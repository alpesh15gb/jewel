from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS_HASH = "0" * 64


def compute_audit_hash(
    prev_hash: str | None,
    user_id: Any,
    action: Any,
    entity: Any,
    entity_id: Any,
    details_json: Any,
    client_ip: Any,
    created_at: Any,
) -> str:
    payload = [
        prev_hash or GENESIS_HASH,
        "" if user_id is None else str(user_id),
        "" if action is None else str(action),
        "" if entity is None else str(entity),
        "" if entity_id is None else str(entity_id),
        "" if details_json is None else str(details_json),
        "" if client_ip is None else str(client_ip),
        "" if created_at is None else str(created_at),
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_audit_chain(conn, max_errors: int = 20) -> dict[str, Any]:
    prev = GENESIS_HASH
    errors: list[dict[str, Any]] = []
    count = 0
    rows = conn.execute(
        "SELECT id,user_id,action,entity,entity_id,details_json,client_ip,created_at,prev_hash,entry_hash "
        "FROM audit_log ORDER BY id"
    ).fetchall()
    for row in rows:
        count += 1
        stored_prev = row["prev_hash"] or GENESIS_HASH
        expected = compute_audit_hash(
            prev,
            row["user_id"],
            row["action"],
            row["entity"],
            row["entity_id"],
            row["details_json"],
            row["client_ip"],
            row["created_at"],
        )
        if stored_prev != prev or (row["entry_hash"] or "") != expected:
            if len(errors) < max_errors:
                errors.append(
                    {
                        "id": row["id"],
                        "stored_prev": stored_prev,
                        "expected_prev": prev,
                        "stored_hash": row["entry_hash"],
                        "expected_hash": expected,
                    }
                )
        prev = row["entry_hash"] or expected
    return {"ok": not errors, "entries": count, "errors": errors, "head_hash": prev}
