from __future__ import annotations

import os
from pathlib import Path

import run_client


class FakeRoot:
    def __init__(self):
        self.calls = []

    def deiconify(self):
        self.calls.append(("deiconify", None))

    def geometry(self, value):
        self.calls.append(("geometry", value))

    def update_idletasks(self):
        self.calls.append(("update_idletasks", None))


def test_post_login_setup_maps_root_before_transient_dialogs():
    root = FakeRoot()
    run_client._prepare_setup_parent(root)
    assert root.calls == [
        ("deiconify", None),
        ("geometry", "1x1+0+0"),
        ("update_idletasks", None),
    ]


def test_startup_crash_writes_visible_log_location(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        raise RuntimeError("startup regression sentinel")
    except RuntimeError as exc:
        path = run_client._crash_log(exc)
    assert path == Path(tmp_path) / "JewelLAN" / "client-crash.log"
    text = path.read_text(encoding="utf-8")
    assert "startup regression sentinel" in text
    assert "JewelPOS startup failure" in text
