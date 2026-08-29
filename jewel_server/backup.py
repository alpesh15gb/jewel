from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .db import DB_PATH, app_data_dir, connect, get_settings, read_db


def backup_dir() -> Path:
    p = app_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_backup(label: str = "auto") -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(c for c in label if c.isalnum() or c in "-_ ").strip().replace(" ", "-")[:30] or "backup"
    target = backup_dir() / f"jewellan-{stamp}-{safe_label}.db"
    src = connect()
    dst = sqlite3.connect(target)
    try:
        src.backup(dst, pages=1000, sleep=0.02)
        dst.execute("PRAGMA integrity_check")
    finally:
        dst.close(); src.close()
    return target


def list_backups() -> list[dict]:
    result = []
    for p in sorted(backup_dir().glob("jewellan-*.db"), reverse=True):
        st = p.stat()
        result.append({"name": p.name, "size": st.st_size, "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return result


def prune_backups(days: int) -> None:
    cutoff = time.time() - max(1, days) * 86400
    for p in backup_dir().glob("jewellan-*.db"):
        if p.stat().st_mtime < cutoff:
            try: p.unlink()
            except OSError: pass


def restore_backup(path: str) -> None:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(src)
    chk = sqlite3.connect(src)
    try:
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"Backup failed integrity check: {ok}")
    finally:
        chk.close()
    create_backup("pre-restore")
    shutil.copy2(src, DB_PATH)


class BackupWorker(threading.Thread):
    daemon = True
    def __init__(self):
        super().__init__(name="JewelLAN-Backup")
        self.stop_event = threading.Event()

    def run(self) -> None:
        if self.stop_event.wait(60): return
        while not self.stop_event.is_set():
            try:
                with read_db() as conn:
                    s = get_settings(conn)
                hours = max(1.0, float(s.get("backup_interval_hours", 6)))
                retention = max(1, int(float(s.get("backup_retention_days", 30))))
                create_backup("auto")
                prune_backups(retention)
            except Exception as exc:
                print(f"[backup] {exc}")
                hours = 1.0
            self.stop_event.wait(hours * 3600)

    def stop(self) -> None:
        self.stop_event.set()
