from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - graceful fallback when PG deps are absent
    psycopg = None
    dict_row = None

from .config import AUTH_AUDIT_FILE, PG_DB, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER, RUNS_DIR, TASKS_DIR, USERS_FILE, SESSIONS_FILE


def _json_default(value: Any) -> Any:
    return value if value is not None else {}


class PostgresStore:
    def __init__(self) -> None:
        self.enabled = bool(psycopg) and all([PG_HOST, PG_DB, PG_USER])

    def connect(self):
        if not self.enabled:
            raise RuntimeError("postgres is not configured")
        return psycopg.connect(
            host=PG_HOST,
            port=PG_PORT,
            dbname=PG_DB,
            user=PG_USER,
            password=PG_PASSWORD,
            row_factory=dict_row,
        )

    def ensure_schema(self) -> None:
        if not self.enabled:
            return
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    username TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    password_change_required BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES auth_users(username) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at_ts BIGINT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions (expires_at_ts);
                CREATE TABLE IF NOT EXISTS auth_audit (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    client_ip TEXT,
                    detail TEXT
                );
                CREATE TABLE IF NOT EXISTS batch_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    project_code TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    submitted INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    progress_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
                    gpu_workers JSONB NOT NULL DEFAULT '[]'::jsonb,
                    backend JSONB NOT NULL DEFAULT '{}'::jsonb,
                    input_preview JSONB NOT NULL DEFAULT '[]'::jsonb,
                    items JSONB NOT NULL DEFAULT '[]'::jsonb,
                    error TEXT NOT NULL DEFAULT '',
                    csv_path TEXT NOT NULL DEFAULT '',
                    html_report_path TEXT NOT NULL DEFAULT '',
                    last_gpu_index INTEGER,
                    last_chunk_size INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_batch_tasks_created_at ON batch_tasks (created_at DESC);
                CREATE TABLE IF NOT EXISTS batch_task_items (
                    id BIGSERIAL PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES batch_tasks(task_id) ON DELETE CASCADE,
                    row_index INTEGER NOT NULL,
                    compound_name TEXT NOT NULL DEFAULT '',
                    smiles TEXT NOT NULL DEFAULT '',
                    gpu_index INTEGER,
                    device TEXT NOT NULL DEFAULT '',
                    overall_admet_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    oral_f DOUBLE PRECISION,
                    hia DOUBLE PRECISION,
                    caco2 DOUBLE PRECISION,
                    half_life_h DOUBLE PRECISION,
                    cyp3a4_inhibitor TEXT NOT NULL DEFAULT '',
                    herg_risk TEXT NOT NULL DEFAULT '',
                    dili_risk TEXT NOT NULL DEFAULT '',
                    development_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_task_items_task_row
                    ON batch_task_items (task_id, row_index);
                CREATE INDEX IF NOT EXISTS idx_batch_task_items_task_score
                    ON batch_task_items (task_id, overall_admet_score DESC);
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    compound_name TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    overall_risk TEXT NOT NULL,
                    admet_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    recommended_regimen TEXT NOT NULL DEFAULT '',
                    report_path TEXT NOT NULL DEFAULT '',
                    json_path TEXT NOT NULL DEFAULT '',
                    html_report_path TEXT NOT NULL DEFAULT '',
                    project_name TEXT NOT NULL DEFAULT '未命名项目',
                    project_code TEXT NOT NULL DEFAULT 'P58',
                    owner TEXT NOT NULL DEFAULT 'analyst',
                    access_level TEXT NOT NULL DEFAULT 'internal',
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    fit_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    project_json JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created_at ON pipeline_runs (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project_code ON pipeline_runs (project_code);
                """
            )
            cur.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_login_at TEXT;")
            cur.execute("ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS request_json JSONB NOT NULL DEFAULT '{}'::jsonb;")
            cur.execute("ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS result_json JSONB NOT NULL DEFAULT '{}'::jsonb;")
            conn.commit()

    def migrate_from_json_if_needed(self) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM auth_users")
            user_count = int(cur.fetchone()["count"])
            cur.execute("SELECT COUNT(*) AS count FROM batch_tasks")
            task_count = int(cur.fetchone()["count"])
            cur.execute("SELECT COUNT(*) AS count FROM batch_task_items")
            task_item_count = int(cur.fetchone()["count"])
            cur.execute("SELECT COUNT(*) AS count FROM pipeline_runs")
            run_count = int(cur.fetchone()["count"])
            conn.commit()
        if user_count == 0:
            self._import_users_json()
            self._import_sessions_json()
            self._import_auth_audit_jsonl()
        if task_count == 0:
            self._import_task_jsons()
        if task_item_count == 0:
            self._sync_task_items_from_tasks()
        if run_count == 0:
            self._import_run_jsons()
        self._sync_run_jsons()

    def _import_users_json(self) -> None:
        if not USERS_FILE.exists():
            return
        users = json.loads(USERS_FILE.read_text(encoding="utf-8-sig"))
        with self.connect() as conn, conn.cursor() as cur:
            for username, row in users.items():
                cur.execute(
                    """
                    INSERT INTO auth_users (username, display_name, role, active, password_change_required, created_at, updated_at, password_salt, password_hash, last_login_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (username) DO UPDATE SET
                      display_name = EXCLUDED.display_name,
                      role = EXCLUDED.role,
                      active = EXCLUDED.active,
                      password_change_required = EXCLUDED.password_change_required,
                      created_at = EXCLUDED.created_at,
                      updated_at = EXCLUDED.updated_at,
                      password_salt = EXCLUDED.password_salt,
                      password_hash = EXCLUDED.password_hash,
                      last_login_at = EXCLUDED.last_login_at
                    """,
                    (
                        username,
                        row.get("display_name", username),
                        row.get("role", "viewer"),
                        bool(row.get("active", True)),
                        bool(row.get("password_change_required", False)),
                        row.get("created_at", ""),
                        row.get("updated_at"),
                        row.get("password_salt", ""),
                        row.get("password_hash", ""),
                        row.get("last_login_at"),
                    ),
                )
            conn.commit()

    def _import_sessions_json(self) -> None:
        if not SESSIONS_FILE.exists():
            return
        sessions = json.loads(SESSIONS_FILE.read_text(encoding="utf-8-sig"))
        with self.connect() as conn, conn.cursor() as cur:
            for token, row in sessions.items():
                cur.execute(
                    """
                    INSERT INTO auth_sessions (token, username, created_at, expires_at_ts)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (token) DO UPDATE SET
                      username = EXCLUDED.username,
                      created_at = EXCLUDED.created_at,
                      expires_at_ts = EXCLUDED.expires_at_ts
                    """,
                    (token, row.get("username", ""), row.get("created_at", ""), int(row.get("expires_at_ts", 0))),
                )
            conn.commit()

    def _import_auth_audit_jsonl(self) -> None:
        if not AUTH_AUDIT_FILE.exists():
            return
        with self.connect() as conn, conn.cursor() as cur:
            for line in AUTH_AUDIT_FILE.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                cur.execute(
                    """
                    INSERT INTO auth_audit (created_at, action, username, role, client_ip, detail)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        row.get("created_at", ""),
                        row.get("action", ""),
                        row.get("username", ""),
                        row.get("role", "viewer"),
                        row.get("client_ip", ""),
                        row.get("detail", ""),
                    ),
                )
            conn.commit()

    def _import_task_jsons(self) -> None:
        if not TASKS_DIR.exists():
            return
        with self.connect() as conn, conn.cursor() as cur:
            for path in sorted(TASKS_DIR.glob("task_*.json")):
                try:
                    row = json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                cur.execute(
                    """
                    INSERT INTO batch_tasks (
                        task_id, task_type, status, created_at, updated_at, created_by, project_name, project_code, notes,
                        submitted, completed, progress_pct, gpu_workers, backend, input_preview, items, error, csv_path,
                        html_report_path, last_gpu_index, last_chunk_size
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s)
                    ON CONFLICT (task_id) DO NOTHING
                    """,
                    (
                        row.get("task_id", path.stem),
                        row.get("task_type", "admet_batch"),
                        row.get("status", "completed"),
                        row.get("created_at", ""),
                        row.get("updated_at", row.get("created_at", "")),
                        row.get("created_by", ""),
                        row.get("project_name", "ADMET 批量筛选"),
                        row.get("project_code", "P58-BATCH"),
                        row.get("notes", ""),
                        int(row.get("submitted", 0)),
                        int(row.get("completed", 0)),
                        float(row.get("progress_pct", 0)),
                        json.dumps(row.get("gpu_workers", []), ensure_ascii=False),
                        json.dumps(_json_default(row.get("backend")), ensure_ascii=False),
                        json.dumps(row.get("input_preview", []), ensure_ascii=False),
                        json.dumps(row.get("items", []), ensure_ascii=False),
                        row.get("error", ""),
                        row.get("csv_path", ""),
                        row.get("html_report_path", ""),
                        row.get("last_gpu_index"),
                        row.get("last_chunk_size"),
                    ),
                )
            conn.commit()

    def _import_run_jsons(self) -> None:
        if not RUNS_DIR.exists():
            return
        for path in sorted(RUNS_DIR.glob("run_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            self.upsert_run(payload, str(path))

    def _sync_task_items_from_tasks(self) -> None:
        for row in self.list_tasks():
            task_id = str(row.get("task_id", "")).strip()
            if not task_id:
                continue
            self.replace_task_items(task_id, row.get("items", []) or [])

    def _sync_run_jsons(self) -> None:
        if not RUNS_DIR.exists():
            return
        for path in sorted(RUNS_DIR.glob("run_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            self.upsert_run(payload, str(path))

    def fetch_users(self) -> Dict[str, Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM auth_users ORDER BY username")
            rows = cur.fetchall()
        return {row["username"]: dict(row) for row in rows}

    def upsert_user(self, username: str, row: Dict[str, Any]) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_users (username, display_name, role, active, password_change_required, created_at, updated_at, password_salt, password_hash, last_login_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (username) DO UPDATE SET
                  display_name = EXCLUDED.display_name,
                  role = EXCLUDED.role,
                  active = EXCLUDED.active,
                  password_change_required = EXCLUDED.password_change_required,
                  created_at = EXCLUDED.created_at,
                  updated_at = EXCLUDED.updated_at,
                  password_salt = EXCLUDED.password_salt,
                  password_hash = EXCLUDED.password_hash,
                  last_login_at = EXCLUDED.last_login_at
                """,
                (
                    username,
                    row.get("display_name", username),
                    row.get("role", "viewer"),
                    bool(row.get("active", True)),
                    bool(row.get("password_change_required", False)),
                    row.get("created_at", ""),
                    row.get("updated_at"),
                    row.get("password_salt", ""),
                    row.get("password_hash", ""),
                    row.get("last_login_at"),
                ),
            )
            conn.commit()


    def delete_user(self, username: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM auth_users WHERE username = %s", (username,))
            conn.commit()

    def fetch_sessions(self, now_ts: int) -> Dict[str, Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM auth_sessions WHERE expires_at_ts <= %s", (now_ts,))
            cur.execute("SELECT token, username, created_at, expires_at_ts FROM auth_sessions")
            rows = cur.fetchall()
            conn.commit()
        return {row["token"]: dict(row) for row in rows}

    def upsert_session(self, token: str, row: Dict[str, Any]) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_sessions (token, username, created_at, expires_at_ts)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (token) DO UPDATE SET
                  username = EXCLUDED.username,
                  created_at = EXCLUDED.created_at,
                  expires_at_ts = EXCLUDED.expires_at_ts
                """,
                (token, row.get("username", ""), row.get("created_at", ""), int(row.get("expires_at_ts", 0))),
            )
            conn.commit()

    def delete_session(self, token: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM auth_sessions WHERE token = %s", (token,))
            conn.commit()

    def insert_auth_audit(self, row: Dict[str, Any]) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_audit (created_at, action, username, role, client_ip, detail) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    row.get("created_at", ""),
                    row.get("action", ""),
                    row.get("username", ""),
                    row.get("role", "viewer"),
                    row.get("client_ip", ""),
                    row.get("detail", ""),
                ),
            )
            conn.commit()

    def list_auth_audit(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT created_at, action, username, role, client_ip, detail FROM auth_audit ORDER BY id DESC")
            return [dict(row) for row in cur.fetchall()]

    def upsert_task(self, payload: Dict[str, Any]) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO batch_tasks (
                    task_id, task_type, status, created_at, updated_at, created_by, project_name, project_code, notes,
                    submitted, completed, progress_pct, gpu_workers, backend, input_preview, items, error, csv_path,
                    html_report_path, last_gpu_index, last_chunk_size
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s)
                ON CONFLICT (task_id) DO UPDATE SET
                    task_type = EXCLUDED.task_type,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    created_by = EXCLUDED.created_by,
                    project_name = EXCLUDED.project_name,
                    project_code = EXCLUDED.project_code,
                    notes = EXCLUDED.notes,
                    submitted = EXCLUDED.submitted,
                    completed = EXCLUDED.completed,
                    progress_pct = EXCLUDED.progress_pct,
                    gpu_workers = EXCLUDED.gpu_workers,
                    backend = EXCLUDED.backend,
                    input_preview = EXCLUDED.input_preview,
                    items = EXCLUDED.items,
                    error = EXCLUDED.error,
                    csv_path = EXCLUDED.csv_path,
                    html_report_path = EXCLUDED.html_report_path,
                    last_gpu_index = EXCLUDED.last_gpu_index,
                    last_chunk_size = EXCLUDED.last_chunk_size
                """,
                (
                    payload.get("task_id"),
                    payload.get("task_type", "admet_batch"),
                    payload.get("status", "queued"),
                    payload.get("created_at", ""),
                    payload.get("updated_at", payload.get("created_at", "")),
                    payload.get("created_by", ""),
                    payload.get("project_name", "ADMET 批量筛选"),
                    payload.get("project_code", "P58-BATCH"),
                    payload.get("notes", ""),
                    int(payload.get("submitted", 0)),
                    int(payload.get("completed", 0)),
                    float(payload.get("progress_pct", 0)),
                    json.dumps(payload.get("gpu_workers", []), ensure_ascii=False),
                    json.dumps(_json_default(payload.get("backend")), ensure_ascii=False),
                    json.dumps(payload.get("input_preview", []), ensure_ascii=False),
                    json.dumps(payload.get("items", []), ensure_ascii=False),
                    payload.get("error", ""),
                    payload.get("csv_path", ""),
                    payload.get("html_report_path", ""),
                    payload.get("last_gpu_index"),
                    payload.get("last_chunk_size"),
                ),
            )
            conn.commit()
        self.replace_task_items(str(payload.get("task_id", "")), payload.get("items", []) or [])

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM batch_tasks WHERE task_id = %s", (task_id,))
            row = cur.fetchone()
        if not row:
            raise FileNotFoundError(task_id)
        payload = dict(row)
        payload["items"] = self.list_task_items(task_id)
        return payload

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM batch_tasks ORDER BY created_at DESC")
            return [dict(row) for row in cur.fetchall()]

    def replace_task_items(self, task_id: str, items: List[Dict[str, Any]]) -> None:
        if not task_id:
            return
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM batch_task_items WHERE task_id = %s", (task_id,))
            for idx, item in enumerate(items):
                cur.execute(
                    """
                    INSERT INTO batch_task_items (
                        task_id, row_index, compound_name, smiles, gpu_index, device, overall_admet_score,
                        oral_f, hia, caco2, half_life_h, cyp3a4_inhibitor, herg_risk, dili_risk,
                        development_flags, raw_json
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                    """,
                    (
                        task_id,
                        idx,
                        item.get("compound_name", "") or "",
                        item.get("smiles", "") or "",
                        item.get("gpu_index"),
                        item.get("device", "") or "",
                        float(item.get("overall_admet_score", 0) or 0),
                        item.get("oral_f"),
                        item.get("hia"),
                        item.get("caco2"),
                        item.get("half_life_h"),
                        item.get("cyp3a4_inhibitor", "") or "",
                        item.get("herg_risk", "") or "",
                        item.get("dili_risk", "") or "",
                        json.dumps(item.get("development_flags", []), ensure_ascii=False),
                        json.dumps(item.get("raw", {}) or {}, ensure_ascii=False),
                    ),
                )
            conn.commit()

    def list_task_items(self, task_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT row_index, compound_name, smiles, gpu_index, device, overall_admet_score,
                       oral_f, hia, caco2, half_life_h, cyp3a4_inhibitor, herg_risk, dili_risk,
                       development_flags, raw_json
                FROM batch_task_items
                WHERE task_id = %s
                ORDER BY row_index ASC
                """,
                (task_id,),
            )
            rows = cur.fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            payload["raw"] = payload.pop("raw_json", {}) or {}
            items.append(payload)
        return items

    def upsert_run(self, payload: Dict[str, Any], json_path: str) -> None:
        summary = (payload.get("summary", {}) or {})
        request = (payload.get("request", {}) or {})
        project = (request.get("project", {}) or {})
        result = (payload.get("result", {}) or {})
        fit_summary = ((payload.get("result", {}) or {}).get("fit_summary", {}) or {})
        run_id = str(summary.get("run_id", "")).strip()
        if not run_id:
            raise ValueError("run payload is missing run_id")
        html_report_path = f"/api/v1/pipeline58/runs/{run_id}/report/html"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, created_at, compound_name, target_name, overall_risk, admet_score, recommended_regimen,
                    report_path, json_path, html_report_path, project_name, project_code, owner, access_level, tags,
                    fit_enabled, summary_json, project_json, request_json, result_json
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    created_at = EXCLUDED.created_at,
                    compound_name = EXCLUDED.compound_name,
                    target_name = EXCLUDED.target_name,
                    overall_risk = EXCLUDED.overall_risk,
                    admet_score = EXCLUDED.admet_score,
                    recommended_regimen = EXCLUDED.recommended_regimen,
                    report_path = EXCLUDED.report_path,
                    json_path = EXCLUDED.json_path,
                    html_report_path = EXCLUDED.html_report_path,
                    project_name = EXCLUDED.project_name,
                    project_code = EXCLUDED.project_code,
                    owner = EXCLUDED.owner,
                    access_level = EXCLUDED.access_level,
                    tags = EXCLUDED.tags,
                    fit_enabled = EXCLUDED.fit_enabled,
                    summary_json = EXCLUDED.summary_json,
                    project_json = EXCLUDED.project_json,
                    request_json = EXCLUDED.request_json,
                    result_json = EXCLUDED.result_json
                """,
                (
                    run_id,
                    summary.get("created_at", ""),
                    summary.get("compound_name", ""),
                    summary.get("target_name", ""),
                    summary.get("overall_risk", ""),
                    float(summary.get("admet_score", 0) or 0),
                    summary.get("recommended_regimen", ""),
                    summary.get("report_path", ""),
                    json_path,
                    html_report_path,
                    project.get("project_name", "未命名项目"),
                    project.get("project_code", "P58"),
                    project.get("owner", "analyst"),
                    project.get("access_level", "internal"),
                    json.dumps(project.get("tags", []), ensure_ascii=False),
                    bool(fit_summary.get("enabled", False)),
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(project, ensure_ascii=False),
                    json.dumps(request, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            conn.commit()

    def list_runs(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, created_at, compound_name, target_name, overall_risk, admet_score,
                       recommended_regimen, report_path
                FROM pipeline_runs
                ORDER BY created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def list_run_indexes(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, created_at, compound_name, target_name, overall_risk, admet_score,
                       recommended_regimen, report_path, json_path, html_report_path, project_name,
                       project_code, owner, access_level, tags, fit_enabled
                FROM pipeline_runs
                ORDER BY created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def get_run_payload(self, run_id: str) -> Dict[str, Any]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT summary_json, request_json, result_json
                FROM pipeline_runs
                WHERE run_id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
        if not row:
            raise FileNotFoundError(run_id)
        return {
            "summary": row.get("summary_json") or {},
            "request": row.get("request_json") or {},
            "result": row.get("result_json") or {},
        }

    def list_project_indexes(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    project_code,
                    MAX(project_name) AS project_name,
                    MAX(owner) AS owner,
                    MAX(access_level) AS access_level,
                    COALESCE(
                      (
                        ARRAY_AGG(tags ORDER BY created_at DESC)
                        FILTER (WHERE tags IS NOT NULL)
                      )[1],
                      '[]'::jsonb
                    ) AS tags,
                    COUNT(*) AS run_count,
                    MAX(created_at) AS last_run_at,
                    (
                      ARRAY_AGG(overall_risk ORDER BY created_at DESC)
                      FILTER (WHERE overall_risk IS NOT NULL)
                    )[1] AS last_overall_risk
                FROM pipeline_runs
                GROUP BY project_code
                ORDER BY last_run_at DESC NULLS LAST
                """
            )
            return [dict(row) for row in cur.fetchall()]

    def list_run_audit_indexes(self) -> List[Dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    run_id,
                    created_at,
                    project_code,
                    project_name,
                    owner,
                    access_level,
                    compound_name,
                    overall_risk,
                    fit_enabled
                FROM pipeline_runs
                ORDER BY created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]


PG = PostgresStore()
