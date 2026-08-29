from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import secrets
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from .db import read_db, write_db, utcnow

PBKDF2_ROUNDS = 310_000
SESSION_HOURS = 12


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds_s, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256": return False
        salt = base64.b64decode(salt_b64); expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds_s))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, client_name: str | None = None) -> str:
    token = secrets.token_urlsafe(40)
    now = dt.datetime.now(dt.timezone.utc); expires = now + dt.timedelta(hours=SESSION_HOURS)
    with write_db() as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at,client_name) VALUES(?,?,?,?,?,?)",(_token_hash(token), user_id, now.replace(microsecond=0).isoformat(), expires.replace(microsecond=0).isoformat(), utcnow(), client_name))
    return token


def delete_session(token: str) -> None:
    with write_db() as conn: conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return authorization.split(" ", 1)[1].strip()


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _extract_token(authorization); token_hash = _token_hash(token); now = dt.datetime.now(dt.timezone.utc)
    with read_db() as conn:
        row = conn.execute("""SELECT u.id,u.username,u.full_name,u.role,u.active,u.must_change_password,s.expires_at
               FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",(token_hash,)).fetchone()
    if not row: raise HTTPException(status_code=401, detail="Session expired or invalid")
    try: expires = dt.datetime.fromisoformat(row["expires_at"])
    except ValueError: raise HTTPException(status_code=401, detail="Session invalid")
    if expires <= now or not row["active"]:
        with write_db() as conn: conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        raise HTTPException(status_code=401, detail="Session expired or user inactive")
    try:
        with write_db() as conn: conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (utcnow(), token_hash))
    except Exception: pass
    return dict(row) | {"token_hash": token_hash}


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "manager": {"dashboard", "inventory.read", "inventory.write", "sales", "contacts", "purchases", "repairs", "orders", "approvals", "audit", "reports", "rates", "backup"},
    "cashier": {"dashboard", "inventory.read", "sales", "contacts", "repairs", "orders"},
    "inventory": {"dashboard", "inventory.read", "inventory.write", "contacts", "purchases", "audit", "approvals", "rates"},
    "accounts": {"dashboard", "inventory.read", "contacts", "reports", "rates", "backup"},
}


def require(permission: str):
    def dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        perms = ROLE_PERMISSIONS.get(user["role"], set())
        if "*" not in perms and permission not in perms: raise HTTPException(status_code=403, detail="Permission denied")
        return user
    return dep


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
