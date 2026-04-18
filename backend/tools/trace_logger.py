"""Phase 4 trace persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_DIR = Path(os.getenv("AI_K8S_TRACE_DIR", str(REPO_ROOT / "backend" / "traces")))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_trace_dir() -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)


def _trace_file_path(trace_id: str, trace_type: str) -> Path:
    safe_trace_type = "".join(ch if ch.isalnum() or ch in ["-", "_"] else "_" for ch in trace_type)
    return TRACE_DIR / f"{safe_trace_type}-{trace_id}.json"


def write_trace(trace_type: str, payload: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _ensure_trace_dir()

    trace_id = str(uuid4())
    created_at = _utc_timestamp()
    trace_document = {
        "trace_id": trace_id,
        "trace_type": trace_type,
        "created_at": created_at,
        "metadata": metadata or {},
        "payload": payload,
    }

    trace_file = _trace_file_path(trace_id=trace_id, trace_type=trace_type)
    trace_file.write_text(json.dumps(trace_document, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "trace_id": trace_id,
        "trace_type": trace_type,
        "created_at": created_at,
        "file": str(trace_file),
    }


def list_traces(limit: int = 20, trace_type: Optional[str] = None) -> Dict[str, Any]:
    _ensure_trace_dir()

    files = sorted(TRACE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    summaries: List[Dict[str, Any]] = []

    for file_path in files:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        if trace_type and data.get("trace_type") != trace_type:
            continue

        summaries.append(
            {
                "trace_id": data.get("trace_id"),
                "trace_type": data.get("trace_type"),
                "created_at": data.get("created_at"),
                "file": str(file_path),
            }
        )

        if len(summaries) >= max(1, limit):
            break

    return {
        "ok": True,
        "count": len(summaries),
        "traces": summaries,
    }


def read_trace(trace_id: str) -> Dict[str, Any]:
    _ensure_trace_dir()

    matches = sorted(TRACE_DIR.glob(f"*-{trace_id}.json"))
    if not matches:
        return {
            "ok": False,
            "error": f"Trace not found for trace_id '{trace_id}'",
        }

    target = matches[-1]
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": f"Trace file '{target.name}' is not valid JSON",
        }

    return {
        "ok": True,
        "trace": data,
    }
