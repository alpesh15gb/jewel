from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .db import DB_PATH, app_data_dir, connect, database_path, get_settings, read_db


def backup_dir() -> Path:
    p = app_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _status_path() -> Path:
    return app_data_dir() / "backup-status.json"


def _manifest_path(db_path: Path) -> Path:
    return db_path.with_suffix(db_path.suffix + ".manifest.json")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _record_status(ok: bool, **extra: Any) -> None:
    data = {"ok": bool(ok), "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), **extra}
    try:
        _write_json_atomic(_status_path(), data)
    except OSError:
        pass


def backup_status() -> dict[str, Any]:
    p = _status_path()
    if not p.exists():
        return {"ok": None, "message": "No backup has completed in this installation yet."}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "message": f"Backup status file is unreadable: {exc}"}


def verify_backup(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(p)
    digest = _sha256(p)
    conn = sqlite3.connect(p)
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    manifest_path = _manifest_path(p)
    manifest = None
    checksum_verified = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checksum_verified = manifest.get("sha256") == digest and int(manifest.get("size", -1)) == p.stat().st_size
        except Exception:
            checksum_verified = False
    return {
        "ok": integrity.lower() == "ok" and not fk_rows and checksum_verified is not False,
        "path": str(p),
        "size": p.stat().st_size,
        "sha256": digest,
        "integrity_check": integrity,
        "foreign_key_violations": len(fk_rows),
        "schema_version": user_version,
        "checksum_verified": checksum_verified,
        "manifest": manifest,
    }


def create_backup(label: str = "auto") -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(c for c in label if c.isalnum() or c in "-_ ").strip().replace(" ", "-")[:30] or "backup"
    target = backup_dir() / f"jewellan-{stamp}-{safe_label}.db"
    src = connect()
    dst = sqlite3.connect(target)
    try:
        src.backup(dst, pages=1000, sleep=0.02)
        integrity = str(dst.execute("PRAGMA integrity_check").fetchone()[0])
        fk_rows = dst.execute("PRAGMA foreign_key_check").fetchall()
        schema_version = int(dst.execute("PRAGMA user_version").fetchone()[0])
        if integrity.lower() != "ok":
            raise RuntimeError(f"Backup integrity_check failed: {integrity}")
        if fk_rows:
            raise RuntimeError(f"Backup foreign_key_check found {len(fk_rows)} violation(s)")
    except Exception as exc:
        _record_status(False, label=safe_label, error=str(exc))
        raise
    finally:
        dst.close()
        src.close()
    try:
        with target.open("rb+") as f:
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    digest = _sha256(target)
    manifest = {
        "product": "JewelLAN",
        "created_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "label": safe_label,
        "database": target.name,
        "size": target.stat().st_size,
        "sha256": digest,
        "schema_version": schema_version,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
    }
    _write_json_atomic(_manifest_path(target), manifest)
    verified = verify_backup(target)
    if not verified["ok"]:
        raise RuntimeError(f"Backup verification failed after creation: {verified}")
    _record_status(True, name=target.name, size=target.stat().st_size, sha256=digest, label=safe_label)
    return target


def list_backups() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for p in sorted(backup_dir().glob("jewellan-*.db"), reverse=True):
        st = p.stat()
        manifest = None
        mp = _manifest_path(p)
        if mp.exists():
            try:
                manifest = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                manifest = {"error": "manifest unreadable"}
        result.append(
            {
                "name": p.name,
                "size": st.st_size,
                "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
                "verified_at_creation": bool(isinstance(manifest, dict) and manifest.get("integrity_check") == "ok"),
            }
        )
    return result


def prune_backups(days: int) -> None:
    cutoff = time.time() - max(1, days) * 86400
    for p in backup_dir().glob("jewellan-*.db"):
        if p.stat().st_mtime < cutoff:
            for candidate in (p, _manifest_path(p)):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst, pages=1000, sleep=0.02)
        integrity = str(dst.execute("PRAGMA integrity_check").fetchone()[0])
        fk_rows = dst.execute("PRAGMA foreign_key_check").fetchall()
        if integrity.lower() != "ok" or fk_rows:
            raise RuntimeError(f"Restored database failed verification: integrity={integrity}, foreign_keys={len(fk_rows)}")
    finally:
        dst.close()
        src.close()


def restore_backup(path: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    verified = verify_backup(source)
    if not verified["ok"]:
        raise RuntimeError(f"Backup is not safe to restore: {verified}")
    pre_restore = create_backup("pre-restore")
    target = database_path()
    try:
        _copy_sqlite_database(source, target)
        restored = verify_backup(target)
        if restored["integrity_check"].lower() != "ok" or restored["foreign_key_violations"]:
            raise RuntimeError(f"Restored database failed final verification: {restored}")
    except Exception:
        _copy_sqlite_database(pre_restore, target)
        raise
    _record_status(True, restored_from=source.name, pre_restore=pre_restore.name)
    return {"ok": True, "restored_from": source.name, "pre_restore": pre_restore.name, "sha256": verified["sha256"]}


class BackupWorker(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="JewelLAN-Backup")
        self.stop_event = threading.Event()

    def run(self) -> None:
        if self.stop_event.wait(60):
            return
        while not self.stop_event.is_set():
            try:
                with read_db() as conn:
                    settings = get_settings(conn)
                hours = max(1.0, float(settings.get("backup_interval_hours", 6)))
                retention = max(1, int(float(settings.get("backup_retention_days", 30))))
                create_backup("auto")
                prune_backups(retention)
            except Exception as exc:
                print(f"[backup] {exc}")
                _record_status(False, error=str(exc))
                hours = 1.0
            self.stop_event.wait(hours * 3600)

    def stop(self) -> None:
        self.stop_event.set()
