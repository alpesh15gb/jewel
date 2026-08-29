from __future__ import annotations

import re


def read_scale(port: str, baud: int = 9600, timeout: float = 1.0) -> float:
    if not port:
        raise RuntimeError("No weighing scale COM port configured")
    try:
        import serial
    except Exception as e:
        raise RuntimeError("pyserial is not installed") from e
    with serial.Serial(port, baudrate=int(baud), timeout=timeout) as s:
        s.reset_input_buffer()
        raw = s.readline().decode(errors="ignore").strip()
        if not raw:
            s.write(b"\r\n")
            raw = s.readline().decode(errors="ignore").strip()
    # Common scales emit forms such as 'ST,GS,+ 12.345 g' or simply '12.345'.
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", raw)
    if not nums:
        raise RuntimeError(f"Could not parse scale output: {raw!r}")
    return round(float(nums[-1]), 3)
