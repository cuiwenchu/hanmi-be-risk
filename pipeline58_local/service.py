from __future__ import annotations

import contextlib
import concurrent.futures
import csv
import html
import io
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import threading
import uuid
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from .config import REPORTS_DIR, RUNS_DIR, TASKS_DIR, Pipeline58Settings
from .db import PG
from .models import ADMETBatchItem, ADMETBatchRequest, ADMETBatchTaskRequest, Pipeline58Request, Pipeline58RunDetail, Pipeline58RunSummary


ATOMIC_WEIGHTS = {
    "H": 1.008,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Br": 79.904,
    "I": 126.904,
}

TOKEN_PATTERN = re.compile(r"Cl|Br|[A-Z][a-z]?")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def linear_interpolate(points: List[Dict[str, float]], x_key: str, y_key: str, target_x: float) -> Optional[float]:
    if not points:
        return None
    ordered = sorted(points, key=lambda item: float(item.get(x_key, 0.0)))
    if target_x <= float(ordered[0].get(x_key, 0.0)):
        return float(ordered[0].get(y_key, 0.0))
    if target_x >= float(ordered[-1].get(x_key, 0.0)):
        return float(ordered[-1].get(y_key, 0.0))
    for left, right in zip(ordered, ordered[1:]):
        x1 = float(left.get(x_key, 0.0))
        x2 = float(right.get(x_key, 0.0))
        if x1 <= target_x <= x2:
            if abs(x2 - x1) < 1e-9:
                return float(left.get(y_key, 0.0))
            y1 = float(left.get(y_key, 0.0))
            y2 = float(right.get(y_key, 0.0))
            weight = (target_x - x1) / (x2 - x1)
            return y1 + (y2 - y1) * weight
    return None


def smiles_descriptors(smiles: str) -> Dict[str, float]:
    tokens = TOKEN_PATTERN.findall(smiles)
    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    atom_count = sum(counts.values())
    mw = sum(ATOMIC_WEIGHTS.get(token, 12.0) * count for token, count in counts.items())
    carbon = counts.get("C", 0)
    hetero = atom_count - carbon
    rings = sum(1 for char in smiles if char.isdigit()) / 2.0
    aromatic = sum(1 for char in smiles if char in "cnosp")
    halogen = counts.get("Cl", 0) + counts.get("Br", 0) + counts.get("F", 0) + counts.get("I", 0)
    donors = sum(counts.get(item, 0) for item in ["N", "O", "S"]) * 0.45
    acceptors = sum(counts.get(item, 0) for item in ["N", "O", "S", "F", "Cl", "Br"]) * 0.7
    tpsa = 12.0 * counts.get("N", 0) + 17.0 * counts.get("O", 0) + 25.0 * counts.get("P", 0) + 25.0 * counts.get("S", 0)
    logp = clamp(1.1 + carbon * 0.17 + aromatic * 0.08 + rings * 0.22 - hetero * 0.18 - halogen * 0.06, -1.5, 7.5)
    logs = clamp(-0.7 - 0.85 * logp - 0.004 * mw + hetero * 0.06, -8.0, 1.2)
    return {
        "mw": round(mw, 2),
        "atoms": float(atom_count),
        "carbon": float(carbon),
        "hetero": float(hetero),
        "rings": float(rings),
        "aromatic": float(aromatic),
        "halogen": float(halogen),
        "hbd": round(donors, 2),
        "hba": round(acceptors, 2),
        "tpsa": round(tpsa, 2),
        "logp": round(logp, 2),
        "logs": round(logs, 2),
    }


def _risk_from_probability(probability: float, low: float = 0.25, high: float = 0.6) -> str:
    if probability >= high:
        return "red"
    if probability >= low:
        return "yellow"
    return "green"


@dataclass
class Pipeline58Service:
    settings: Pipeline58Settings
    _admet_model: Any = field(default=None, init=False, repr=False)
    _admet_model_ready: bool = field(default=False, init=False, repr=False)
    _admet_model_error: str = field(default="", init=False, repr=False)
    _pbpk_runner_error: str = field(default="", init=False, repr=False)
    _pkpd_runner_error: str = field(default="", init=False, repr=False)
    _task_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _task_executor: concurrent.futures.ThreadPoolExecutor | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        if PG.enabled:
            PG.ensure_schema()
            PG.migrate_from_json_if_needed()
        self._task_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="p58-task")
        self._recover_task_store()

    @staticmethod
    def _project_visible(project: Dict[str, Any], username: str | None, role: str | None) -> bool:
        access_level = str(project.get("access_level", "internal"))
        owner = str(project.get("owner", ""))
        if role == "admin":
            return True
        if access_level != "restricted":
            return True
        return bool(username) and username == owner

    def _iter_run_payloads(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for path in sorted(RUNS_DIR.glob("run_*.json"), reverse=True):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
        return rows

    @staticmethod
    def _task_visible(payload: Dict[str, Any], username: str | None, role: str | None) -> bool:
        if role == "admin":
            return True
        created_by = str(payload.get("created_by", ""))
        return bool(username) and username == created_by

    @staticmethod
    def _flatten_scalar(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        return json.dumps(value, ensure_ascii=False)

    def _task_path(self, task_id: str) -> Path:
        return TASKS_DIR / f"{task_id}.json"

    def _task_csv_path(self, task_id: str) -> Path:
        return TASKS_DIR / f"{task_id}.csv"

    def _task_html_path(self, task_id: str) -> Path:
        return TASKS_DIR / f"{task_id}.html"

    def _iter_task_payloads(self) -> List[Dict[str, Any]]:
        if PG.enabled:
            return PG.list_tasks()
        rows: List[Dict[str, Any]] = []
        for path in sorted(TASKS_DIR.glob("task_*.json"), reverse=True):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
        return rows

    def _read_task_payload(self, task_id: str) -> Dict[str, Any]:
        if PG.enabled:
            payload = PG.get_task(task_id)
            # Disk artifacts remain the source of truth for report/CSV files, but
            # metadata comes from PostgreSQL once enabled.
            return payload
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(task_id)
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _write_task_payload(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = now_iso()
        with self._task_lock:
            if PG.enabled:
                PG.upsert_task(payload)
            self._task_path(str(payload["task_id"])).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _recover_task_store(self) -> None:
        for payload in self._iter_task_payloads():
            if str(payload.get("status", "")) in {"queued", "running"}:
                payload["status"] = "interrupted"
                payload["error"] = "任务在服务重启前中断，需要重新提交。"
                self._write_task_payload(payload)

    def _summarize_batch_prediction(self, row: Dict[str, Any]) -> Dict[str, Any]:
        compound_name = str(row.get("compound_name", ""))
        smiles = str(row.get("smiles", ""))
        raw = row.get("raw", {}) or {}
        try:
            request = Pipeline58Request(compound_name=compound_name or "Unknown", smiles=smiles or "C", target_name="ADMET batch")
            desc = smiles_descriptors(smiles or "C")
            normalized = self._real_admet(request, desc, raw) if isinstance(raw, dict) else self._heuristic_admet(request, desc)
        except Exception:
            request = Pipeline58Request(compound_name=compound_name or "Unknown", smiles=smiles or "C", target_name="ADMET batch")
            normalized = self._heuristic_admet(request, smiles_descriptors(smiles or "C"))
        return {
            "compound_name": compound_name,
            "smiles": smiles,
            "gpu_index": row.get("gpu_index", 0),
            "device": row.get("device", "cpu"),
            "overall_admet_score": normalized.get("overall_admet_score", 0),
            "oral_f": normalized.get("absorption", {}).get("Oral_F", {}).get("value"),
            "hia": normalized.get("absorption", {}).get("HIA", {}).get("value"),
            "caco2": normalized.get("absorption", {}).get("Caco2", {}).get("value"),
            "half_life_h": normalized.get("elimination", {}).get("Half_Life", {}).get("value"),
            "cyp3a4_inhibitor": normalized.get("metabolism", {}).get("CYP3A4_Inhibitor", {}).get("value"),
            "herg_risk": normalized.get("toxicity", {}).get("hERG", {}).get("risk"),
            "dili_risk": normalized.get("toxicity", {}).get("DILI", {}).get("risk"),
            "development_flags": normalized.get("development_flags", []),
            "raw": raw,
        }

    def _write_task_csv(self, task_id: str, items: List[Dict[str, Any]]) -> str:
        path = self._task_csv_path(task_id)
        header = [
            "compound_name",
            "smiles",
            "gpu_index",
            "device",
            "overall_admet_score",
            "oral_f",
            "hia",
            "caco2",
            "half_life_h",
            "cyp3a4_inhibitor",
            "herg_risk",
            "dili_risk",
            "development_flags",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for item in items:
                writer.writerow({
                    **{key: item.get(key, "") for key in header},
                    "development_flags": " | ".join(item.get("development_flags", [])),
                })
        return str(path)

    def _resolve_population(self, request: Pipeline58Request) -> Dict[str, Any]:
        preset = request.population.preset
        preset_map: Dict[str, Dict[str, Any]] = {
            "adult": {"label": "成人 Adult", "age_years": 40, "weight_kg": 70.0, "ethnicity": "general", "cl_factor": 1.0, "v_factor": 1.0},
            "infant": {"label": "婴儿 Infant", "age_years": 1, "weight_kg": 10.0, "ethnicity": "general", "cl_factor": 0.45, "v_factor": 1.25},
            "child": {"label": "儿童 Child", "age_years": 8, "weight_kg": 25.0, "ethnicity": "general", "cl_factor": 0.8, "v_factor": 1.1},
            "adolescent": {"label": "青少年 Adolescent", "age_years": 15, "weight_kg": 55.0, "ethnicity": "general", "cl_factor": 0.95, "v_factor": 1.02},
            "elderly": {"label": "老年 Elderly", "age_years": 72, "weight_kg": 65.0, "ethnicity": "general", "cl_factor": 0.72, "v_factor": 0.95},
            "east_asian_adult": {"label": "东亚成人 East Asian Adult", "age_years": 40, "weight_kg": 63.0, "ethnicity": "east_asian", "cl_factor": 0.92, "v_factor": 0.95},
            "european_adult": {"label": "欧洲成人 European Adult", "age_years": 40, "weight_kg": 78.0, "ethnicity": "european", "cl_factor": 1.02, "v_factor": 1.04},
            "pregnant_adult": {"label": "妊娠成人 Pregnant Adult", "age_years": 30, "weight_kg": 68.0, "ethnicity": "general", "cl_factor": 0.9, "v_factor": 1.15},
            "renal_ckd": {"label": "慢性肾病 Chronic Kidney Disease", "age_years": 60, "weight_kg": 68.0, "ethnicity": "general", "cl_factor": 0.62, "v_factor": 1.05},
            "hepatic_cirrhosis": {"label": "肝硬化 Hepatic Cirrhosis", "age_years": 58, "weight_kg": 65.0, "ethnicity": "general", "cl_factor": 0.58, "v_factor": 1.08},
        }
        meta = dict(preset_map.get(preset, preset_map["adult"]))
        weight = request.population.weight_kg
        age = request.population.age_years
        if preset in set(preset_map):
            if weight == 70.0 and preset != "adult":
                weight = meta["weight_kg"]
            if age == 40 and preset != "adult":
                age = meta["age_years"]
        sex_factor = 0.94 if request.population.sex == "female" else 1.0
        ethnicity_factor = {
            "general": 1.0,
            "east_asian": 0.93,
            "european": 1.0,
            "african_ancestry": 1.04,
            "latino": 0.98,
        }.get(request.population.ethnicity or meta["ethnicity"], 1.0)
        renal_stage = request.population.renal_stage
        hepatic_stage = request.population.hepatic_stage
        trimester = request.population.pregnancy_trimester
        if preset == "renal_ckd" and renal_stage == "normal":
            renal_stage = "moderate"
        if preset == "hepatic_cirrhosis" and hepatic_stage == "normal":
            hepatic_stage = "child_pugh_b"
        if preset == "pregnant_adult" and trimester == "none":
            trimester = "t2"
        renal_factor = {"normal": 1.0, "mild": 0.88, "moderate": 0.7, "severe": 0.5}.get(renal_stage, 1.0)
        hepatic_factor = {"normal": 1.0, "child_pugh_a": 0.82, "child_pugh_b": 0.63, "child_pugh_c": 0.45}.get(hepatic_stage, 1.0)
        trimester_cl_factor = {"none": 1.0, "t1": 0.95, "t2": 0.88, "t3": 0.8}.get(trimester, 1.0)
        trimester_v_factor = {"none": 1.0, "t1": 1.06, "t2": 1.14, "t3": 1.22}.get(trimester, 1.0)
        pregnancy_enabled = request.population.pregnant or preset == "pregnant_adult" or trimester != "none"
        pregnancy_cl_factor = trimester_cl_factor if pregnancy_enabled else 1.0
        pregnancy_v_factor = trimester_v_factor if pregnancy_enabled else 1.0
        sex_label_map = {"unknown": "未知", "male": "男", "female": "女"}
        ethnicity_label_map = {
            "general": "通用",
            "east_asian": "东亚",
            "european": "欧洲",
            "african_ancestry": "非洲祖源",
            "latino": "拉美",
        }
        renal_label_map = {"normal": "正常", "mild": "轻度", "moderate": "中度", "severe": "重度"}
        hepatic_label_map = {"normal": "正常", "child_pugh_a": "Child-Pugh A", "child_pugh_b": "Child-Pugh B", "child_pugh_c": "Child-Pugh C"}
        trimester_label_map = {"none": "无", "t1": "孕早期", "t2": "孕中期", "t3": "孕晚期"}
        return {
            "label": meta["label"],
            "preset": preset,
            "species": request.population.species,
            "sex": request.population.sex,
            "sex_label": sex_label_map.get(request.population.sex, request.population.sex),
            "ethnicity": request.population.ethnicity if request.population.ethnicity != "general" else meta["ethnicity"],
            "ethnicity_label": ethnicity_label_map.get(request.population.ethnicity if request.population.ethnicity != "general" else meta["ethnicity"], "通用"),
            "weight_kg": round(weight, 2),
            "age_years": int(age),
            "renal_impairment": request.population.renal_impairment or renal_stage != "normal" or preset == "renal_ckd",
            "hepatic_impairment": request.population.hepatic_impairment or hepatic_stage != "normal" or preset == "hepatic_cirrhosis",
            "pregnant": pregnancy_enabled,
            "renal_stage": renal_stage,
            "renal_stage_label": renal_label_map.get(renal_stage, renal_stage),
            "hepatic_stage": hepatic_stage,
            "hepatic_stage_label": hepatic_label_map.get(hepatic_stage, hepatic_stage),
            "pregnancy_trimester": trimester,
            "pregnancy_trimester_label": trimester_label_map.get(trimester, trimester),
            "cl_factor": round(meta["cl_factor"] * sex_factor * ethnicity_factor * pregnancy_cl_factor * renal_factor * hepatic_factor, 3),
            "v_factor": round(meta["v_factor"] * (0.98 if request.population.sex == "female" else 1.0) * pregnancy_v_factor, 3),
        }

    def _fetch_json(self, url: str, timeout: int = 12) -> Optional[Dict[str, Any]]:
        try:
            request = Request(url, headers={"User-Agent": "pipeline58-local/0.1"})
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def _fetch_pubmed_snapshot(self, query: str, max_results: int = 3) -> List[Dict[str, str]]:
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode({
            "db": "pubmed",
            "retmode": "json",
            "retmax": max_results,
            "term": query,
        })
        search_json = self._fetch_json(search_url)
        if not search_json:
            return []
        id_list = search_json.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urlencode({
            "db": "pubmed",
            "retmode": "json",
            "id": ",".join(id_list),
        })
        summary_json = self._fetch_json(summary_url)
        if not summary_json:
            return []
        result = summary_json.get("result", {})
        out: List[Dict[str, str]] = []
        for uid in result.get("uids", []):
            item = result.get(uid, {})
            if not item:
                continue
            out.append({
                "title": str(item.get("title", "")).strip(),
                "pubdate": str(item.get("pubdate", "")).strip(),
                "source": str(item.get("source", "")).strip(),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            })
        return out

    def _load_real_admet_model(self) -> Optional[Any]:
        if not self.settings.prefer_real_admet_model:
            return None
        if self._admet_model_ready:
            return self._admet_model
        self._admet_model_ready = True
        try:
            from admet_ai import ADMETModel

            self._admet_model = ADMETModel()
            self._admet_model_error = ""
        except Exception as exc:
            self._admet_model = None
            self._admet_model_error = str(exc)
        return self._admet_model

    def runtime_status(self) -> Dict[str, Any]:
        gpu_rows: List[Dict[str, Any]] = []
        try:
            output = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,driver_version,memory.total,memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=10,
            )
            for line in output.splitlines():
                parts = [item.strip() for item in line.split(",")]
                if len(parts) < 6:
                    continue
                gpu_rows.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "driver_version": parts[2],
                    "memory_total_mib": int(float(parts[3])),
                    "memory_used_mib": int(float(parts[4])),
                    "utilization_pct": int(float(parts[5])),
                    "status": "ready",
                })
        except Exception as exc:
            gpu_rows.append({
                "index": -1,
                "name": "GPU unavailable",
                "driver_version": "",
                "memory_total_mib": 0,
                "memory_used_mib": 0,
                "utilization_pct": 0,
                "status": str(exc),
            })
        admet_model = self._load_real_admet_model()
        admet_backend = "admet_ai" if admet_model is not None else "heuristic"
        return {
            "admet": {
                "backend": admet_backend,
                "device": getattr(admet_model, "device", "cpu") if admet_model is not None else "cpu",
                "num_workers": getattr(admet_model, "num_workers", 0) if admet_model is not None else 0,
                "batch_parallel_gpus": [row["index"] for row in gpu_rows if row.get("index", -1) >= 0],
            },
            "pbpk": {
                "backend": "mrgsolve" if self.settings.prefer_real_pbpk_model else "heuristic",
                "open_source_backend": "PK-Sim",
            },
            "pkpd": {
                "backend": "rxode2" if self.settings.prefer_real_pkpd_model else "heuristic",
            },
            "pksim": {
                "backend": "ospsuite",
                "runner": str(self._pksim_runner_path()),
                "runner_exists": self._pksim_runner_path().exists(),
            },
            "gpus": gpu_rows,
        }

    @staticmethod
    def _batch_worker(
        gpu_index: int,
        items: List[Dict[str, str]],
        python_executable: str,
    ) -> List[Dict[str, Any]]:
        if not items:
            return []
        script = """
import json
import sys
import io
import contextlib
from admet_ai import ADMETModel

payload = json.loads(sys.stdin.read())
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    model = ADMETModel()
rows = []
for item in payload["items"]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        raw = model.predict(smiles=item["smiles"])
    if hasattr(raw, "to_dict"):
        try:
            raw = raw.to_dict()
        except Exception:
            pass
    if isinstance(raw, list) and raw:
        raw = raw[0]
    rows.append({
        "compound_name": item["compound_name"],
        "smiles": item["smiles"],
        "gpu_index": payload["gpu_index"],
        "device": getattr(model, "device", "cpu"),
        "raw": raw,
    })
print(json.dumps(rows, ensure_ascii=False))
""".strip()
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
        proc = subprocess.run(
            [python_executable, "-c", script],
            input=json.dumps({"gpu_index": gpu_index, "items": items}, ensure_ascii=False),
            text=True,
            capture_output=True,
            env=env,
            timeout=600,
            check=True,
        )
        return json.loads(proc.stdout.strip())

    def batch_admet_screen(self, request: ADMETBatchRequest, progress_hook: Any = None) -> Dict[str, Any]:
        runtime = self.runtime_status()
        available_gpus = runtime.get("admet", {}).get("batch_parallel_gpus", [])
        if not available_gpus:
            available_gpus = [0]
        python_executable = sys.executable
        chunks: List[List[Dict[str, str]]] = [[] for _ in available_gpus]
        normalized_items = [{"compound_name": item.compound_name, "smiles": item.smiles} for item in request.items]
        for index, item in enumerate(normalized_items):
            chunks[index % len(available_gpus)].append(item)
        predictions: List[Dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(available_gpus)) as executor:
            futures = {
                executor.submit(self._batch_worker, gpu_index, chunk, python_executable): (gpu_index, chunk)
                for gpu_index, chunk in zip(available_gpus, chunks)
                if chunk
            }
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                gpu_index, chunk = futures[future]
                rows = future.result()
                predictions.extend(rows)
                completed += len(rows)
                if progress_hook is not None:
                    progress_hook(completed, len(normalized_items), gpu_index, len(chunk))
        order_map = {(item["compound_name"], item["smiles"]): idx for idx, item in enumerate(normalized_items)}
        predictions.sort(key=lambda row: order_map.get((row["compound_name"], row["smiles"]), 10**9))
        return {
            "submitted": len(normalized_items),
            "gpu_workers": available_gpus,
            "backend": runtime.get("admet", {}),
            "items": predictions,
        }

    def submit_admet_batch_task(self, request: ADMETBatchTaskRequest, username: str) -> Dict[str, Any]:
        runtime = self.runtime_status()
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        payload = {
            "task_id": task_id,
            "task_type": "admet_batch",
            "status": "queued",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": username,
            "project_name": request.project_name,
            "project_code": request.project_code,
            "notes": request.notes,
            "submitted": len(request.items),
            "completed": 0,
            "progress_pct": 0,
            "gpu_workers": runtime.get("admet", {}).get("batch_parallel_gpus", []),
            "backend": runtime.get("admet", {}),
            "input_preview": [item.model_dump() for item in request.items[:12]],
            "items": [],
            "error": "",
            "csv_path": "",
            "html_report_path": "",
        }
        self._write_task_payload(payload)
        if self._task_executor is None:
            raise RuntimeError("task executor is unavailable")
        self._task_executor.submit(self._run_admet_batch_task, task_id, request.model_dump())
        return payload

    def _run_admet_batch_task(self, task_id: str, request_payload: Dict[str, Any]) -> None:
        payload = self._read_task_payload(task_id)
        payload["status"] = "running"
        payload["error"] = ""
        self._write_task_payload(payload)

        def progress_hook(completed: int, total: int, gpu_index: int, chunk_size: int) -> None:
            task = self._read_task_payload(task_id)
            task["status"] = "running"
            task["completed"] = completed
            task["submitted"] = total
            task["progress_pct"] = round((completed / max(total, 1)) * 100, 1)
            task["last_gpu_index"] = gpu_index
            task["last_chunk_size"] = chunk_size
            self._write_task_payload(task)

        try:
            batch_request = ADMETBatchRequest(items=[ADMETBatchItem(**item) for item in request_payload.get("items", [])])
            result = self.batch_admet_screen(batch_request, progress_hook=progress_hook)
            items = [self._summarize_batch_prediction(item) for item in result.get("items", [])]
            items.sort(key=lambda row: (-float(row.get("overall_admet_score") or 0), str(row.get("compound_name", ""))))
            csv_path = self._write_task_csv(task_id, items)
            html_path = self._write_batch_report_html(task_id, payload, items, result)
            payload = self._read_task_payload(task_id)
            payload.update({
                "status": "completed",
                "completed": len(items),
                "submitted": len(items),
                "progress_pct": 100,
                "items": items,
                "csv_path": csv_path,
                "html_report_path": html_path,
                "backend": result.get("backend", payload.get("backend", {})),
                "gpu_workers": result.get("gpu_workers", payload.get("gpu_workers", [])),
                "error": "",
            })
            self._write_task_payload(payload)
        except Exception as exc:
            payload = self._read_task_payload(task_id)
            payload["status"] = "failed"
            payload["error"] = str(exc)
            self._write_task_payload(payload)

    def list_tasks(self, username: str | None = None, role: str | None = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for payload in self._iter_task_payloads():
            if not self._task_visible(payload, username, role):
                continue
            rows.append({
                "task_id": payload.get("task_id"),
                "task_type": payload.get("task_type"),
                "status": payload.get("status"),
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
                "created_by": payload.get("created_by"),
                "project_name": payload.get("project_name"),
                "project_code": payload.get("project_code"),
                "submitted": payload.get("submitted", 0),
                "completed": payload.get("completed", 0),
                "progress_pct": payload.get("progress_pct", 0),
                "gpu_workers": payload.get("gpu_workers", []),
                "error": payload.get("error", ""),
                "top_hits": [item.get("compound_name") for item in (payload.get("items") or [])[:3]],
            })
        return rows

    def get_task(self, task_id: str, username: str | None = None, role: str | None = None) -> Dict[str, Any]:
        payload = self._read_task_payload(task_id)
        if not self._task_visible(payload, username, role):
            raise PermissionError(task_id)
        return payload

    def _predict_real_admet(self, smiles: str) -> Optional[Dict[str, Any]]:
        model = self._load_real_admet_model()
        if model is None:
            return None
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                raw = model.predict(smiles=smiles)
        except Exception as exc:
            self._admet_model_error = str(exc)
            return None
        if hasattr(raw, "to_dict"):
            try:
                raw = raw.to_dict()
            except Exception:
                pass
        if isinstance(raw, list) and raw:
            item = raw[0]
        elif isinstance(raw, dict):
            item = raw
        else:
            return None
        return item if isinstance(item, dict) else None

    def _heuristic_admet(self, request: Pipeline58Request, desc: Dict[str, float], backend_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        caco2 = round(-6.3 + desc["logp"] * 0.36 + desc["hetero"] * 0.08 - desc["tpsa"] * 0.01, 2)
        bioavailability = round(clamp(0.92 - 0.06 * max(desc["logp"] - 3.5, 0) - 0.002 * desc["tpsa"], 0.05, 0.95), 2)
        bbb = round(clamp(logistic(desc["logp"] - desc["tpsa"] / 60.0 - 0.4), 0.01, 0.99), 2)
        ppb = round(clamp(0.45 + desc["logp"] * 0.09 + desc["mw"] * 0.00045, 0.2, 0.99), 2)
        vdss = round(clamp(0.35 + desc["logp"] * 0.28 + desc["rings"] * 0.08 - desc["tpsa"] * 0.0018, 0.15, 8.0), 2)
        cyp3a4_sub = round(clamp(logistic(desc["logp"] * 0.9 + desc["aromatic"] * 0.18 - 2.8), 0.01, 0.99), 2)
        cyp3a4_inh = round(clamp(logistic(desc["halogen"] * 0.55 + desc["aromatic"] * 0.22 + desc["logp"] * 0.7 - 3.3), 0.01, 0.99), 2)
        renal_cl = round(clamp(8.5 - desc["logp"] * 1.2 - ppb * 2.0 + desc["tpsa"] * 0.015, 0.1, 12.0), 2)
        total_cl = round(clamp(renal_cl + (1.0 - cyp3a4_sub) * 3.2 + (1.0 - ppb) * 1.4, 0.3, 15.0), 2)
        half_life = round(clamp(0.693 * vdss / max(total_cl / 10.0, 0.08), 1.2, 48.0), 2)
        herg = round(clamp(logistic(desc["logp"] * 0.95 + desc["aromatic"] * 0.2 + desc["halogen"] * 0.45 - 4.1), 0.01, 0.99), 2)
        dili = round(clamp(logistic(desc["logp"] * 0.55 + desc["mw"] / 220.0 + desc["aromatic"] * 0.12 - 2.6), 0.01, 0.99), 2)
        ames = round(clamp(logistic(desc["aromatic"] * 0.1 + desc["halogen"] * 0.28 - 1.4), 0.01, 0.99), 2)
        hia = round(clamp(bioavailability + 0.04, 0.05, 0.99), 2)
        flags: List[str] = []
        if herg >= 0.6:
            flags.append("hERG risk is high and should gate oral development.")
        if dili >= 0.6:
            flags.append("Predicted DILI risk is elevated and warrants structure review.")
        if bioavailability < 0.2 and request.dosing.route == "po":
            flags.append("Oral exposure is likely poor for the requested oral regimen.")
        if cyp3a4_inh >= 0.6:
            flags.append("CYP3A4 inhibition is elevated and should feed the DDI module.")
        score = 100
        score -= 30 if herg >= 0.6 else 15 if herg >= 0.25 else 0
        score -= 25 if dili >= 0.6 else 10 if dili >= 0.25 else 0
        score -= 15 if bioavailability < 0.2 else 8 if bioavailability < 0.35 else 0
        score -= 10 if ppb > 0.95 else 4 if ppb > 0.9 else 0
        score -= 10 if cyp3a4_inh >= 0.6 else 4 if cyp3a4_inh >= 0.25 else 0
        score = int(clamp(score, 5, 98))
        return {
            "model_backend": backend_meta or {"backend": "heuristic", "error": self._admet_model_error},
            "descriptors": desc,
            "absorption": {
                "Caco2_Papp": {"value": caco2, "unit": "log cm/s", "risk": "green" if caco2 > -5.15 else "yellow"},
                "Oral_F": {"value": bioavailability, "unit": "fraction", "risk": "green" if bioavailability >= 0.3 else "yellow" if bioavailability >= 0.15 else "red"},
                "HIA": {"value": hia, "unit": "probability", "risk": "green" if hia >= 0.7 else "yellow"},
                "BBB": {"value": bbb, "unit": "probability", "risk": "green" if bbb >= 0.45 else "yellow"},
            },
            "distribution": {
                "PPB": {"value": ppb, "unit": "fraction", "risk": "green" if ppb < 0.9 else "yellow" if ppb < 0.96 else "red"},
                "VDss": {"value": vdss, "unit": "L/kg", "risk": "green"},
            },
            "metabolism": {
                "CYP3A4_substrate": {"value": cyp3a4_sub, "unit": "probability", "risk": _risk_from_probability(cyp3a4_sub)},
                "CYP3A4_inhibitor": {"value": cyp3a4_inh, "unit": "probability", "risk": _risk_from_probability(cyp3a4_inh)},
                "Half_life": {"value": half_life, "unit": "h", "risk": "green"},
            },
            "excretion": {
                "CLrenal": {"value": renal_cl, "unit": "mL/min/kg", "risk": "green"},
                "CLtotal": {"value": total_cl, "unit": "mL/min/kg", "risk": "green"},
            },
            "toxicity": {
                "hERG": {"value": herg, "unit": "probability", "risk": _risk_from_probability(herg)},
                "DILI": {"value": dili, "unit": "probability", "risk": _risk_from_probability(dili)},
                "AMES": {"value": ames, "unit": "probability", "risk": _risk_from_probability(ames)},
            },
            "overall_admet_score": score,
            "risk_flags": flags,
        }

    def _real_admet(self, request: Pipeline58Request, desc: Dict[str, float], raw: Dict[str, Any]) -> Dict[str, Any]:
        merged_desc = dict(desc)
        merged_desc["mw"] = round(float(raw.get("molecular_weight", merged_desc["mw"])), 2)
        merged_desc["logp"] = round(float(raw.get("logP", merged_desc["logp"])), 2)
        merged_desc["logs"] = round(float(raw.get("Solubility_AqSolDB", merged_desc["logs"])), 2)
        merged_desc["hba"] = round(float(raw.get("hydrogen_bond_acceptors", merged_desc["hba"])), 2)
        merged_desc["hbd"] = round(float(raw.get("hydrogen_bond_donors", merged_desc["hbd"])), 2)
        merged_desc["tpsa"] = round(float(raw.get("tpsa", merged_desc["tpsa"])), 2)

        caco2 = round(float(raw.get("Caco2_Wang", -5.5)), 2)
        bioavailability = round(clamp(float(raw.get("Bioavailability_Ma", 0.5)), 0.01, 0.99), 2)
        hia = round(clamp(float(raw.get("HIA_Hou", bioavailability)), 0.01, 0.99), 2)
        bbb = round(clamp(float(raw.get("BBB_Martins", 0.5)), 0.01, 0.99), 2)
        pgp = round(clamp(float(raw.get("Pgp_Broccatelli", 0.3)), 0.01, 0.99), 2)
        ppb_percent = float(raw.get("PPBR_AZ", 70.0))
        ppb = round(clamp(ppb_percent / 100.0 if ppb_percent > 1.0 else ppb_percent, 0.05, 0.99), 2)
        vdss = round(clamp(float(raw.get("VDss_Lombardo", 1.0)), 0.1, 8.0), 2)
        cyp3a4_sub = round(clamp(float(raw.get("CYP3A4_Substrate_CarbonMangels", 0.5)), 0.01, 0.99), 2)
        cyp3a4_inh = round(clamp(float(raw.get("CYP3A4_Veith", 0.5)), 0.01, 0.99), 2)
        raw_half_life = float(raw.get("Half_Life_Obach", 8.0))
        half_life = round(clamp((10 ** raw_half_life) if raw_half_life < 3 else raw_half_life, 0.5, 72.0), 2)
        solubility = round(float(raw.get("Solubility_AqSolDB", merged_desc["logs"])), 2)
        hepatic_clearance = float(raw.get("Clearance_Hepatocyte_AZ", 20.0))
        renal_cl = round(clamp(8.0 - merged_desc["logp"] * 0.9 - ppb * 2.0 + merged_desc["tpsa"] * 0.02, 0.1, 12.0), 2)
        total_cl = round(clamp(renal_cl + hepatic_clearance / 10.0, 0.2, 18.0), 2)
        herg = round(clamp(float(raw.get("hERG", 0.3)), 0.01, 0.99), 2)
        dili = round(clamp(float(raw.get("DILI", 0.3)), 0.01, 0.99), 2)
        ames = round(clamp(float(raw.get("AMES", 0.3)), 0.01, 0.99), 2)

        flags: List[str] = []
        if herg >= 0.6:
            flags.append("ADMET-AI predicts elevated hERG liability.")
        if dili >= 0.6:
            flags.append("ADMET-AI predicts elevated DILI risk.")
        if bioavailability < 0.2 and request.dosing.route == "po":
            flags.append("Predicted oral bioavailability is poor for the requested oral regimen.")
        if cyp3a4_inh >= 0.25:
            flags.append("Predicted CYP3A4 inhibition should propagate into DDI review.")

        score = 100
        score -= 30 if herg >= 0.6 else 15 if herg >= 0.25 else 0
        score -= 25 if dili >= 0.6 else 10 if dili >= 0.25 else 0
        score -= 15 if bioavailability < 0.2 else 8 if bioavailability < 0.35 else 0
        score -= 10 if ppb > 0.95 else 4 if ppb > 0.9 else 0
        score -= 10 if cyp3a4_inh >= 0.6 else 4 if cyp3a4_inh >= 0.25 else 0
        score = int(clamp(score, 5, 98))

        return {
            "model_backend": {
                "backend": "admet_ai",
                "device": getattr(self._admet_model, "device", "cpu"),
                "num_workers": getattr(self._admet_model, "num_workers", 0),
                "error": self._admet_model_error,
                "source_metrics": [
                    "Caco2_Wang",
                    "Bioavailability_Ma",
                    "HIA_Hou",
                    "BBB_Martins",
                    "Pgp_Broccatelli",
                    "PPBR_AZ",
                    "VDss_Lombardo",
                    "CYP3A4_Substrate_CarbonMangels",
                    "CYP3A4_Veith",
                    "hERG",
                    "DILI",
                    "AMES",
                ],
            },
            "descriptors": merged_desc,
            "absorption": {
                "Caco2_Papp": {"value": caco2, "unit": "log cm/s", "risk": "green" if caco2 > -5.15 else "yellow"},
                "Oral_F": {"value": bioavailability, "unit": "fraction", "risk": "green" if bioavailability >= 0.3 else "yellow" if bioavailability >= 0.15 else "red"},
                "HIA": {"value": hia, "unit": "probability", "risk": "green" if hia >= 0.7 else "yellow"},
                "BBB": {"value": bbb, "unit": "probability", "risk": "green" if bbb >= 0.45 else "yellow"},
                "Pgp": {"value": pgp, "unit": "probability", "risk": _risk_from_probability(pgp)},
                "Solubility": {"value": solubility, "unit": "log mol/L", "risk": "green" if solubility > -4 else "yellow"},
            },
            "distribution": {
                "PPB": {"value": ppb, "unit": "fraction", "risk": "green" if ppb < 0.9 else "yellow" if ppb < 0.96 else "red"},
                "VDss": {"value": vdss, "unit": "L/kg", "risk": "green"},
            },
            "metabolism": {
                "CYP3A4_substrate": {"value": cyp3a4_sub, "unit": "probability", "risk": _risk_from_probability(cyp3a4_sub)},
                "CYP3A4_inhibitor": {"value": cyp3a4_inh, "unit": "probability", "risk": _risk_from_probability(cyp3a4_inh)},
                "Half_life": {"value": half_life, "unit": "h", "risk": "green"},
            },
            "excretion": {
                "CLrenal": {"value": renal_cl, "unit": "mL/min/kg", "risk": "green"},
                "CLtotal": {"value": total_cl, "unit": "mL/min/kg", "risk": "green"},
            },
            "toxicity": {
                "hERG": {"value": herg, "unit": "probability", "risk": _risk_from_probability(herg)},
                "DILI": {"value": dili, "unit": "probability", "risk": _risk_from_probability(dili)},
                "AMES": {"value": ames, "unit": "probability", "risk": _risk_from_probability(ames)},
            },
            "overall_admet_score": score,
            "risk_flags": flags,
            "raw_model_output": {
                "molecular_weight": raw.get("molecular_weight"),
                "logP": raw.get("logP"),
                "QED": raw.get("QED"),
                "Lipinski": raw.get("Lipinski"),
                "Caco2_Wang": raw.get("Caco2_Wang"),
                "Bioavailability_Ma": raw.get("Bioavailability_Ma"),
                "HIA_Hou": raw.get("HIA_Hou"),
                "BBB_Martins": raw.get("BBB_Martins"),
                "PPBR_AZ": raw.get("PPBR_AZ"),
                "VDss_Lombardo": raw.get("VDss_Lombardo"),
                "Clearance_Hepatocyte_AZ": raw.get("Clearance_Hepatocyte_AZ"),
                "Half_Life_Obach": raw.get("Half_Life_Obach"),
                "hERG": raw.get("hERG"),
                "DILI": raw.get("DILI"),
                "AMES": raw.get("AMES"),
            },
        }

    def _admet(self, request: Pipeline58Request, desc: Dict[str, float]) -> Dict[str, Any]:
        raw = self._predict_real_admet(request.smiles)
        if raw:
            return self._real_admet(request, desc, raw)
        return self._heuristic_admet(request, desc, backend_meta={"backend": "heuristic", "error": self._admet_model_error})

    def _pbpk_runner_path(self) -> Path:
        return Path(__file__).resolve().parent / "runners" / "pbpk_mrgsolve.R"

    def _compound_pbpk_parameters(self, request: Pipeline58Request, admet: Dict[str, Any], population: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        overrides = overrides or {}
        desc = admet.get("descriptors", {}) or {}
        absorption = admet.get("absorption", {}) or {}
        distribution = admet.get("distribution", {}) or {}
        metabolism = admet.get("metabolism", {}) or {}
        excretion = admet.get("excretion", {}) or {}
        raw = admet.get("raw_model_output", {}) or {}

        weight = float(population.get("weight_kg", 70.0) or 70.0)
        mw = float(desc.get("mw", raw.get("molecular_weight", 400.0)) or 400.0)
        logp = float(desc.get("logp", raw.get("logP", 2.0)) or 2.0)
        tpsa = float(desc.get("tpsa", 70.0) or 70.0)
        logs = float(desc.get("logs", absorption.get("Solubility", {}).get("value", -3.0)) or -3.0)
        solubility_mg_ml = None
        try:
            if overrides.get("solubility_mg_ml") not in (None, ""):
                solubility_mg_ml = max(float(overrides.get("solubility_mg_ml")), 1e-9)
                # mg/mL equals g/L; mol/L = (g/L) / molecular weight.
                logs = math.log10(max(solubility_mg_ml / max(mw, 1e-6), 1e-12))
        except Exception:
            solubility_mg_ml = None
        caco2 = float(absorption.get("Caco2_Papp", {}).get("value", -5.5) or -5.5)
        oral_f = float(absorption.get("Oral_F", {}).get("value", 0.55) or 0.55) if request.dosing.route == "po" else 1.0
        ppb = float(distribution.get("PPB", {}).get("value", 0.75) or 0.75)
        fu = clamp(1.0 - ppb, 0.01, 0.95)
        vdss_l_per_kg = float(distribution.get("VDss", {}).get("value", 1.0) or 1.0)
        vdss_l_per_kg = vdss_l_per_kg * float(population.get("v_factor", 1.0) or 1.0) * float(overrides.get("v_multiplier", 1.0))
        total_cl_ml_min_kg = float(excretion.get("CLtotal", {}).get("value", 5.0) or 5.0)
        total_cl_ml_min_kg = total_cl_ml_min_kg * float(population.get("cl_factor", 1.0) or 1.0) * float(overrides.get("cl_multiplier", 1.0))
        renal_cl_ml_min_kg = float(excretion.get("CLrenal", {}).get("value", max(total_cl_ml_min_kg * 0.45, 0.1)) or 0.1)
        renal_cl_ml_min_kg = min(renal_cl_ml_min_kg * float(population.get("cl_factor", 1.0) or 1.0), total_cl_ml_min_kg * 0.9)
        cl_total_l_h = max(total_cl_ml_min_kg * weight * 0.06, 0.05)
        cl_renal_l_h = max(renal_cl_ml_min_kg * weight * 0.06, 0.0)
        cl_hepatic_l_h = max(cl_total_l_h - cl_renal_l_h, cl_total_l_h * 0.1)
        cyp3a4_sub = float(metabolism.get("CYP3A4_substrate", {}).get("value", 0.35) or 0.35)
        cyp3a4_inh = float(metabolism.get("CYP3A4_inhibitor", {}).get("value", 0.2) or 0.2)
        permeability_score = clamp((caco2 + 7.0) / 2.5, 0.05, 1.5)
        solubility_factor = clamp(10 ** clamp(logs + 4.0, -2.0, 2.0), 0.05, 4.0)
        ka = (0.15 + 1.25 * permeability_score * clamp(solubility_factor, 0.2, 1.8)) if request.dosing.route == "po" else 3.0
        ka = max(ka * float(overrides.get("ka_multiplier", 1.0)), 0.03)
        vd_total_l = max(vdss_l_per_kg * weight, 6.0)

        volumes = {
            "arterial_blood_l": max(0.018 * weight, 0.8),
            "venous_blood_l": max(0.052 * weight, 2.0),
            "lung_l": max(0.0076 * weight, 0.35),
            "stomach_lumen_l": max(0.0035 * weight, 0.18),
            "duodenum_lumen_l": max(0.0012 * weight, 0.06),
            "jejunum_lumen_l": max(0.0045 * weight, 0.20),
            "ileum_lumen_l": max(0.0045 * weight, 0.20),
            "colon_lumen_l": max(0.0060 * weight, 0.30),
            "gut_l": max(0.017 * weight, 0.8),
            "liver_l": max(0.026 * weight, 1.0),
            "kidney_l": max(0.0044 * weight, 0.25),
            "rich_l": max(0.070 * weight, 2.0),
            "muscle_l": max(0.400 * weight, 8.0),
            "fat_l": max(0.210 * weight, 3.0),
        }
        cardiac_output = max(300.0 * (weight / 70.0) ** 0.75, 90.0)
        flow_fracs = {
            "gut_flow_l_h": 0.16,
            "hepatic_artery_flow_l_h": 0.065,
            "kidney_flow_l_h": 0.19,
            "rich_flow_l_h": 0.18,
            "muscle_flow_l_h": 0.20,
            "fat_flow_l_h": 0.055,
        }
        flows = {name: round(cardiac_output * frac, 4) for name, frac in flow_fracs.items()}
        assigned_flow = sum(flows.values())
        flows["rest_flow_l_h"] = round(max(cardiac_output - assigned_flow, cardiac_output * 0.05), 4)
        flows["cardiac_output_l_h"] = round(assigned_flow + flows["rest_flow_l_h"], 4)

        blood_plasma_ratio = clamp(0.72 + logp * 0.04 + (1.0 - fu) * 0.12, 0.55, 1.35)
        base_lipophilicity = clamp(0.6 + 0.22 * logp + 0.35 * (1.0 - fu) - 0.002 * tpsa, 0.15, 6.0)
        kp = {
            "gut": clamp(base_lipophilicity * 0.9 + permeability_score * 0.25, 0.15, 12.0),
            "liver": clamp(base_lipophilicity * 1.25 + cyp3a4_sub * 0.65, 0.2, 18.0),
            "kidney": clamp(base_lipophilicity * 0.75 + fu * 0.45, 0.15, 10.0),
            "lung": clamp(base_lipophilicity * 0.85 + logp * 0.08, 0.15, 10.0),
            "rich": clamp(base_lipophilicity * 1.05, 0.15, 14.0),
            "muscle": clamp(base_lipophilicity * 0.55, 0.1, 8.0),
            "fat": clamp(1.0 + max(logp, 0.0) * 1.8 + (1.0 - fu) * 2.5, 0.25, 80.0),
            "rest": clamp(base_lipophilicity * 0.7, 0.1, 8.0),
        }
        blood_volume = volumes["arterial_blood_l"] + volumes["venous_blood_l"]
        tissue_vss = (
            volumes["gut_l"] * kp["gut"] + volumes["liver_l"] * kp["liver"] + volumes["kidney_l"] * kp["kidney"] +
            volumes["lung_l"] * kp["lung"] + volumes["rich_l"] * kp["rich"] + volumes["muscle_l"] * kp["muscle"] +
            volumes["fat_l"] * kp["fat"]
        )
        target_tissue_vss = max(vd_total_l - blood_volume, tissue_vss * 0.2)
        scale = clamp(target_tissue_vss / max(tissue_vss, 1e-6), 0.2, 8.0)
        kp = {key: round(value * scale, 4) for key, value in kp.items()}
        effective_oral_f = clamp(oral_f * (0.75 + 0.25 * permeability_score), 0.01, 1.0)
        k_ge = clamp(0.75 + 0.35 * solubility_factor, 0.35, 2.2)
        k_si = clamp(0.42 + 0.25 * permeability_score, 0.18, 1.25)
        k_colon = clamp(0.055 + 0.03 * permeability_score, 0.02, 0.18)
        release_type = str(overrides.get("release_type") or "immediate_release").strip() or "immediate_release"
        food_state = str(overrides.get("food_state") or "fasted").strip() or "fasted"
        formulation_notes_input = str(overrides.get("formulation_notes") or "").strip()
        api_data_source = str(overrides.get("api_data_source") or "").strip()
        formulation_data_source = str(overrides.get("formulation_data_source") or "").strip()
        dissolution_data_source = str(overrides.get("dissolution_data_source") or "").strip()
        pka_acid = overrides.get("pka_acid")
        pka_base = overrides.get("pka_base")
        def override_float_value(key: str):
            try:
                if overrides.get(key) not in (None, ""):
                    return float(overrides.get(key))
            except Exception:
                return None
            return None
        particle_size_um = override_float_value("particle_size_um")
        dissolution_t50_min = override_float_value("dissolution_t50_min")
        dissolution_30min_pct = override_float_value("dissolution_30min_pct")
        gi_transit = {
            "dissolution_h": round(clamp(0.35 + 0.18 / max(solubility_factor, 0.1), 0.12, 2.5), 4),
            "gastric_emptying_h": round(k_ge, 4),
            "duodenum_to_jejunum_h": round(k_si * 1.15, 4),
            "jejunum_to_ileum_h": round(k_si * 0.85, 4),
            "ileum_to_colon_h": round(k_si * 0.55, 4),
            "colon_transit_h": round(k_colon, 4),
            "abs_duodenum_h": round(clamp(ka * 0.55, 0.02, 3.0), 4),
            "abs_jejunum_h": round(clamp(ka * 0.95, 0.03, 4.0), 4),
            "abs_ileum_h": round(clamp(ka * 0.65, 0.02, 3.0), 4),
            "abs_colon_h": round(clamp(ka * 0.08, 0.001, 0.45), 4),
        }
        formulation_notes: List[str] = []
        derived_dissolution_h = None
        try:
            if dissolution_t50_min and dissolution_t50_min > 0:
                derived_dissolution_h = math.log(2.0) / max(dissolution_t50_min / 60.0, 1e-6)
                formulation_notes.append("dissolution_t50 converted to first-order KDIS")
        except Exception:
            pass
        try:
            if dissolution_30min_pct is not None and 0 < dissolution_30min_pct < 99.9:
                k30 = -math.log(1.0 - dissolution_30min_pct / 100.0) / 0.5
                derived_dissolution_h = k30 if derived_dissolution_h is None else (derived_dissolution_h + k30) / 2.0
                formulation_notes.append("30 min dissolution converted to first-order KDIS")
        except Exception:
            pass
        explicit_dissolution = "dissolution_h" in overrides
        if derived_dissolution_h is not None and not explicit_dissolution:
            gi_transit["dissolution_h"] = round(clamp(derived_dissolution_h, 0.01, 8.0), 4)
        try:
            if particle_size_um and particle_size_um > 0 and not explicit_dissolution:
                particle_factor = clamp((100.0 / particle_size_um) ** 0.35, 0.25, 2.5)
                gi_transit["dissolution_h"] = round(clamp(gi_transit["dissolution_h"] * particle_factor, 0.01, 8.0), 4)
                formulation_notes.append("particle size adjusted dissolution rate")
        except Exception:
            pass
        if release_type in {"modified_release", "sustained_release", "extended_release"} and not explicit_dissolution:
            gi_transit["dissolution_h"] = round(max(gi_transit["dissolution_h"] * 0.35, 0.005), 4)
            formulation_notes.append("modified release slowed dissolution")
        elif release_type == "enteric_coated" and not explicit_dissolution:
            gi_transit["dissolution_h"] = round(max(gi_transit["dissolution_h"] * 0.65, 0.005), 4)
            gi_transit["abs_duodenum_h"] = round(max(gi_transit["abs_duodenum_h"] * 0.55, 0.001), 4)
            formulation_notes.append("enteric coating shifted early absorption")
        if food_state == "fed":
            gi_transit["gastric_emptying_h"] = round(max(gi_transit["gastric_emptying_h"] * 0.55, 0.001), 4)
            formulation_notes.append("fed state slowed gastric emptying")
        for key in (
            "dissolution_h", "gastric_emptying_h", "duodenum_to_jejunum_h",
            "jejunum_to_ileum_h", "ileum_to_colon_h", "colon_transit_h",
            "abs_duodenum_h", "abs_jejunum_h", "abs_ileum_h", "abs_colon_h",
        ):
            if key in overrides:
                try:
                    gi_transit[key] = round(max(float(overrides[key]), 0.0001), 4)
                    formulation_notes.append(f"explicit {key} override applied")
                except Exception:
                    pass
        api_formulation_inputs = {
            "pka_acid": None if pka_acid in (None, "") else pka_acid,
            "pka_base": None if pka_base in (None, "") else pka_base,
            "solubility_mg_ml": solubility_mg_ml,
            "particle_size_um": particle_size_um,
            "dissolution_t50_min": dissolution_t50_min,
            "dissolution_30min_pct": dissolution_30min_pct,
            "release_type": release_type,
            "food_state": food_state,
            "derived_dissolution_h": round(derived_dissolution_h, 4) if derived_dissolution_h is not None else None,
            "applied_notes": formulation_notes,
            "formulation_notes_input": formulation_notes_input,
            "api_data_source": api_data_source,
            "formulation_data_source": formulation_data_source,
            "dissolution_data_source": dissolution_data_source,
        }
        return {
            "compound_name": request.compound_name,
            "smiles": request.smiles,
            "parameter_source": "ADMET-AI/descriptor-derived whole-body PBPK parameters",
            "molecular_weight": round(mw, 3),
            "logP": round(logp, 3),
            "tpsa": round(tpsa, 3),
            "log_solubility": round(logs, 3),
            "api_formulation_inputs": api_formulation_inputs,
            "caco2_log_cm_s": round(caco2, 3),
            "fraction_unbound_plasma": round(fu, 4),
            "plasma_protein_binding": round(ppb, 4),
            "blood_plasma_ratio": round(blood_plasma_ratio, 3),
            "oral_bioavailability": round(effective_oral_f, 4),
            "ka_h": round(ka, 4),
            "vdss_l_per_kg": round(vdss_l_per_kg, 4),
            "vd_total_l": round(vd_total_l, 4),
            "total_clearance_l_h": round(cl_total_l_h, 4),
            "hepatic_clearance_l_h": round(cl_hepatic_l_h, 4),
            "renal_clearance_l_h": round(cl_renal_l_h, 4),
            "volumes_l": {key: round(value, 4) for key, value in volumes.items()},
            "blood_flows_l_h": flows,
            "partition_coefficients": kp,
            "gi_transit_absorption": gi_transit,
            "cyp3a4_substrate_probability": round(cyp3a4_sub, 4),
            "cyp3a4_inhibitor_probability": round(cyp3a4_inh, 4),
        }


    def _run_real_pbpk(self, request: Pipeline58Request, admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
        if not self.settings.prefer_real_pbpk_model:
            return None
        rscript = shutil.which(self.settings.rscript_bin) or shutil.which("Rscript")
        runner = self._pbpk_runner_path()
        if not rscript:
            self._pbpk_runner_error = "Rscript not found"
            return None
        if not runner.exists():
            self._pbpk_runner_error = f"runner not found: {runner}"
            return None
        population = self._resolve_population(request)
        compound_params = self._compound_pbpk_parameters(request, admet, population, overrides=overrides)
        payload = {
            "dosing": request.dosing.model_dump(),
            "population": population,
            "compound": compound_params,
            "admet": {
                "oral_f": compound_params["oral_bioavailability"],
                "cl_l_h": compound_params["total_clearance_l_h"],
                "vd_l": compound_params["vd_total_l"],
                "ka": compound_params["ka_h"],
            },
            "simulation": {
                "total_hours": min(self.settings.max_simulation_hours, request.dosing.interval_hours * max(request.dosing.repeat_days, 1))
            },
        }
        with tempfile.TemporaryDirectory(prefix="pipeline58_pbpk_") as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ)
            env["PIPELINE58_HOME"] = str(Path(__file__).resolve().parent.parent)
            try:
                proc = subprocess.run(
                    [rscript, str(runner), str(input_path), str(output_path)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                    check=False,
                )
            except Exception as exc:
                self._pbpk_runner_error = str(exc)
                return None
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                self._pbpk_runner_error = stderr or f"R runner failed with code {proc.returncode}"
                return None
            if not output_path.exists():
                self._pbpk_runner_error = "R runner produced no output file"
                return None
            try:
                result = json.loads(output_path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                self._pbpk_runner_error = f"invalid R output: {exc}"
                return None
        result.setdefault("scenario", {
            "route": request.dosing.route,
            "dose_mg": request.dosing.dose_mg,
            "interval_hours": request.dosing.interval_hours,
            "repeat_days": request.dosing.repeat_days,
            "population": population,
            "fitting_overrides": overrides or {},
        })
        # Keep the Python-normalized parameter object. The R/json round trip may turn null values into empty objects.
        result["compound_specific_parameters"] = compound_params
        result.setdefault("model_backend", {}).setdefault("parameterization", "compound-specific")
        return result

    def _heuristic_pbpk(self, request: Pipeline58Request, admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        population = self._resolve_population(request)
        oral_f = admet["absorption"]["Oral_F"]["value"] if request.dosing.route == "po" else 1.0
        vdss_l_per_kg = admet["distribution"]["VDss"]["value"] * population["v_factor"] * float((overrides or {}).get("v_multiplier", 1.0))
        total_cl_ml_min_kg = admet["excretion"]["CLtotal"]["value"] * population["cl_factor"] * float((overrides or {}).get("cl_multiplier", 1.0))
        weight = population["weight_kg"]
        vd_total = max(vdss_l_per_kg * weight, 8.0)
        cl_total_l_h = max(total_cl_ml_min_kg * weight * 0.06, 0.5)
        renal_factor = 0.55 if population["renal_impairment"] else 1.0
        hepatic_factor = 0.65 if population["hepatic_impairment"] else 1.0
        cl_total_l_h = round(cl_total_l_h * renal_factor * hepatic_factor, 2)
        ka = (1.0 if request.dosing.route == "po" else 3.0) * float((overrides or {}).get("ka_multiplier", 1.0))
        ke = max(cl_total_l_h / vd_total, 0.03)
        interval = request.dosing.interval_hours
        repeat_days = max(request.dosing.repeat_days, 1)
        total_hours = min(self.settings.max_simulation_hours, interval * repeat_days)
        dose = request.dosing.dose_mg
        points: List[Dict[str, float]] = []
        for hour in range(0, total_hours + 1):
            concentration = 0.0
            for n in range(repeat_days):
                dose_time = n * interval
                if dose_time > hour:
                    break
                elapsed = hour - dose_time
                if request.dosing.route == "po":
                    if abs(ka - ke) < 1e-6:
                        term = oral_f * dose / vd_total * elapsed * math.exp(-ke * elapsed)
                    else:
                        term = oral_f * dose * ka / (vd_total * (ka - ke)) * (math.exp(-ke * elapsed) - math.exp(-ka * elapsed))
                else:
                    term = oral_f * dose / vd_total * math.exp(-ke * elapsed)
                concentration += max(term * 1000.0, 0.0)
            points.append({"time_h": float(hour), "conc_ng_ml": round(concentration, 2)})
        cmax_point = max(points, key=lambda item: item["conc_ng_ml"])
        auc = 0.0
        for left, right in zip(points, points[1:]):
            auc += (left["conc_ng_ml"] + right["conc_ng_ml"]) * 0.5 * (right["time_h"] - left["time_h"])
        half_life = round(clamp(0.693 / ke, 1.0, 96.0), 2)
        rac = round(1.0 / max(1.0 - math.exp(-ke * interval), 0.15), 2)
        return {
            "model_backend": {"backend": "heuristic", "error": self._pbpk_runner_error},
            "scenario": {
                "route": request.dosing.route,
                "dose_mg": request.dosing.dose_mg,
                "interval_hours": interval,
                "repeat_days": repeat_days,
                "population": population,
                "fitting_overrides": overrides or {},
            },
            "pk_parameters": {
                "F": round(oral_f, 2),
                "Cmax": {"value": round(cmax_point["conc_ng_ml"], 2), "unit": "ng/mL"},
                "Tmax": {"value": round(cmax_point["time_h"], 2), "unit": "h"},
                "AUC0_t": {"value": round(auc, 2), "unit": "ng*h/mL"},
                "t_half": {"value": half_life, "unit": "h"},
                "Vss": {"value": round(vdss_l_per_kg, 2), "unit": "L/kg"},
                "CL": {"value": cl_total_l_h, "unit": "L/h"},
                "Rac": {"value": rac, "unit": "ratio"},
            },
            "concentration_time_curve": points,
            "go_no_go": {
                "oral_exposure": "no-go" if request.dosing.route == "po" and oral_f < 0.1 else "go",
                "accumulation": "review" if rac > 3.0 else "go",
            },
        }

    def _pbpk(self, request: Pipeline58Request, admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        real_pbpk = self._run_real_pbpk(request, admet, overrides=overrides)
        if real_pbpk:
            return real_pbpk
        return self._heuristic_pbpk(request, admet, overrides=overrides)

    def run_pksim_vm_case(self, request: Pipeline58Request, username: str | None = None, role: str | None = None) -> Dict[str, Any]:
        '''Bridge the main Pipeline58 request to the Windows VM that hosts PK-Sim.'''
        try:
            import winrm
        except Exception as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError(f"pywinrm is not installed in the Pipeline58 venv: {exc}")

        def dump_model(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump()
            if isinstance(value, dict):
                return {str(k): dump_model(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [dump_model(v) for v in value]
            return value

        run_id = f"pksimvm_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        created_at = now_iso()
        vm_host = os.environ.get("PKSIM_VM_HOST", "192.168.122.22")
        vm_user = os.environ.get("PKSIM_VM_USER", "Administrator")
        vm_password = os.environ.get("PKSIM_VM_PASSWORD", "")
        if not vm_password:
            raise ValueError("PKSIM_VM_PASSWORD is required when the optional PK-Sim VM integration is enabled")
        cli_path = os.environ.get("PKSIM_VM_CLI", r"C:\Program Files\Open Systems Pharmacology\PK-Sim 12.2\PKSim.CLI.exe")

        mapped_request = {
            "run_id": run_id,
            "created_at": created_at,
            "requested_by": username or "unknown",
            "request_source": "hanmi-main-page",
            "compound_name": request.compound_name,
            "smiles": request.smiles,
            "target_name": request.target_name,
            "indication": request.indication,
            "mechanism": request.mechanism,
            "potency_uM": request.potency_uM,
            "project": dump_model(request.project),
            "dosing": dump_model(request.dosing),
            "population": dump_model(request.population),
            "observations": dump_model(request.observations),
            "concomitant_drugs": dump_model(request.concomitant_drugs),
            "ddi_notes": dump_model(request.ddi_notes),
            "fit": dump_model(request.fit),
            "template_path": os.environ.get("PKSIM_VM_TEMPLATE", ""),
        }
        payload_dir = REPORTS_DIR / "pksim_vm_payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_secret = uuid.uuid4().hex
        payload_path = payload_dir / f"{run_id}.json"
        secret_path = payload_dir / f"{run_id}.secret"
        payload_path.write_text(json.dumps(mapped_request, ensure_ascii=False, indent=2), encoding="utf-8")
        secret_path.write_text(payload_secret, encoding="utf-8")
        payload_base_url = os.environ.get("PKSIM_VM_PAYLOAD_BASE_URL", "http://192.168.122.1:8780/api/v1/pksim-vm/payloads")
        payload_url = f"{payload_base_url}/{run_id}?secret={payload_secret}"
        vm_input_name = f"{run_id}.json"
        ps_script = rf'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$inputDir = 'C:\Pipeline58\inputs'
$outputDir = 'C:\Pipeline58\outputs'
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$inputPath = Join-Path $inputDir '{vm_input_name}'
$payloadUrl = '{payload_url}'
Invoke-WebRequest -Uri $payloadUrl -OutFile $inputPath -UseBasicParsing
$cli = '{cli_path}'
$cliExists = Test-Path $cli
if (-not $cliExists) {{ throw "PKSim.CLI not found: $cli" }}
$oldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$version = (& $cli version 2>&1 | Out-String).Trim()
$help = (& $cli help 2>&1 | Out-String)
$ErrorActionPreference = $oldErrorActionPreference
if ($null -eq $help) {{ $help = '' }}
$helpHead = $help.Substring(0, [Math]::Min(1200, $help.Length))
$result = [PSCustomObject]@{{
  ok = $true
  hostname = $env:COMPUTERNAME
  input_path = $inputPath
  output_dir = $outputDir
  cli_path = $cli
  cli_exists = $cliExists
  version = $version
  help_head = $helpHead
  simulation_status = 'not_run_no_pkml_template'
  message = 'Windows VM connection and PKSim.CLI execution succeeded. Full simulation requires a PK-Sim project/snapshot/batch template.'
}}
Write-Output '__PIPELINE58_JSON_START__'
$result | ConvertTo-Json -Depth 8 -Compress
Write-Output '__PIPELINE58_JSON_END__'
'''

        session = winrm.Session(
            f"http://{vm_host}:5985/wsman",
            auth=(vm_user, vm_password),
            transport="ntlm",
            read_timeout_sec=90,
            operation_timeout_sec=60,
        )
        response = session.run_ps(ps_script)
        stdout = (response.std_out or b"").decode("utf-8", "replace")
        stderr = (response.std_err or b"").decode("utf-8", "replace")
        if response.status_code != 0:
            raise RuntimeError(f"PK-Sim VM bridge failed with code {response.status_code}: {stderr or stdout}")
        start = stdout.find("__PIPELINE58_JSON_START__")
        end = stdout.find("__PIPELINE58_JSON_END__")
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError(f"PK-Sim VM bridge returned unexpected output: {stdout[:1200]} {stderr[:800]}")
        raw_json = stdout[start + len("__PIPELINE58_JSON_START__"):end].strip()
        vm_result = json.loads(raw_json)
        version_text = str(vm_result.get("version", ""))
        version_match = re.search(r"PKSim\.CLI[^\r\n]*", version_text)
        if version_match:
            vm_result["version"] = version_match.group(0).replace("PKSim.CLI.exe : ", "")

        pksim_vm_dir = REPORTS_DIR / "pksim_vm"
        pksim_vm_dir.mkdir(parents=True, exist_ok=True)
        artifact = {
            "run_id": run_id,
            "created_at": created_at,
            "vm_host": vm_host,
            "requested_by": username or "unknown",
            "request": mapped_request,
            "payload_path": str(payload_path),
            "payload_url": payload_url.split("?", 1)[0],
            "vm_result": vm_result,
            "cli_verified": bool(vm_result.get("cli_exists")) and "PKSim.CLI" in str(vm_result.get("version", "")),
            "simulation_status": vm_result.get("simulation_status", "unknown"),
            "raw_stdout_tail": stdout[-2000:],
            "raw_stderr_tail": stderr[-2000:],
        }
        artifact_path = pksim_vm_dir / f"{run_id}.json"
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact["artifact_path"] = str(artifact_path)
        return artifact

    def _pksim_runner_path(self) -> Path:
        return Path(__file__).resolve().parent / "runners" / "pksim_ospsuite.R"

    def run_pksim_case(self, payload: Dict[str, Any], username: str | None = None, role: str | None = None) -> Dict[str, Any]:
        run_id = f"pksim_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        created_at = now_iso()
        rscript = shutil.which(self.settings.rscript_bin) or shutil.which("Rscript")
        runner = self._pksim_runner_path()
        if not rscript:
            raise RuntimeError("Rscript not found")
        if not runner.exists():
            raise RuntimeError(f"PK-Sim runner not found: {runner}")

        source_run_id = str(payload.get("source_run_id", "") or "").strip()
        compound_parameters = payload.get("compound_parameters") if isinstance(payload.get("compound_parameters"), dict) else None
        if source_run_id and not compound_parameters:
            try:
                source_detail = self.get_run(source_run_id, username, role)
                step6 = ((source_detail.result or {}).get("step6_pbpk") or {})
                compound_parameters = step6.get("compound_specific_parameters") or None
            except Exception as exc:
                compound_parameters = {"parameter_source_error": str(exc)}

        pksim_dir = REPORTS_DIR / "pksim"
        pksim_dir.mkdir(parents=True, exist_ok=True)
        mapped_pkml_path = pksim_dir / f"{run_id}_mapped.pkml"
        request_payload = {
            "compound_name": str(payload.get("compound_name", "Aciclovir")),
            "route": str(payload.get("route", "po")),
            "dose_mg": float(payload.get("dose_mg", 500.0) or 500.0),
            "interval_hours": int(payload.get("interval_hours", 24) or 24),
            "repeat_days": int(payload.get("repeat_days", 1) or 1),
            "total_hours": int(payload.get("total_hours", 72) or 72),
            "path_filter": str(payload.get("path_filter", "PeripheralVenousBlood|Plasma")),
            "pkml_path": str(payload.get("pkml_path", "")),
            "source_run_id": source_run_id,
            "compound_parameters": compound_parameters or {},
            "export_pkml_path": str(mapped_pkml_path),
        }

        with tempfile.TemporaryDirectory(prefix="pipeline58_pksim_") as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ)
            env.setdefault("PIPELINE58_HOME", str(Path(__file__).resolve().parent.parent))
            env.setdefault("DOTNET_ROOT", "/opt/dotnet")
            proc = subprocess.run(
                [rscript, str(runner), str(input_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                raise RuntimeError(stderr or f"PK-Sim runner failed with code {proc.returncode}")
            if not output_path.exists():
                raise RuntimeError("PK-Sim runner produced no output")
            result = json.loads(output_path.read_text(encoding="utf-8-sig"))

        artifact = {
            "run_id": run_id,
            "created_at": created_at,
            "request": request_payload,
            "result": result,
        }
        artifact_path = pksim_dir / f"{run_id}.json"
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact["artifact_path"] = str(artifact_path)
        return artifact

    def _pkpd_runner_path(self) -> Path:
        return Path(__file__).resolve().parent / "runners" / "pkpd_rxode2.R"

    def _run_real_pkpd(self, request: Pipeline58Request, pbpk: Dict[str, Any], admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
        if not self.settings.prefer_real_pkpd_model:
            return None
        rscript = shutil.which(self.settings.rscript_bin) or shutil.which("Rscript")
        runner = self._pkpd_runner_path()
        if not rscript:
            self._pkpd_runner_error = "Rscript not found"
            return None
        if not runner.exists():
            self._pkpd_runner_error = f"runner not found: {runner}"
            return None
        potency_uM = request.potency_uM or self.settings.default_micromolar_potency
        molecular_weight = admet["descriptors"]["mw"] or 400.0
        ec50_ng_ml = round(potency_uM * molecular_weight * float((overrides or {}).get("ec50_multiplier", 1.0)), 2)
        hill = float((overrides or {}).get("hill", 1.2))
        emax = float((overrides or {}).get("emax", 100.0))
        payload = {
            "dosing": request.dosing.model_dump(),
            "pkpd": {
                "mechanism": request.mechanism,
                "ec50_ng_ml": ec50_ng_ml,
                "hill": hill,
                "emax": emax,
            },
            "pbpk": {
                "times": [float(point["time_h"]) for point in pbpk["concentration_time_curve"]],
                "concs": [float(point["conc_ng_ml"]) for point in pbpk["concentration_time_curve"]],
            },
        }
        with tempfile.TemporaryDirectory(prefix="pipeline58_pkpd_") as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            output_path = Path(tmpdir) / "output.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ)
            env["PIPELINE58_HOME"] = str(Path(__file__).resolve().parent.parent)
            try:
                proc = subprocess.run(
                    [rscript, str(runner), str(input_path), str(output_path)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                    check=False,
                )
            except Exception as exc:
                self._pkpd_runner_error = str(exc)
                return None
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                self._pkpd_runner_error = stderr or f"R runner failed with code {proc.returncode}"
                return None
            if not output_path.exists():
                self._pkpd_runner_error = "R runner produced no output file"
                return None
            try:
                result = json.loads(output_path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                self._pkpd_runner_error = f"invalid R output: {exc}"
                return None
        return result

    def _heuristic_pkpd(self, request: Pipeline58Request, pbpk: Dict[str, Any], admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        potency_uM = request.potency_uM or self.settings.default_micromolar_potency
        molecular_weight = admet["descriptors"]["mw"] or 400.0
        ec50_ng_ml = round(potency_uM * molecular_weight * float((overrides or {}).get("ec50_multiplier", 1.0)), 2)
        emax = float((overrides or {}).get("emax", 100.0))
        hill = float((overrides or {}).get("hill", 1.2))
        effect_curve: List[Dict[str, float]] = []
        above_mec_hours = 0
        mec = ec50_ng_ml * 0.8
        mtc = ec50_ng_ml * 6.0
        for point in pbpk["concentration_time_curve"]:
            conc = point["conc_ng_ml"]
            effect = emax * (conc ** hill) / ((ec50_ng_ml ** hill) + (conc ** hill)) if conc > 0 else 0.0
            effect_curve.append({"time_h": point["time_h"], "effect_pct": round(effect, 2), "conc_ng_ml": conc})
            if conc >= mec:
                above_mec_hours += 1
        target_attainment = round(above_mec_hours / max(len(pbpk["concentration_time_curve"]), 1), 2)
        regimen_text = "BID" if target_attainment < 0.35 and request.dosing.interval_hours >= 24 else "QD"
        therapeutic_index = round(mtc / max(mec, 1.0), 2)
        return {
            "model_backend": {"backend": "heuristic", "error": self._pkpd_runner_error},
            "model": {
                "type": "Emax",
                "mechanism": request.mechanism,
                "EC50": {"value": ec50_ng_ml, "unit": "ng/mL"},
                "Emax": {"value": emax, "unit": "%"},
                "Hill": hill,
            },
            "dose_optimization": {
                "MEC": {"value": round(mec, 2), "unit": "ng/mL"},
                "MTC": {"value": round(mtc, 2), "unit": "ng/mL"},
                "therapeutic_index": therapeutic_index,
                "target_attainment": target_attainment,
                "recommended_regimen": regimen_text,
                "recommended_starting_dose_mg": round(request.dosing.dose_mg * (0.75 if target_attainment > 0.7 else 1.25), 1),
            },
            "effect_time_curve": effect_curve,
            "go_no_go": {
                "therapeutic_index": "high-risk" if therapeutic_index < 2.0 else "go",
                "target_attainment": "review" if target_attainment < 0.3 else "go",
            },
        }

    def _pkpd(self, request: Pipeline58Request, pbpk: Dict[str, Any], admet: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        real_pkpd = self._run_real_pkpd(request, pbpk, admet, overrides=overrides)
        if real_pkpd:
            return real_pkpd
        return self._heuristic_pkpd(request, pbpk, admet, overrides=overrides)

    def _fit_observations(self, request: Pipeline58Request, pbpk: Dict[str, Any], pkpd: Dict[str, Any]) -> Dict[str, Any]:
        if not request.observations:
            return {
                "has_observations": False,
                "pk_fit": None,
                "pd_fit": None,
                "overlay_points": [],
            }
        overlay_points: List[Dict[str, Any]] = []
        pk_pairs: List[Dict[str, float]] = []
        pd_pairs: List[Dict[str, float]] = []
        for obs in request.observations:
            item: Dict[str, Any] = {"time_h": obs.time_h}
            if obs.conc_ng_ml is not None:
                pred_conc = linear_interpolate(pbpk["concentration_time_curve"], "time_h", "conc_ng_ml", obs.time_h)
                if pred_conc is not None:
                    item["obs_conc_ng_ml"] = obs.conc_ng_ml
                    item["pred_conc_ng_ml"] = round(pred_conc, 2)
                    pk_pairs.append({"obs": float(obs.conc_ng_ml), "pred": float(pred_conc)})
            if obs.effect_pct is not None:
                pred_effect = linear_interpolate(pkpd["effect_time_curve"], "time_h", "effect_pct", obs.time_h)
                if pred_effect is not None:
                    item["obs_effect_pct"] = obs.effect_pct
                    item["pred_effect_pct"] = round(pred_effect, 2)
                    pd_pairs.append({"obs": float(obs.effect_pct), "pred": float(pred_effect)})
            overlay_points.append(item)
        return {
            "has_observations": True,
            "pk_fit": self._fit_metrics(pk_pairs, unit="ng/mL"),
            "pd_fit": self._fit_metrics(pd_pairs, unit="%"),
            "overlay_points": overlay_points,
        }

    def _fit_metrics(self, pairs: List[Dict[str, float]], unit: str) -> Optional[Dict[str, Any]]:
        if not pairs:
            return None
        obs_values = [item["obs"] for item in pairs]
        pred_values = [item["pred"] for item in pairs]
        errors = [pred - obs for obs, pred in zip(obs_values, pred_values)]
        mae = sum(abs(err) for err in errors) / len(errors)
        rmse = math.sqrt(sum(err * err for err in errors) / len(errors))
        mape_terms = [abs(err) / obs for obs, err in zip(obs_values, errors) if abs(obs) > 1e-6]
        mape = (sum(mape_terms) / len(mape_terms) * 100.0) if mape_terms else None
        mean_obs = sum(obs_values) / len(obs_values)
        ss_tot = sum((obs - mean_obs) ** 2 for obs in obs_values)
        ss_res = sum((obs - pred) ** 2 for obs, pred in zip(obs_values, pred_values))
        r2 = None if ss_tot <= 1e-9 else 1.0 - (ss_res / ss_tot)
        return {
            "n": len(pairs),
            "MAE": {"value": round(mae, 2), "unit": unit},
            "RMSE": {"value": round(rmse, 2), "unit": unit},
            "MAPE_pct": None if mape is None else round(mape, 2),
            "R2": None if r2 is None else round(r2, 3),
        }

    def _fit_profile_grid(self, profile: str) -> Dict[str, List[float]]:
        if profile == "deep":
            return {
                "cl": [0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.4],
                "v": [0.7, 0.85, 1.0, 1.15, 1.3],
                "ka": [0.75, 1.0, 1.25],
                "ec50": [0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.4],
                "hill": [0.9, 1.1, 1.2, 1.4, 1.6],
            }
        if profile == "standard":
            return {
                "cl": [0.7, 0.85, 1.0, 1.2, 1.4],
                "v": [0.8, 1.0, 1.2],
                "ka": [0.8, 1.0, 1.2],
                "ec50": [0.7, 0.85, 1.0, 1.2, 1.4],
                "hill": [1.0, 1.2, 1.5],
            }
        return {
            "cl": [0.75, 1.0, 1.25],
            "v": [0.85, 1.0, 1.15],
            "ka": [0.85, 1.0, 1.15],
            "ec50": [0.75, 1.0, 1.25],
            "hill": [1.0, 1.2, 1.4],
        }

    def _rmse_against_observations(self, observations: List[Any], curve: List[Dict[str, Any]], value_key: str, obs_key: str) -> Optional[float]:
        pairs: List[float] = []
        for obs in observations:
            obs_value = getattr(obs, obs_key)
            if obs_value is None:
                continue
            pred_value = linear_interpolate(curve, "time_h", value_key, obs.time_h)
            if pred_value is None:
                continue
            pairs.append((float(pred_value) - float(obs_value)) ** 2)
        if not pairs:
            return None
        return math.sqrt(sum(pairs) / len(pairs))

    def _optimize_models(
        self,
        request: Pipeline58Request,
        admet: Dict[str, Any],
        pbpk: Dict[str, Any],
        pkpd: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not request.observations or not (request.fit.enable_pk_fit or request.fit.enable_pd_fit):
            return {
                "pbpk": pbpk,
                "pkpd": pkpd,
                "fit_summary": {
                    "enabled": False,
                    "profile": request.fit.profile,
                    "pk_fit_applied": False,
                    "pd_fit_applied": False,
                },
            }
        grid = self._fit_profile_grid(request.fit.profile)
        best_pbpk = pbpk
        best_pk_overrides: Dict[str, float] = {}
        best_pk_rmse = self._rmse_against_observations(request.observations, pbpk["concentration_time_curve"], "conc_ng_ml", "conc_ng_ml")
        if request.fit.enable_pk_fit:
            for cl_multiplier in grid["cl"]:
                for v_multiplier in grid["v"]:
                    for ka_multiplier in grid["ka"]:
                        candidate = self._pbpk(
                            request,
                            admet,
                            overrides={
                                "cl_multiplier": cl_multiplier,
                                "v_multiplier": v_multiplier,
                                "ka_multiplier": ka_multiplier,
                            },
                        )
                        rmse = self._rmse_against_observations(request.observations, candidate["concentration_time_curve"], "conc_ng_ml", "conc_ng_ml")
                        if rmse is None:
                            continue
                        if best_pk_rmse is None or rmse < best_pk_rmse:
                            best_pk_rmse = rmse
                            best_pbpk = candidate
                            best_pk_overrides = {
                                "cl_multiplier": cl_multiplier,
                                "v_multiplier": v_multiplier,
                                "ka_multiplier": ka_multiplier,
                            }
        best_pkpd = pkpd
        best_pd_overrides: Dict[str, float] = {}
        best_pd_rmse = self._rmse_against_observations(request.observations, pkpd["effect_time_curve"], "effect_pct", "effect_pct")
        if request.fit.enable_pd_fit:
            baseline_pkpd = self._pkpd(request, best_pbpk, admet)
            if best_pd_rmse is None:
                best_pd_rmse = self._rmse_against_observations(request.observations, baseline_pkpd["effect_time_curve"], "effect_pct", "effect_pct")
            if best_pd_rmse is None:
                best_pd_rmse = None
            best_pkpd = baseline_pkpd
            for ec50_multiplier in grid["ec50"]:
                for hill in grid["hill"]:
                    candidate = self._pkpd(
                        request,
                        best_pbpk,
                        admet,
                        overrides={
                            "ec50_multiplier": ec50_multiplier,
                            "hill": hill,
                            "emax": 100.0,
                        },
                    )
                    rmse = self._rmse_against_observations(request.observations, candidate["effect_time_curve"], "effect_pct", "effect_pct")
                    if rmse is None:
                        continue
                    if best_pd_rmse is None or rmse < best_pd_rmse:
                        best_pd_rmse = rmse
                        best_pkpd = candidate
                        best_pd_overrides = {
                            "ec50_multiplier": ec50_multiplier,
                            "hill": hill,
                            "emax": 100.0,
                        }
        elif best_pbpk is not pbpk:
            best_pkpd = self._pkpd(request, best_pbpk, admet)
        return {
            "pbpk": best_pbpk,
            "pkpd": best_pkpd,
            "fit_summary": {
                "enabled": True,
                "profile": request.fit.profile,
                "pk_fit_applied": request.fit.enable_pk_fit,
                "pd_fit_applied": request.fit.enable_pd_fit,
                "pk_overrides": best_pk_overrides,
                "pd_overrides": best_pd_overrides,
                "pk_rmse": None if best_pk_rmse is None else round(best_pk_rmse, 3),
                "pd_rmse": None if best_pd_rmse is None else round(best_pd_rmse, 3),
            },
        }

    def _known_ddi_drug(self, name: str) -> Dict[str, Any]:
        key = name.strip().lower()
        library = {
            "ketoconazole": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "strong"},
            "itraconazole": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "strong"},
            "clarithromycin": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "strong"},
            "erythromycin": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "moderate"},
            "diltiazem": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "moderate"},
            "verapamil": {"mechanism": "inhibitor", "enzyme": "Pgp", "strength": "moderate"},
            "rifampin": {"mechanism": "inducer", "enzyme": "CYP3A4", "strength": "strong"},
            "rifampicin": {"mechanism": "inducer", "enzyme": "CYP3A4", "strength": "strong"},
            "carbamazepine": {"mechanism": "inducer", "enzyme": "CYP3A4", "strength": "strong"},
            "phenytoin": {"mechanism": "inducer", "enzyme": "CYP3A4", "strength": "strong"},
            "fluconazole": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "moderate"},
            "grapefruit juice": {"mechanism": "inhibitor", "enzyme": "CYP3A4", "strength": "moderate"},
            "quinidine": {"mechanism": "inhibitor", "enzyme": "CYP2D6", "strength": "strong"},
            "paroxetine": {"mechanism": "inhibitor", "enzyme": "CYP2D6", "strength": "strong"},
            "cyclosporine": {"mechanism": "inhibitor", "enzyme": "OATP1B1", "strength": "strong"},
            "gemfibrozil": {"mechanism": "inhibitor", "enzyme": "OATP1B1", "strength": "strong"},
            "valproate": {"mechanism": "inhibitor", "enzyme": "UGT", "strength": "moderate"},
        }
        return library.get(key, {})

    def _mechanistic_ddi_matrix(self, request: Pipeline58Request, base_delta_auc: float, base_r_value: float) -> Dict[str, Any]:
        if not request.concomitant_drugs:
            return {"scenarios": [], "highest_risk": "low"}
        strength_scale = {"weak": 0.35, "moderate": 0.9, "strong": 1.8}
        scenario_rows: List[Dict[str, Any]] = []
        highest_risk = "low"
        for item in request.concomitant_drugs:
            known = self._known_ddi_drug(item.name)
            mechanism = known.get("mechanism", item.mechanism)
            enzyme = known.get("enzyme", item.enzyme)
            strength = known.get("strength", item.strength)
            scale = strength_scale.get(strength, 0.9)
            auc_multiplier = base_delta_auc
            r_value = base_r_value
            if enzyme == "CYP3A4":
                if mechanism == "inhibitor":
                    auc_multiplier = round(base_delta_auc * (1.0 + scale), 2)
                    r_value = round(base_r_value + 0.6 * scale, 2)
                elif mechanism == "inducer":
                    auc_multiplier = round(max(base_delta_auc * (1.0 - 0.35 * scale), 0.2), 2)
                    r_value = round(max(base_r_value - 0.25 * scale, 0.8), 2)
                elif mechanism == "substrate":
                    auc_multiplier = round(base_delta_auc * 1.15, 2)
            elif enzyme == "CYP2D6":
                if mechanism == "inhibitor":
                    auc_multiplier = round(base_delta_auc * (1.0 + 0.55 * scale), 2)
                    r_value = round(base_r_value + 0.35 * scale, 2)
                elif mechanism == "inducer":
                    auc_multiplier = round(max(base_delta_auc * (1.0 - 0.18 * scale), 0.3), 2)
                    r_value = round(max(base_r_value - 0.12 * scale, 0.8), 2)
            elif enzyme == "Pgp":
                if mechanism == "inhibitor":
                    auc_multiplier = round(base_delta_auc * (1.0 + 0.42 * scale), 2)
                    r_value = round(base_r_value + 0.28 * scale, 2)
                elif mechanism == "inducer":
                    auc_multiplier = round(max(base_delta_auc * (1.0 - 0.22 * scale), 0.35), 2)
                    r_value = round(max(base_r_value - 0.1 * scale, 0.8), 2)
            elif enzyme == "OATP1B1":
                if mechanism == "inhibitor":
                    auc_multiplier = round(base_delta_auc * (1.0 + 0.62 * scale), 2)
                    r_value = round(base_r_value + 0.22 * scale, 2)
            elif enzyme == "UGT":
                if mechanism == "inhibitor":
                    auc_multiplier = round(base_delta_auc * (1.0 + 0.3 * scale), 2)
                elif mechanism == "inducer":
                    auc_multiplier = round(max(base_delta_auc * (1.0 - 0.24 * scale), 0.35), 2)
            if mechanism == "mixed":
                auc_multiplier = round(base_delta_auc * (1.0 + 0.2 * scale), 2)
                r_value = round(base_r_value + 0.15 * scale, 2)
            classification = "high" if auc_multiplier >= 5.0 else "moderate" if auc_multiplier >= 2.0 else "low"
            if classification == "high":
                highest_risk = "high"
            elif classification == "moderate" and highest_risk != "high":
                highest_risk = "moderate"
            scenario_rows.append({
                "drug": item.name,
                "role": item.role,
                "mechanism": mechanism,
                "enzyme": enzyme,
                "strength": strength,
                "predicted_delta_auc": auc_multiplier,
                "predicted_r_value": r_value,
                "classification": classification,
                "dose_note": item.dose_note,
            })
        if len(scenario_rows) >= 2:
            combo_auc = 1.0
            combo_r = base_r_value
            for row in scenario_rows:
                combo_auc *= max(row["predicted_delta_auc"], 0.2)
                combo_r += max(row["predicted_r_value"] - 1.0, 0.0)
            combo_auc = round(combo_auc, 2)
            combo_r = round(combo_r, 2)
            combo_class = "high" if combo_auc >= 5.0 else "moderate" if combo_auc >= 2.0 else "low"
            if combo_class == "high":
                highest_risk = "high"
            elif combo_class == "moderate" and highest_risk != "high":
                highest_risk = "moderate"
            scenario_rows.append({
                "drug": "Combined scenario",
                "role": "matrix",
                "mechanism": "combined",
                "enzyme": "multi-pathway",
                "strength": "mixed",
                "predicted_delta_auc": combo_auc,
                "predicted_r_value": combo_r,
                "classification": combo_class,
                "dose_note": "Combined concomitant scenario",
            })
        return {"scenarios": scenario_rows, "highest_risk": highest_risk}

    def _virtual_population_distribution(self, request: Pipeline58Request, pbpk: Dict[str, Any]) -> Dict[str, Any]:
        base_curve = pbpk["concentration_time_curve"]
        if not base_curve:
            return {"available": False, "population_n": 0, "percentile_curve": [], "summary": {}}
        stage_penalty = 0.08
        renal_cv = {"normal": 0.0, "mild": 0.04, "moderate": 0.1, "severe": 0.18}.get(request.population.renal_stage, 0.0)
        hepatic_cv = {"normal": 0.0, "child_pugh_a": 0.05, "child_pugh_b": 0.12, "child_pugh_c": 0.2}.get(request.population.hepatic_stage, 0.0)
        pregnancy_cv = {"none": 0.0, "t1": 0.03, "t2": 0.05, "t3": 0.08}.get(request.population.pregnancy_trimester, 0.0)
        sigma = 0.18 + renal_cv + hepatic_cv + pregnancy_cv + (0.04 if request.population.preset in {"elderly", "renal_ckd", "hepatic_cirrhosis"} else 0.0)
        z_values = [-1.64, -1.28, -1.0, -0.67, -0.33, 0.0, 0.33, 0.67, 1.0, 1.28, 1.64]
        sample_curves: List[List[float]] = []
        sample_metrics: List[Dict[str, float]] = []
        times = [float(point["time_h"]) for point in base_curve]
        for z in z_values:
            cl_factor = math.exp(z * sigma)
            v_factor = math.exp(z * (sigma * 0.55 + stage_penalty))
            time_scale = max(v_factor / max(cl_factor, 0.2), 0.35)
            amp_scale = max((1.0 / max(cl_factor, 0.25)) * (1.0 / (v_factor ** 0.22)), 0.15)
            transformed: List[float] = []
            for time_h in times:
                source_time = time_h / time_scale
                source_conc = linear_interpolate(base_curve, "time_h", "conc_ng_ml", source_time)
                transformed.append(round(max((source_conc or 0.0) * amp_scale, 0.0), 4))
            sample_curves.append(transformed)
            cmax = max(transformed) if transformed else 0.0
            auc = 0.0
            for i in range(len(times) - 1):
                auc += (transformed[i] + transformed[i + 1]) * 0.5 * (times[i + 1] - times[i])
            sample_metrics.append({"cmax": round(cmax, 2), "auc": round(auc, 2)})
        percentile_curve: List[Dict[str, Any]] = []
        for index, time_h in enumerate(times):
            values = sorted(curve[index] for curve in sample_curves)
            percentile_curve.append({
                "time_h": time_h,
                "p10_conc_ng_ml": round(values[max(0, int((len(values) - 1) * 0.1))], 2),
                "p50_conc_ng_ml": round(values[int((len(values) - 1) * 0.5)], 2),
                "p90_conc_ng_ml": round(values[min(len(values) - 1, int((len(values) - 1) * 0.9))], 2),
            })
        cmax_values = sorted(item["cmax"] for item in sample_metrics)
        auc_values = sorted(item["auc"] for item in sample_metrics)
        def pct(items: List[float], q: float) -> float:
            idx = min(len(items) - 1, max(0, int((len(items) - 1) * q)))
            return round(items[idx], 2)
        return {
            "available": True,
            "population_n": len(z_values),
            "percentile_curve": percentile_curve,
            "summary": {
                "Cmax_p10": pct(cmax_values, 0.1),
                "Cmax_p50": pct(cmax_values, 0.5),
                "Cmax_p90": pct(cmax_values, 0.9),
                "AUC_p10": pct(auc_values, 0.1),
                "AUC_p50": pct(auc_values, 0.5),
                "AUC_p90": pct(auc_values, 0.9),
            },
            "model_backend": {"backend": "distribution-transform", "sigma": round(sigma, 3)},
        }

    def _pbbm_profile(self, request: Pipeline58Request, pbpk: Dict[str, Any], admet: Dict[str, Any]) -> Dict[str, Any]:
        curve = pbpk.get("concentration_time_curve", []) or []
        if not curve:
            return {
                "available": False,
                "route": request.dosing.route,
                "model_backend": {"backend": "pbbm-synthetic"},
                "summary": {},
                "segments": [],
            }
        times = [float(point.get("time_h", 0.0)) for point in curve]
        concs = [max(float(point.get("conc_ng_ml", 0.0)), 0.0) for point in curve]
        max_conc = max(max(concs), 1.0)
        oral_f = float(pbpk.get("pk_parameters", {}).get("F", 1.0) or 1.0)
        hia = float(admet.get("absorption", {}).get("HIA", {}).get("value", 0.5) or 0.5)
        cyp3a4_sub = float(admet.get("metabolism", {}).get("CYP3A4_substrate", {}).get("value", 0.5) or 0.5)

        fa = clamp(hia * 0.96, 0.08, 0.99)
        fg = clamp(1.0 - cyp3a4_sub * 0.35, 0.35, 0.99)
        fh = clamp(oral_f / max(fa * fg, 0.05), 0.15, 0.99)
        f_est = round(fa * fg * fh, 3)
        ge_t50_h = round(math.log(2) / 0.75, 2)
        si_transit_h = round(3.8 + (0.8 if request.population.preset in {"elderly", "hepatic_cirrhosis"} else 0.0), 2)

        segments: Dict[str, List[Dict[str, float]]] = {
            "stomach": [],
            "duodenum": [],
            "jejunum": [],
            "ileum": [],
            "colon": [],
            "portal": [],
            "liver": [],
            "systemic": [],
        }
        is_oral = request.dosing.route == "po"
        for time_h, conc in zip(times, concs):
            systemic_pct = clamp((conc / max_conc) * 100.0, 0.0, 100.0)
            if is_oral:
                stomach_pct = clamp(100.0 * math.exp(-0.75 * time_h), 0.0, 100.0)
                duo_pct = clamp(68.0 * max(math.exp(-0.38 * time_h) - math.exp(-1.2 * time_h), 0.0), 0.0, 100.0)
                jej_pct = clamp(84.0 * max(math.exp(-0.16 * time_h) - math.exp(-0.42 * time_h), 0.0), 0.0, 100.0)
                ileum_pct = clamp(62.0 * max(math.exp(-0.09 * time_h) - math.exp(-0.2 * time_h), 0.0), 0.0, 100.0)
                colon_pct = clamp(30.0 * (1.0 - math.exp(-0.12 * time_h)) * math.exp(-0.02 * time_h), 0.0, 100.0)
                portal_pct = clamp(systemic_pct * 0.88 + jej_pct * 0.12, 0.0, 100.0)
            else:
                stomach_pct = 0.0
                duo_pct = 0.0
                jej_pct = 0.0
                ileum_pct = 0.0
                colon_pct = 0.0
                portal_pct = clamp(systemic_pct * 0.65, 0.0, 100.0)
            liver_pct = clamp(portal_pct * (0.68 + (1.0 - fg) * 0.3), 0.0, 100.0)

            segments["stomach"].append({"time_h": time_h, "value_pct": round(stomach_pct, 2)})
            segments["duodenum"].append({"time_h": time_h, "value_pct": round(duo_pct, 2)})
            segments["jejunum"].append({"time_h": time_h, "value_pct": round(jej_pct, 2)})
            segments["ileum"].append({"time_h": time_h, "value_pct": round(ileum_pct, 2)})
            segments["colon"].append({"time_h": time_h, "value_pct": round(colon_pct, 2)})
            segments["portal"].append({"time_h": time_h, "value_pct": round(portal_pct, 2)})
            segments["liver"].append({"time_h": time_h, "value_pct": round(liver_pct, 2)})
            segments["systemic"].append({"time_h": time_h, "value_pct": round(systemic_pct, 2)})

        segment_def = [
            ("stomach", "胃", "Stomach", "#7a8aa1"),
            ("duodenum", "十二指肠", "Duodenum", "#1f77b4"),
            ("jejunum", "空肠", "Jejunum", "#2ca02c"),
            ("ileum", "回肠", "Ileum", "#ff7f0e"),
            ("colon", "结肠", "Colon", "#9467bd"),
            ("portal", "门静脉", "Portal vein", "#17becf"),
            ("liver", "肝", "Liver", "#d62728"),
            ("systemic", "体循环", "Systemic", "#204d63"),
        ]
        segment_rows = [
            {
                "key": key,
                "label_zh": label_zh,
                "label_en": label_en,
                "color": color,
                "series": segments[key],
            }
            for key, label_zh, label_en, color in segment_def
        ]
        return {
            "available": True,
            "route": request.dosing.route,
            "model_backend": {"backend": "pbbm-synthetic", "mode": "oral" if is_oral else "iv-adapted"},
            "summary": {
                "Fa": round(fa, 3),
                "Fg": round(fg, 3),
                "Fh": round(fh, 3),
                "F_estimated": f_est,
                "gastric_emptying_t50_h": ge_t50_h,
                "small_intestinal_transit_h": si_transit_h,
            },
                "segments": segment_rows,
            }

    def _equivalence_assessment(self, request: Pipeline58Request, admet: Dict[str, Any], pbpk: Dict[str, Any]) -> Dict[str, Any]:
        curve = pbpk.get("concentration_time_curve", []) or []
        if not curve:
            return {
                "available": False,
                "model_backend": {
                    "backend": "PowerTOST / bootf2",
                    "open_source": ["PowerTOST", "bootf2", "PK-Sim"],
                },
                "be": {},
                "dissolution": {},
                "comparison_series": {"be": [], "dissolution": []},
            }

        reference_request = request.model_copy(deep=True)
        reference_request.population = reference_request.population.model_copy(deep=True)
        reference_request.population.preset = "adult"
        reference_request.population.ethnicity = "general"
        reference_request.population.sex = "unknown"
        reference_request.population.weight_kg = 70.0
        reference_request.population.age_years = 40
        reference_request.population.renal_impairment = False
        reference_request.population.hepatic_impairment = False
        reference_request.population.pregnant = False
        reference_request.population.renal_stage = "normal"
        reference_request.population.hepatic_stage = "normal"
        reference_request.population.pregnancy_trimester = "none"

        ref_pbpk = self._pbpk(reference_request, admet)
        ref_curve = ref_pbpk.get("concentration_time_curve", []) or []
        if not ref_curve:
            return {
                "available": False,
                "model_backend": {
                    "backend": "PowerTOST / bootf2",
                    "open_source": ["PowerTOST", "bootf2", "PK-Sim"],
                },
                "be": {},
                "dissolution": {},
                "comparison_series": {"be": [], "dissolution": []},
            }

        def normalize_curve(points: List[Dict[str, Any]]) -> List[Dict[str, float]]:
            values = [max(float(point.get("conc_ng_ml", 0.0)), 0.0) for point in points]
            max_value = max(max(values), 1.0)
            return [
                {"time_h": float(point.get("time_h", 0.0)), "conc_ng_ml": round((max(float(point.get("conc_ng_ml", 0.0)), 0.0) / max_value) * 100.0, 2)}
                for point in points
            ]

        test_norm = normalize_curve(curve)
        ref_norm = normalize_curve(ref_curve)
        time_grid = sorted({float(point.get("time_h", 0.0)) for point in test_norm} | {float(point.get("time_h", 0.0)) for point in ref_norm})
        if len(time_grid) < 4:
            time_grid = sorted(set(time_grid + [0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]))

        def paired_series(series_a: List[Dict[str, float]], series_b: List[Dict[str, float]]) -> List[Dict[str, float]]:
            rows: List[Dict[str, float]] = []
            for time_h in time_grid:
                a = linear_interpolate(series_a, "time_h", "conc_ng_ml", time_h)
                b = linear_interpolate(series_b, "time_h", "conc_ng_ml", time_h)
                if a is None or b is None:
                    continue
                rows.append({"time_h": round(float(time_h), 2), "test": round(float(a), 2), "ref": round(float(b), 2)})
            return rows

        paired = paired_series(test_norm, ref_norm)
        test_auc = float(pbpk.get("pk_parameters", {}).get("AUC0_t", {}).get("value", 0.0) or 0.0)
        ref_auc = float(ref_pbpk.get("pk_parameters", {}).get("AUC0_t", {}).get("value", 0.0) or 0.0)
        test_cmax = float(pbpk.get("pk_parameters", {}).get("Cmax", {}).get("value", 0.0) or 0.0)
        ref_cmax = float(ref_pbpk.get("pk_parameters", {}).get("Cmax", {}).get("value", 0.0) or 0.0)
        auc_ratio = round(test_auc / ref_auc, 3) if ref_auc > 0 else None
        cmax_ratio = round(test_cmax / ref_cmax, 3) if ref_cmax > 0 else None

        log_deltas_auc = []
        log_deltas_cmax = []
        ratio_rows = []
        for row in paired:
            test_value = max(float(row["test"]), 1e-6)
            ref_value = max(float(row["ref"]), 1e-6)
            ratio = test_value / ref_value
            ratio_rows.append({"time_h": row["time_h"], "ratio_pct": round(ratio * 100.0, 2)})
            log_delta = math.log(ratio)
            log_deltas_auc.append(log_delta)
            log_deltas_cmax.append(log_delta)
        spread = statistics.pstdev(log_deltas_auc) if len(log_deltas_auc) > 1 else 0.0
        spread = max(spread, 0.12)
        def interval(value: Optional[float]) -> Dict[str, Optional[float]]:
            if value is None or value <= 0:
                return {"low": None, "high": None}
            log_value = math.log(value)
            low = math.exp(log_value - 1.645 * spread)
            high = math.exp(log_value + 1.645 * spread)
            return {"low": round(low, 3), "high": round(high, 3)}

        auc_ci = interval(auc_ratio)
        cmax_ci = interval(cmax_ratio)
        be_pass = bool(
            auc_ci["low"] is not None
            and auc_ci["high"] is not None
            and cmax_ci["low"] is not None
            and cmax_ci["high"] is not None
            and auc_ci["low"] >= 0.8
            and auc_ci["high"] <= 1.25
            and cmax_ci["low"] >= 0.8
            and cmax_ci["high"] <= 1.25
        )

        dissolution_rows = []
        for row in paired:
            if row["time_h"] <= 0:
                continue
            dissolution_rows.append({
                "time_h": row["time_h"],
                "test": row["test"],
                "ref": row["ref"],
            })
        dissolution_rows = [row for row in dissolution_rows if row["time_h"] <= 24.0][:12] or dissolution_rows[:12]
        dissolution_diff = 0.0
        dissolution_n = 0
        for row in dissolution_rows:
            dissolution_diff += (row["test"] - row["ref"]) ** 2
            dissolution_n += 1
        if dissolution_n > 0:
            f2 = 50.0 * math.log10((((1.0 + (dissolution_diff / dissolution_n)) ** -0.5) * 100.0))
        else:
            f2 = 0.0
        dissolution_pass = f2 >= 50.0

        return {
            "available": True,
            "model_backend": {
                "backend": "PowerTOST / bootf2",
                "open_source": ["PowerTOST", "bootf2", "PK-Sim"],
            },
            "reference_profile": {
                "population": {
                    "label": ref_pbpk.get("scenario", {}).get("population", {}).get("label", "Adult baseline"),
                    "backend": ref_pbpk.get("model_backend", {}).get("backend", "heuristic"),
                },
                "pk_parameters": {
                    "AUC0_t": round(ref_auc, 2),
                    "Cmax": round(ref_cmax, 2),
                },
            },
            "be": {
                "auc_ratio": auc_ratio,
                "cmax_ratio": cmax_ratio,
                "auc_90ci": auc_ci,
                "cmax_90ci": cmax_ci,
                "pass": be_pass,
                "method": "PowerTOST-style virtual TOST",
                "time_grid_n": len(paired),
            },
            "dissolution": {
                "f2": round(f2, 2),
                "pass": dissolution_pass,
                "method": "bootf2-style similarity factor",
                "time_grid_n": len(dissolution_rows),
            },
            "comparison_series": {
                "be": [
                    {
                        "label": "当前情景",
                        "color": "#0f6c78",
                        "series": test_norm,
                    },
                    {
                        "label": "成人参考",
                        "color": "#8d6a9f",
                        "series": ref_norm,
                    },
                ],
                "dissolution": [
                    {
                        "label": "当前情景",
                        "color": "#c7851a",
                        "series": test_norm,
                    },
                    {
                        "label": "成人参考",
                        "color": "#406882",
                        "series": ref_norm,
                    },
                ],
            },
        }

    def _ddi(self, request: Pipeline58Request, admet: Dict[str, Any], pbpk: Dict[str, Any], pkpd: Dict[str, Any]) -> Dict[str, Any]:
        cyp3a4_sub = admet["metabolism"]["CYP3A4_substrate"]["value"]
        cyp3a4_inh = admet["metabolism"]["CYP3A4_inhibitor"]["value"]
        cmax = pbpk["pk_parameters"]["Cmax"]["value"]
        fu = round(1.0 - admet["distribution"]["PPB"]["value"], 2)
        cmax_free = round(cmax * fu, 2)
        ki = round(max(3.0, 25.0 - 18.0 * cyp3a4_inh), 2)
        r_value = round(1.0 + (cmax_free / max(ki, 0.5)), 2)
        delta_auc = round(1.0 + cyp3a4_inh * 3.4 + cyp3a4_sub * 1.6, 2)
        herg_margin = round((1.0 - admet["toxicity"]["hERG"]["value"] + 0.1) * 30.0 / max(cmax_free / 100.0, 0.2), 2)
        ddi_class = "high" if delta_auc >= 5.0 else "moderate" if delta_auc >= 2.0 else "low"
        literature_term = quote_plus(f"{request.compound_name} CYP3A4 DDI")
        target_term = quote_plus(f"{request.compound_name} {request.target_name} safety")
        monitoring = [
            "Check QT interval if hERG probability is not green.",
            "Monitor ALT and AST during dose escalation.",
        ]
        if cyp3a4_inh >= 0.25:
            monitoring.append("Review ketoconazole and clarithromycin co-administration scenarios.")
        if request.ddi_notes:
            monitoring.extend(request.ddi_notes)
        mechanistic_matrix = self._mechanistic_ddi_matrix(request, delta_auc, r_value)
        if mechanistic_matrix["highest_risk"] in {"moderate", "high"}:
            monitoring.append("Perform concomitant-drug scenario review before escalation.")
        ddi_query = f"{request.compound_name} CYP3A4 drug interaction pharmacokinetics"
        safety_query = f"{request.compound_name} {request.target_name} safety pharmacokinetics"
        return {
            "victim_risk": {
                "CYP3A4_substrate_probability": cyp3a4_sub,
                "classification": _risk_from_probability(cyp3a4_sub),
            },
            "perpetrator_risk": {
                "CYP3A4_inhibitor_probability": cyp3a4_inh,
                "R_value": r_value,
                "delta_auc": delta_auc,
                "classification": ddi_class,
            },
            "organ_safety": {
                "hERG_safety_margin": herg_margin,
                "DILI_risk": admet["toxicity"]["DILI"]["risk"],
                "AMES_risk": admet["toxicity"]["AMES"]["risk"],
                "target_attainment_context": pkpd["dose_optimization"]["target_attainment"],
            },
            "mechanistic_matrix": mechanistic_matrix,
            "external_literature": [
                {"label": "DrugBank", "url": self.settings.ddi_sources["drugbank"]},
                {"label": "STITCH", "url": self.settings.ddi_sources["stitch"]},
                {"label": "PubMed DDI query", "url": f"{self.settings.ddi_sources['pubmed']}?term={literature_term}"},
                {"label": "PubMed safety query", "url": f"{self.settings.ddi_sources['pubmed']}?term={target_term}"},
            ],
            "literature_snapshot": {
                "ddi_query": ddi_query,
                "ddi_articles": self._fetch_pubmed_snapshot(ddi_query, max_results=3),
                "safety_query": safety_query,
                "safety_articles": self._fetch_pubmed_snapshot(safety_query, max_results=3),
            },
            "recommended_monitoring": monitoring,
            "go_no_go": {
                "ddi": "warning" if delta_auc >= 2.0 or mechanistic_matrix["highest_risk"] in {"moderate", "high"} else "go",
                "cardiac": "warning" if herg_margin < 30.0 else "go",
            },
        }

    def _overall_risk(self, admet: Dict[str, Any], pbpk: Dict[str, Any], pkpd: Dict[str, Any], ddi: Dict[str, Any]) -> str:
        if admet["toxicity"]["hERG"]["risk"] == "red" or admet["toxicity"]["DILI"]["risk"] == "red":
            return "red"
        if pbpk["go_no_go"]["oral_exposure"] == "no-go" or pkpd["go_no_go"]["therapeutic_index"] == "high-risk":
            return "red"
        if ddi["perpetrator_risk"]["classification"] in {"moderate", "high"} or ddi.get("mechanistic_matrix", {}).get("highest_risk") in {"moderate", "high"}:
            return "yellow"
        return "green"

    def _write_report(self, summary: Pipeline58RunSummary, request: Pipeline58Request, result: Dict[str, Any]) -> str:
        report_path = REPORTS_DIR / f"{summary.run_id}.md"
        audit_lines = [
            f"- submit | `{summary.created_at}` | owner `{request.project.owner}` | access `{request.project.access_level}`",
            f"- fit | `{result.get('fit_summary', {}).get('enabled')}` | profile `{result.get('fit_summary', {}).get('profile')}`",
            f"- report_export | `{summary.run_id}` | path `{report_path}`",
        ]
        lines = [
            f"# STEP 5-8 Local Report: {summary.compound_name}",
            "",
            f"- Run ID: `{summary.run_id}`",
            f"- Created at: `{summary.created_at}`",
            f"- Project: `{request.project.project_name}` / `{request.project.project_code}`",
            f"- Owner: `{request.project.owner}`",
            f"- Access level: `{request.project.access_level}`",
            f"- Target: `{summary.target_name}`",
            f"- Indication: `{request.indication}`",
            f"- Population: `{result['step6_pbpk']['scenario']['population'].get('label', result['step6_pbpk']['scenario']['population'].get('preset', 'adult'))}`",
            f"- Overall risk: `{summary.overall_risk}`",
            f"- ADMET score: `{summary.admet_score}`",
            f"- Recommended regimen: `{summary.recommended_regimen}`",
            "",
            "## Governance",
            f"- Tags: `{', '.join(request.project.tags) if request.project.tags else 'none'}`",
            f"- Concomitant drugs: `{len(request.concomitant_drugs)}`",
            f"- Observation points: `{len(request.observations)}`",
            "",
            "## ADMET",
            f"- Backend: `{result['step5_admet']['model_backend']['backend']}` / device `{result['step5_admet']['model_backend'].get('device', 'cpu')}` / workers `{result['step5_admet']['model_backend'].get('num_workers', 0)}`",
            f"- Oral F: `{result['step5_admet']['absorption']['Oral_F']['value']}`",
            f"- hERG risk: `{result['step5_admet']['toxicity']['hERG']['risk']}`",
            f"- DILI risk: `{result['step5_admet']['toxicity']['DILI']['risk']}`",
            "",
            "## PBPK",
            f"- Backend: `{result['step6_pbpk'].get('model_backend', {}).get('backend', 'heuristic')}`",
            f"- Cmax: `{result['step6_pbpk']['pk_parameters']['Cmax']['value']} ng/mL`",
            f"- Tmax: `{result['step6_pbpk']['pk_parameters']['Tmax']['value']} h`",
            f"- AUC0-t: `{result['step6_pbpk']['pk_parameters']['AUC0_t']['value']} ng*h/mL`",
            "",
            "## PK/PD",
            f"- Backend: `{result['step7_pkpd'].get('model_backend', {}).get('backend', 'heuristic')}`",
            f"- EC50: `{result['step7_pkpd']['model']['EC50']['value']} ng/mL`",
            f"- Target attainment: `{result['step7_pkpd']['dose_optimization']['target_attainment']}`",
            f"- Therapeutic index: `{result['step7_pkpd']['dose_optimization']['therapeutic_index']}`",
            "",
            "## Bioequivalence / Dissolution",
            f"- Backend: `{result.get('equivalence', {}).get('model_backend', {}).get('backend', 'PowerTOST / bootf2')}`",
            f"- BE pass: `{result.get('equivalence', {}).get('be', {}).get('pass', False)}`",
            f"- AUC ratio: `{result.get('equivalence', {}).get('be', {}).get('auc_ratio', '-')}`",
            f"- Cmax ratio: `{result.get('equivalence', {}).get('be', {}).get('cmax_ratio', '-')}`",
            f"- Dissolution f2: `{result.get('equivalence', {}).get('dissolution', {}).get('f2', '-')}`",
            f"- Dissolution pass: `{result.get('equivalence', {}).get('dissolution', {}).get('pass', False)}`",
            "",
            "## Fit Summary",
            f"- Enabled: `{result.get('fit_summary', {}).get('enabled')}`",
            f"- Profile: `{result.get('fit_summary', {}).get('profile')}`",
            f"- PK overrides: `{result.get('fit_summary', {}).get('pk_overrides')}`",
            f"- PD overrides: `{result.get('fit_summary', {}).get('pd_overrides')}`",
            "",
            "## Virtual Population",
            f"- Backend: `{result.get('virtual_population', {}).get('model_backend', {}).get('backend', 'n/a')}`",
            f"- Population n: `{result.get('virtual_population', {}).get('population_n', 0)}`",
            f"- Summary: `{result.get('virtual_population', {}).get('summary')}`",
            "",
            "## DDI",
            f"- Delta AUC: `{result['step8_ddi']['perpetrator_risk']['delta_auc']}`",
            f"- hERG safety margin: `{result['step8_ddi']['organ_safety']['hERG_safety_margin']}`",
            "",
            "## Observation Fit",
            f"- PK fit: `{result.get('observation_fit', {}).get('pk_fit')}`",
            f"- PD fit: `{result.get('observation_fit', {}).get('pd_fit')}`",
            "",
            "## Mechanistic DDI Matrix",
        ]
        for row in result["step8_ddi"].get("mechanistic_matrix", {}).get("scenarios", []):
            lines.append(f"- {row['drug']} | {row['mechanism']} {row['strength']} | delta AUC {row['predicted_delta_auc']} | class {row['classification']}")
        lines.extend([
            "",
            "## Audit Trail",
            *audit_lines,
            "",
            "## External DDI Literature",
        ])
        for item in result["step8_ddi"]["external_literature"]:
            lines.append(f"- {item['label']}: {item['url']}")
        snapshot = result["step8_ddi"].get("literature_snapshot", {})
        ddi_articles = snapshot.get("ddi_articles", [])
        safety_articles = snapshot.get("safety_articles", [])
        if ddi_articles:
            lines.append("")
            lines.append("## PubMed DDI Snapshot")
            for article in ddi_articles:
                lines.append(f"- {article['title']} | {article['source']} | {article['pubdate']} | {article['url']}")
        if safety_articles:
            lines.append("")
            lines.append("## PubMed Safety Snapshot")
            for article in safety_articles:
                lines.append(f"- {article['title']} | {article['source']} | {article['pubdate']} | {article['url']}")
        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return str(report_path)

    def _build_pipeline_detail(self, request: Pipeline58Request, persist: bool) -> Pipeline58RunDetail:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        created_at = now_iso()
        desc = smiles_descriptors(request.smiles)
        admet = self._admet(request, desc)
        pbpk = self._pbpk(request, admet)
        pkpd = self._pkpd(request, pbpk, admet)
        fit_bundle = self._optimize_models(request, admet, pbpk, pkpd)
        pbpk = fit_bundle["pbpk"]
        pkpd = fit_bundle["pkpd"]
        equivalence = self._equivalence_assessment(request, admet, pbpk)
        ddi = self._ddi(request, admet, pbpk, pkpd)
        observation_fit = self._fit_observations(request, pbpk, pkpd)
        virtual_population = self._virtual_population_distribution(request, pbpk)
        pbbm = self._pbbm_profile(request, pbpk, admet)
        overall_risk = self._overall_risk(admet, pbpk, pkpd, ddi)
        result = {
            "step5_admet": admet,
            "step6_pbpk": pbpk,
            "step7_pkpd": pkpd,
            "step8_ddi": ddi,
            "fit_summary": fit_bundle["fit_summary"],
            "observation_fit": observation_fit,
            "virtual_population": virtual_population,
            "pbbm": pbbm,
            "equivalence": equivalence,
            "overall_risk": overall_risk,
        }
        summary = Pipeline58RunSummary(
            run_id=run_id,
            compound_name=request.compound_name,
            target_name=request.target_name,
            created_at=created_at,
            overall_risk=overall_risk,
            admet_score=admet["overall_admet_score"],
            recommended_regimen=pkpd["dose_optimization"]["recommended_regimen"],
            report_path="",
        )
        payload = {
            "summary": summary.model_dump(),
            "request": request.model_dump(),
            "result": result,
        }
        if persist:
            report_path = self._write_report(summary, request, result)
            summary.report_path = report_path
            payload["summary"] = summary.model_dump()
            run_path = RUNS_DIR / f"{run_id}.json"
            run_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if PG.enabled:
                PG.upsert_run(payload, str(run_path))
        return Pipeline58RunDetail(**payload)

    def run_pipeline(self, request: Pipeline58Request) -> Pipeline58RunDetail:
        return self._build_pipeline_detail(request, persist=True)

    def preview_pipeline(self, request: Pipeline58Request) -> Pipeline58RunDetail:
        return self._build_pipeline_detail(request, persist=False)

    def list_runs(self, username: str | None = None, role: str | None = None) -> List[Pipeline58RunSummary]:
        if PG.enabled:
            runs: List[Pipeline58RunSummary] = []
            for row in PG.list_run_indexes():
                project = {
                    "project_code": row.get("project_code", "P58"),
                    "project_name": row.get("project_name", "未命名项目"),
                    "owner": row.get("owner", "analyst"),
                    "access_level": row.get("access_level", "internal"),
                }
                if not self._project_visible(project, username, role):
                    continue
                try:
                    runs.append(Pipeline58RunSummary(
                        run_id=str(row.get("run_id", "")),
                        compound_name=str(row.get("compound_name", "")),
                        target_name=str(row.get("target_name", "")),
                        created_at=str(row.get("created_at", "")),
                        overall_risk=str(row.get("overall_risk", "")),
                        admet_score=float(row.get("admet_score", 0) or 0),
                        recommended_regimen=str(row.get("recommended_regimen", "")),
                        report_path=str(row.get("report_path", "")),
                    ))
                except Exception:
                    continue
            return runs
        runs: List[Pipeline58RunSummary] = []
        for payload in self._iter_run_payloads():
            try:
                project = (payload.get("request", {}) or {}).get("project", {}) or {}
                if not self._project_visible(project, username, role):
                    continue
                runs.append(Pipeline58RunSummary(**payload["summary"]))
            except Exception:
                continue
        return runs

    def list_projects(self, username: str | None = None, role: str | None = None) -> List[Dict[str, Any]]:
        if PG.enabled:
            rows: List[Dict[str, Any]] = []
            for row in PG.list_project_indexes():
                project = {
                    "project_code": row.get("project_code", "P58"),
                    "project_name": row.get("project_name", "未命名项目"),
                    "owner": row.get("owner", "analyst"),
                    "access_level": row.get("access_level", "internal"),
                }
                if not self._project_visible(project, username, role):
                    continue
                rows.append({
                    "project_code": project["project_code"],
                    "project_name": project["project_name"],
                    "owner": project["owner"],
                    "access_level": project["access_level"],
                    "tags": row.get("tags", []) or [],
                    "run_count": int(row.get("run_count", 0) or 0),
                    "last_run_at": row.get("last_run_at", ""),
                    "last_overall_risk": row.get("last_overall_risk", ""),
                })
            return rows
        projects: Dict[str, Dict[str, Any]] = {}
        for payload in self._iter_run_payloads():
            request = payload.get("request", {})
            summary = payload.get("summary", {})
            project = request.get("project", {}) or {}
            if not self._project_visible(project, username, role):
                continue
            project_code = str(project.get("project_code", "P58"))
            project_name = str(project.get("project_name", "未命名项目"))
            row = projects.setdefault(project_code, {
                "project_code": project_code,
                "project_name": project_name,
                "owner": project.get("owner", "analyst"),
                "access_level": project.get("access_level", "internal"),
                "tags": project.get("tags", []),
                "run_count": 0,
                "last_run_at": summary.get("created_at", ""),
                "last_overall_risk": summary.get("overall_risk", ""),
            })
            row["run_count"] += 1
            if summary.get("created_at", "") > row.get("last_run_at", ""):
                row["last_run_at"] = summary.get("created_at", "")
                row["last_overall_risk"] = summary.get("overall_risk", "")
        return list(projects.values())

    def list_audit_events(self, username: str | None = None, role: str | None = None) -> List[Dict[str, Any]]:
        if PG.enabled:
            rows: List[Dict[str, Any]] = []
            for row in PG.list_run_audit_indexes():
                project = {
                    "project_code": row.get("project_code", "P58"),
                    "project_name": row.get("project_name", "未命名项目"),
                    "owner": row.get("owner", "analyst"),
                    "access_level": row.get("access_level", "internal"),
                }
                if not self._project_visible(project, username, role):
                    continue
                rows.append({
                    "run_id": row.get("run_id"),
                    "created_at": row.get("created_at"),
                    "project_code": project["project_code"],
                    "project_name": project["project_name"],
                    "owner": project["owner"],
                    "access_level": project["access_level"],
                    "compound_name": row.get("compound_name"),
                    "overall_risk": row.get("overall_risk"),
                    "fit_enabled": bool(row.get("fit_enabled", False)),
                })
            return rows
        events: List[Dict[str, Any]] = []
        for payload in self._iter_run_payloads():
            request = payload.get("request", {})
            project = request.get("project", {}) or {}
            if not self._project_visible(project, username, role):
                continue
            summary = payload.get("summary", {})
            fit_summary = payload.get("result", {}).get("fit_summary", {})
            events.append({
                "run_id": summary.get("run_id"),
                "created_at": summary.get("created_at"),
                "project_code": project.get("project_code", "P58"),
                "project_name": project.get("project_name", "未命名项目"),
                "owner": project.get("owner", "analyst"),
                "access_level": project.get("access_level", "internal"),
                "compound_name": summary.get("compound_name"),
                "overall_risk": summary.get("overall_risk"),
                "fit_enabled": fit_summary.get("enabled", False),
            })
        return events

    def get_run(self, run_id: str, username: str | None = None, role: str | None = None) -> Pipeline58RunDetail:
        if PG.enabled:
            try:
                payload = PG.get_run_payload(run_id)
                project = (payload.get("request", {}) or {}).get("project", {}) or {}
                if not self._project_visible(project, username, role):
                    raise PermissionError(run_id)
                return Pipeline58RunDetail(**payload)
            except FileNotFoundError:
                pass
        path = RUNS_DIR / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(run_id)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        project = (payload.get("request", {}) or {}).get("project", {}) or {}
        if not self._project_visible(project, username, role):
            raise PermissionError(run_id)
        return Pipeline58RunDetail(**payload)

    def _svg_line_chart(self, points: List[Dict[str, Any]], x_key: str, y_key: str, stroke: str, fill: str) -> str:
        if not points:
            return '<div class="report-empty">No chart data.</div>'
        width = 720
        height = 260
        margin = {"top": 16, "right": 18, "bottom": 34, "left": 52}
        xs = [float(point.get(x_key, 0.0)) for point in points]
        ys = [float(point.get(y_key, 0.0)) for point in points]
        min_x = min(xs)
        max_x = max(xs)
        max_y = max(max(ys), 1.0)
        x_span = max(max_x - min_x, 1.0)
        y_span = max(max_y, 1.0)

        def project_x(value: float) -> float:
            return margin["left"] + ((value - min_x) / x_span) * (width - margin["left"] - margin["right"])

        def project_y(value: float) -> float:
            return height - margin["bottom"] - (value / y_span) * (height - margin["top"] - margin["bottom"])

        polyline = " ".join(f"{project_x(x):.1f},{project_y(y):.1f}" for x, y in zip(xs, ys))
        area_path = f"{polyline} {project_x(xs[-1]):.1f},{height - margin['bottom']} {project_x(xs[0]):.1f},{height - margin['bottom']}"
        return f"""
        <svg viewBox="0 0 {width} {height}" class="report-svg" role="img" aria-label="chart">
          <rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#f8fbfc"></rect>
          <polygon points="{area_path}" fill="{fill}"></polygon>
          <polyline points="{polyline}" fill="none" stroke="{stroke}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
        </svg>
        """

    def render_run_report_html(self, detail: Pipeline58RunDetail) -> str:
        summary = detail.summary.model_dump()
        request = detail.request
        result = detail.result
        step5 = result.get("step5_admet", {})
        step6 = result.get("step6_pbpk", {})
        step7 = result.get("step7_pkpd", {})
        step8 = result.get("step8_ddi", {})
        equivalence = result.get("equivalence", {})
        equivalence_series = equivalence.get("comparison_series", {}) or {}
        equivalence_be_series = equivalence_series.get("be", [])[0].get("series", []) if equivalence_series.get("be") else []
        equivalence_dissolution_series = equivalence_series.get("dissolution", [])[0].get("series", []) if equivalence_series.get("dissolution") else []
        population = (step6.get("scenario", {}) or {}).get("population", {}) or {}
        admet_backend = (step5.get("model_backend", {}) or {}).get("backend", "-")
        admet_device = (step5.get("model_backend", {}) or {}).get("device", "cpu")
        pbpk_curve = step6.get("concentration_time_curve", []) or []
        pkpd_curve = step7.get("effect_time_curve", []) or []
        html_path = REPORTS_DIR / f"{summary['run_id']}.html"
        report_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(summary['compound_name'])} | Pipeline58 Report</title>
  <style>
    body {{ margin:0; background:#edf2f4; color:#18242b; font-family:"Aptos","Segoe UI Variable","Noto Sans SC",sans-serif; }}
    .wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 48px; }}
    .hero, .card {{ background:#ffffff; border:1px solid rgba(24,36,43,0.08); border-radius:24px; box-shadow:0 18px 44px rgba(21,31,38,0.08); }}
    .hero {{ padding:28px; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-top:18px; }}
    .metric {{ padding:16px; border-radius:18px; background:#f7fafb; border:1px solid rgba(32,77,99,0.08); }}
    .metric .k {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:#67808a; }}
    .metric .v {{ margin-top:8px; font-size:28px; font-weight:700; }}
    .section {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-top:18px; }}
    .card {{ padding:22px; }}
    .card h2 {{ margin:0 0 8px; font-size:22px; }}
    .sub {{ color:#5f757e; line-height:1.6; }}
    .report-svg {{ width:100%; height:auto; display:block; }}
    .kv {{ display:grid; grid-template-columns:1fr 1fr; gap:10px 16px; margin-top:14px; }}
    .kv div {{ padding:10px 12px; background:#f7fafb; border-radius:14px; border:1px solid rgba(24,36,43,0.06); }}
    .label {{ color:#66808a; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    .value {{ margin-top:6px; font-weight:700; }}
    .badge {{ display:inline-block; padding:8px 12px; border-radius:999px; background:#204d63; color:#fff; font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:14px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid rgba(24,36,43,0.08); text-align:left; vertical-align:top; }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="label">Pipeline58 professional report</div>
      <h1 style="margin:6px 0 8px;font-size:42px;line-height:1;">{html.escape(summary['compound_name'])}</h1>
      <div class="sub">STEP 5-8 本地闭环结果，覆盖 ADMET、PBPK、PK/PD 与 DDI。当前 ADMET 设备为 {html.escape(str(admet_device).upper())}。</div>
      <div style="margin-top:12px;"><span class="badge">Overall risk: {html.escape(str(summary['overall_risk']).upper())}</span></div>
      <div class="grid">
        <div class="metric"><div class="k">Run ID</div><div class="v" style="font-size:18px">{html.escape(summary['run_id'])}</div></div>
        <div class="metric"><div class="k">ADMET score</div><div class="v">{html.escape(str(summary['admet_score']))}</div></div>
        <div class="metric"><div class="k">PBPK Cmax</div><div class="v">{html.escape(str(step6.get('pk_parameters', {}).get('Cmax', {}).get('value', '-')))}</div></div>
        <div class="metric"><div class="k">PBPK AUC</div><div class="v">{html.escape(str(step6.get('pk_parameters', {}).get('AUC0_t', {}).get('value', '-')))}</div></div>
      </div>
    </section>
    <section class="section">
      <div class="card">
        <h2>Exposure</h2>
        <div class="sub">真实 PBPK 后端输出的浓度-时间曲线。</div>
        {self._svg_line_chart(pbpk_curve, 'time_h', 'conc_ng_ml', '#176f82', 'rgba(23,111,130,0.18)')}
        <div class="kv">
          <div><div class="label">Population</div><div class="value">{html.escape(str(population.get('label', population.get('preset', '-'))))}</div></div>
          <div><div class="label">Backend</div><div class="value">{html.escape(str(step6.get('model_backend', {}).get('backend', '-')))}</div></div>
          <div><div class="label">Cmax</div><div class="value">{html.escape(str(step6.get('pk_parameters', {}).get('Cmax', {}).get('value', '-')))} ng/mL</div></div>
          <div><div class="label">Tmax</div><div class="value">{html.escape(str(step6.get('pk_parameters', {}).get('Tmax', {}).get('value', '-')))} h</div></div>
        </div>
      </div>
      <div class="card">
        <h2>Response</h2>
        <div class="sub">真实 PK/PD 后端输出的效应曲线与推荐给药。</div>
        {self._svg_line_chart(pkpd_curve, 'time_h', 'effect_pct', '#8b4f9c', 'rgba(139,79,156,0.16)')}
        <div class="kv">
          <div><div class="label">Backend</div><div class="value">{html.escape(str(step7.get('model_backend', {}).get('backend', '-')))}</div></div>
          <div><div class="label">Recommended regimen</div><div class="value">{html.escape(str(summary.get('recommended_regimen', '-')))}</div></div>
          <div><div class="label">Target attainment</div><div class="value">{html.escape(str(step7.get('dose_optimization', {}).get('target_attainment', '-')))}</div></div>
          <div><div class="label">EC50</div><div class="value">{html.escape(str(step7.get('model', {}).get('EC50', '-')))}</div></div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="card">
        <h2>Bioequivalence</h2>
        <div class="sub">开源方法链路：PowerTOST 风格 TOST + PK-Sim 参考基线。</div>
        {self._svg_line_chart(equivalence_be_series, 'time_h', 'conc_ng_ml', '#0f6c78', 'rgba(15,108,120,0.16)')}
        <div class="kv">
          <div><div class="label">Backend</div><div class="value">{html.escape(str(equivalence.get('model_backend', {}).get('backend', 'PowerTOST / bootf2')))}</div></div>
          <div><div class="label">BE pass</div><div class="value">{html.escape(str(equivalence.get('be', {}).get('pass', '-')))}</div></div>
          <div><div class="label">AUC ratio</div><div class="value">{html.escape(str(equivalence.get('be', {}).get('auc_ratio', '-')))}</div></div>
          <div><div class="label">Cmax ratio</div><div class="value">{html.escape(str(equivalence.get('be', {}).get('cmax_ratio', '-')))}</div></div>
        </div>
      </div>
      <div class="card">
        <h2>Dissolution equivalence</h2>
        <div class="sub">开源方法链路：bootf2 相似因子 + 释放/吸收代理曲线。</div>
        {self._svg_line_chart(equivalence_dissolution_series, 'time_h', 'conc_ng_ml', '#c7851a', 'rgba(199,133,26,0.16)')}
        <div class="kv">
          <div><div class="label">f2</div><div class="value">{html.escape(str(equivalence.get('dissolution', {}).get('f2', '-')))}</div></div>
          <div><div class="label">Pass</div><div class="value">{html.escape(str(equivalence.get('dissolution', {}).get('pass', '-')))}</div></div>
          <div><div class="label">Method</div><div class="value">{html.escape(str(equivalence.get('dissolution', {}).get('method', '-')))}</div></div>
          <div><div class="label">Reference</div><div class="value">PK-Sim / adult baseline</div></div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="card">
        <h2>ADMET</h2>
        <table>
          <tr><th>Backend</th><td>{html.escape(str(admet_backend))}</td></tr>
          <tr><th>Device</th><td>{html.escape(str(admet_device))}</td></tr>
          <tr><th>Oral F</th><td>{html.escape(str(step5.get('absorption', {}).get('Oral_F', {}).get('value', '-')))}</td></tr>
          <tr><th>hERG risk</th><td>{html.escape(str(step5.get('toxicity', {}).get('hERG', {}).get('risk', '-')))}</td></tr>
          <tr><th>DILI risk</th><td>{html.escape(str(step5.get('toxicity', {}).get('DILI', {}).get('risk', '-')))}</td></tr>
        </table>
      </div>
      <div class="card">
        <h2>DDI and safety</h2>
        <table>
          <tr><th>DDI classification</th><td>{html.escape(str(step8.get('ddi_risk', {}).get('classification', '-')))}</td></tr>
          <tr><th>Predicted AUC fold</th><td>{html.escape(str(step8.get('ddi_risk', {}).get('predicted_auc_fold_change', '-')))}</td></tr>
          <tr><th>R value</th><td>{html.escape(str(step8.get('ddi_risk', {}).get('r_value', '-')))}</td></tr>
          <tr><th>Notes</th><td>{html.escape(' | '.join(request.get('ddi_notes', [])) or '-')}</td></tr>
        </table>
      </div>
    </section>
  </div>
</body>
</html>"""
        html_path.write_text(report_html, encoding="utf-8")
        return report_html

    def _write_batch_report_html(self, task_id: str, task_payload: Dict[str, Any], items: List[Dict[str, Any]], result: Dict[str, Any]) -> str:
        html_path = self._task_html_path(task_id)
        top_rows = sorted(items, key=lambda row: (-float(row.get("overall_admet_score") or 0), str(row.get("compound_name", ""))))[:24]
        rows_html = "".join(
            f"<tr><td>{html.escape(str(item.get('compound_name', '')))}</td><td>{html.escape(str(item.get('gpu_index', '')))}</td><td>{html.escape(str(item.get('overall_admet_score', '')))}</td><td>{html.escape(str(item.get('herg_risk', '')))}</td><td>{html.escape(str(item.get('dili_risk', '')))}</td><td>{html.escape(' | '.join(item.get('development_flags', [])) or '-')}</td></tr>"
            for item in top_rows
        )
        rows_html = rows_html or '<tr><td colspan="6">No rows</td></tr>'
        report_html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(task_payload.get('project_name', task_id))}</title>
<style>body{{margin:0;background:#edf2f4;color:#18242b;font-family:"Aptos","Segoe UI Variable","Noto Sans SC",sans-serif;}}.wrap{{max-width:1100px;margin:0 auto;padding:32px 20px 48px;}}.card{{background:#fff;border:1px solid rgba(24,36,43,.08);border-radius:24px;box-shadow:0 18px 44px rgba(21,31,38,.08);padding:24px;margin-bottom:18px;}}table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px;}}th,td{{padding:10px 12px;border-bottom:1px solid rgba(24,36,43,.08);text-align:left;vertical-align:top;}}.pill{{display:inline-block;padding:8px 12px;border-radius:999px;background:#204d63;color:#fff;font-weight:700;}}</style></head>
<body><div class="wrap">
<section class="card"><div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#667f89;">Batch screening report</div><h1 style="margin:8px 0 10px;font-size:40px;line-height:1;">{html.escape(task_payload.get('project_name', 'ADMET 批量筛选'))}</h1><div style="color:#617781;line-height:1.7;">任务 ID {html.escape(task_id)}，共提交 {task_payload.get('submitted', 0)} 个化合物，使用 GPU {html.escape(', '.join(str(item) for item in result.get('gpu_workers', [])) or '-')} 并行筛选。</div><div style="margin-top:12px;"><span class="pill">{html.escape(str(task_payload.get('status', 'completed')).upper())}</span></div></section>
<section class="card"><h2 style="margin:0 0 8px;">Top results</h2><table><thead><tr><th>Compound</th><th>GPU</th><th>ADMET score</th><th>hERG</th><th>DILI</th><th>Flags</th></tr></thead><tbody>{rows_html}</tbody></table></section>
</div></body></html>"""
        html_path.write_text(report_html, encoding="utf-8")
        return str(html_path)
