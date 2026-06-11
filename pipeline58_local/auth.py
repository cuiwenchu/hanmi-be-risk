from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AUTH_AUDIT_FILE, SESSIONS_FILE, USERS_FILE, ensure_data_dirs
from .db import PG


ROLE_LEVELS = {
    "viewer": 0,
    "analyst": 1,
    "admin": 2,
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AuthService:
    def __init__(self) -> None:
        ensure_data_dirs()
        if PG.enabled:
            PG.ensure_schema()
            PG.migrate_from_json_if_needed()
        self._ensure_bootstrap_admin()

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _append_audit(self, action: str, username: str, role: str, client_ip: str = "", detail: str = "") -> None:
        row = {
            "created_at": now_iso(),
            "action": action,
            "username": username,
            "role": role,
            "client_ip": client_ip,
            "detail": detail,
        }
        if PG.enabled:
            PG.insert_auth_audit(row)
            return
        with AUTH_AUDIT_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _hash_password(self, password: str, salt_hex: str) -> str:
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 240000)
        return derived.hex()

    def _new_password_bundle(self, password: str) -> Dict[str, str]:
        salt = secrets.token_hex(16)
        return {
            "salt": salt,
            "hash": self._hash_password(password, salt),
        }

    def _load_users(self) -> Dict[str, Dict[str, Any]]:
        if PG.enabled:
            return PG.fetch_users()
        return self._read_json(USERS_FILE, {})

    def _save_users(self, users: Dict[str, Dict[str, Any]]) -> None:
        if PG.enabled:
            for username, row in users.items():
                PG.upsert_user(username, row)
            return
        self._write_json(USERS_FILE, users)

    def _load_sessions(self) -> Dict[str, Dict[str, Any]]:
        now_ts = int(time.time())
        if PG.enabled:
            return PG.fetch_sessions(now_ts)
        sessions = self._read_json(SESSIONS_FILE, {})
        alive = {
            token: row
            for token, row in sessions.items()
            if int(row.get("expires_at_ts", 0)) > now_ts
        }
        if alive != sessions:
            self._write_json(SESSIONS_FILE, alive)
        return alive

    def _save_sessions(self, sessions: Dict[str, Dict[str, Any]]) -> None:
        if PG.enabled:
            existing = PG.fetch_sessions(int(time.time()))
            for token in list(existing):
                if token not in sessions:
                    PG.delete_session(token)
            for token, row in sessions.items():
                PG.upsert_session(token, row)
            return
        self._write_json(SESSIONS_FILE, sessions)

    def _public_user(self, username: str, row: Dict[str, Any]) -> Dict[str, Any]:
        display_name = str(row.get("display_name", username) or "").strip()
        if not display_name or set(display_name) <= {"?"}:
            display_name = "系统管理员" if str(row.get("role", "viewer")) == "admin" else username
        return {
            "username": username,
            "display_name": display_name,
            "role": row.get("role", "viewer"),
            "active": bool(row.get("active", True)),
            "password_change_required": bool(row.get("password_change_required", False)),
            "last_login_at": row.get("last_login_at"),
        }

    def _ensure_bootstrap_admin(self) -> None:
        users = self._load_users()
        if users:
            return
        username = os.environ.get("PIPELINE58_ADMIN_USERNAME", "admin").strip() or "admin"
        password = os.environ.get("PIPELINE58_ADMIN_PASSWORD", "").strip()
        if not password:
            raise RuntimeError("PIPELINE58_ADMIN_PASSWORD is required for initial administrator creation")
        bundle = self._new_password_bundle(password)
        users[username] = {
            "display_name": "系统管理员",
            "role": "admin",
            "active": True,
            "password_change_required": False,
            "created_at": now_iso(),
            "password_salt": bundle["salt"],
            "password_hash": bundle["hash"],
        }
        self._save_users(users)
        self._append_audit("bootstrap_admin", username, "admin", detail="Created default admin account")

    def authenticate(self, username: str, password: str, client_ip: str = "") -> Dict[str, Any]:
        username = username.strip()
        users = self._load_users()
        row = users.get(username)
        if not row or not row.get("active", True):
            raise ValueError("用户名或密码错误")
        expected = row.get("password_hash", "")
        salt = row.get("password_salt", "")
        if not expected or not salt or self._hash_password(password, salt) != expected:
            self._append_audit("login_failed", username, row.get("role", "viewer"), client_ip, "Bad password")
            raise ValueError("用户名或密码错误")
        token = f"p58_{secrets.token_urlsafe(24)}"
        now_ts = int(time.time())
        sessions = self._load_sessions()
        sessions[token] = {
            "username": username,
            "created_at": now_iso(),
            "expires_at_ts": now_ts + 60 * 60 * 24 * 30,
        }
        row["last_login_at"] = now_iso()
        row["updated_at"] = now_iso()
        users[username] = row
        self._save_users(users)
        self._save_sessions(sessions)
        self._append_audit("login_success", username, row.get("role", "viewer"), client_ip, "Interactive login")
        return {
            "token": token,
            "user": self._public_user(username, row),
        }

    def logout(self, token: str, client_ip: str = "") -> None:
        sessions = self._load_sessions()
        session = sessions.pop(token, None)
        self._save_sessions(sessions)
        if session:
            users = self._load_users()
            row = users.get(session.get("username", ""), {})
            self._append_audit("logout", session.get("username", ""), row.get("role", "viewer"), client_ip, "Session closed")

    def get_current_user(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        sessions = self._load_sessions()
        session = sessions.get(token)
        if not session:
            return None
        users = self._load_users()
        username = str(session.get("username", ""))
        row = users.get(username)
        if not row or not row.get("active", True):
            return None
        return self._public_user(username, row)

    def _latest_login_success_map(self) -> Dict[str, str]:
        latest: Dict[str, str] = {}
        for row in self.list_auth_audit():
            if str(row.get("action", "")) != "login_success":
                continue
            username = str(row.get("username", "")).strip()
            created_at = str(row.get("created_at", "")).strip()
            if not username or not created_at:
                continue
            prev = latest.get(username)
            if prev is None or created_at > prev:
                latest[username] = created_at
        return latest

    def list_users(self) -> List[Dict[str, Any]]:
        users = self._load_users()
        login_map = self._latest_login_success_map()
        rows: List[Dict[str, Any]] = []
        for username, row in users.items():
            public_row = self._public_user(username, row)
            if not public_row.get("last_login_at"):
                public_row["last_login_at"] = login_map.get(username)
            rows.append(public_row)
        rows.sort(key=lambda item: (ROLE_LEVELS.get(item["role"], -1), item["username"]), reverse=True)
        return rows



    def create_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
        display_name: str = "",
        active: bool = True,
        actor: str = "",
        client_ip: str = "",
    ) -> Dict[str, Any]:
        username = str(username or "").strip()
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if any(ch.isspace() for ch in username):
            raise ValueError("Username cannot contain spaces")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
        if any(ch not in allowed for ch in username):
            raise ValueError("Username can only use letters, numbers, _ . -")

        role = str(role or "viewer").strip().lower()
        if role not in ROLE_LEVELS:
            raise ValueError("Role must be viewer / analyst / admin")

        password = str(password or "")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")

        users = self._load_users()
        if username in users:
            raise ValueError("User already exists")

        display_name = str(display_name or "").strip() or username
        bundle = self._new_password_bundle(password)
        users[username] = {
            "display_name": display_name,
            "role": role,
            "active": bool(active),
            "password_change_required": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "password_salt": bundle["salt"],
            "password_hash": bundle["hash"],
        }
        self._save_users(users)

        actor_name = actor or username
        actor_role = users.get(actor_name, {}).get("role", role)
        self._append_audit(
            "user_create",
            actor_name,
            actor_role,
            client_ip,
            f"created={username}; role={role}; active={bool(active)}",
        )
        return self._public_user(username, users[username])

    def admin_reset_password(
        self,
        username: str,
        new_password: str,
        actor: str = "",
        client_ip: str = "",
    ) -> Dict[str, Any]:
        username = str(username or "").strip()
        if len(str(new_password or "")) < 6:
            raise ValueError("New password must be at least 6 characters")
        users = self._load_users()
        row = users.get(username)
        if not row:
            raise ValueError("User not found")
        bundle = self._new_password_bundle(str(new_password))
        row["password_salt"] = bundle["salt"]
        row["password_hash"] = bundle["hash"]
        row["password_change_required"] = False
        row["updated_at"] = now_iso()
        users[username] = row
        self._save_users(users)
        actor_name = actor or username
        actor_role = users.get(actor_name, {}).get("role", "admin")
        self._append_audit("user_reset_password", actor_name, actor_role, client_ip, f"target={username}")
        return self._public_user(username, row)

    def admin_set_user_active(
        self,
        username: str,
        active: bool,
        actor: str = "",
        client_ip: str = "",
    ) -> Dict[str, Any]:
        username = str(username or "").strip()
        users = self._load_users()
        row = users.get(username)
        if not row:
            raise ValueError("User not found")
        actor_name = str(actor or "").strip()
        if actor_name and actor_name == username and not bool(active):
            raise ValueError("Cannot operate on the current logged-in account")
        if row.get("role") == "admin" and row.get("active", True) and not bool(active):
            other_admins = [
                u for u, r in users.items()
                if u != username and r.get("role") == "admin" and bool(r.get("active", True))
            ]
            if not other_admins:
                raise ValueError("At least one active admin must be kept")
        row["active"] = bool(active)
        row["updated_at"] = now_iso()
        users[username] = row
        self._save_users(users)
        actor_role = users.get(actor_name, {}).get("role", "admin") if actor_name else "admin"
        self._append_audit("user_set_active", actor_name or username, actor_role, client_ip, f"target={username}; active={bool(active)}")
        return self._public_user(username, row)

    def admin_delete_user(
        self,
        username: str,
        actor: str = "",
        client_ip: str = "",
    ) -> Dict[str, Any]:
        username = str(username or "").strip()
        users = self._load_users()
        row = users.get(username)
        if not row:
            raise ValueError("User not found")
        actor_name = str(actor or "").strip()
        if actor_name and actor_name == username:
            raise ValueError("Cannot operate on the current logged-in account")
        if row.get("role") == "admin" and bool(row.get("active", True)):
            other_admins = [
                u for u, r in users.items()
                if u != username and r.get("role") == "admin" and bool(r.get("active", True))
            ]
            if not other_admins:
                raise ValueError("At least one active admin must be kept")

        if PG.enabled:
            PG.delete_user(username)
        else:
            users.pop(username, None)
            self._save_users(users)

        actor_role = users.get(actor_name, {}).get("role", "admin") if actor_name else "admin"
        self._append_audit("user_delete", actor_name or username, actor_role, client_ip, f"target={username}")
        return {"username": username, "deleted": True}

    def change_password(self, username: str, current_password: str, new_password: str, client_ip: str = "") -> None:
        if len(new_password) < 6:
            raise ValueError("New password must be at least 6 characters")
        users = self._load_users()
        row = users.get(username)
        if not row:
            raise ValueError("User not found")
        salt = row.get("password_salt", "")
        if self._hash_password(current_password, salt) != row.get("password_hash", ""):
            raise ValueError("Current password is incorrect")
        bundle = self._new_password_bundle(new_password)
        row["password_salt"] = bundle["salt"]
        row["password_hash"] = bundle["hash"]
        row["password_change_required"] = False
        row["updated_at"] = now_iso()
        users[username] = row
        self._save_users(users)
        self._append_audit("password_change", username, row.get("role", "viewer"), client_ip, "Password updated")

    def list_auth_audit(self) -> List[Dict[str, Any]]:
        if PG.enabled:
            return PG.list_auth_audit()
        rows: List[Dict[str, Any]] = []
        if not AUTH_AUDIT_FILE.exists():
            return rows
        for line in reversed(AUTH_AUDIT_FILE.read_text(encoding="utf-8-sig").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

def role_allows(role: str, required_role: str) -> bool:
    return ROLE_LEVELS.get(role, -1) >= ROLE_LEVELS.get(required_role, 999)
