"""Endpoints de administracion de sincronizacion."""

import logging
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import fetch_all, fetch_one


class SyncRunRequest(BaseModel):
    days: int = Field(7, ge=1, le=3650)
    skip_documents: bool = False
    skip_stock_snapshot: bool = False

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger(__name__)

# Estado in-memory de tareas disparadas desde la API
_task_state: dict[str, dict[str, Any]] = {}


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # produccion/


def _run_update_all(task_id: str, days: int,
                    skip_documents: bool, skip_stock_snapshot: bool) -> None:
    """Ejecuta update_all.py como subproceso y guarda el resultado."""
    _task_state[task_id]["status"] = "RUNNING"
    _task_state[task_id]["started_at"] = datetime.utcnow().isoformat()

    json_path = PROJECT_ROOT / f"report_{task_id}.json"
    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "update_all.py"),
        "--days", str(days),
        "--json", str(json_path),
    ]
    if skip_documents:
        cmd.append("--skip-documents")
    if skip_stock_snapshot:
        cmd.append("--skip-stock-snapshot")

    try:
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5400,  # 90 min
        )
        _task_state[task_id]["returncode"] = proc.returncode
        _task_state[task_id]["stdout_tail"] = proc.stdout[-4000:] if proc.stdout else ""
        _task_state[task_id]["stderr_tail"] = proc.stderr[-2000:] if proc.stderr else ""
        _task_state[task_id]["report_path"] = str(json_path) if json_path.exists() else None
        _task_state[task_id]["status"] = "SUCCESS" if proc.returncode == 0 else "FAILED"
    except Exception as exc:
        logger.exception("Error ejecutando update_all: %s", exc)
        _task_state[task_id]["status"] = "FAILED"
        _task_state[task_id]["error"] = str(exc)
    finally:
        _task_state[task_id]["finished_at"] = datetime.utcnow().isoformat()


@router.post("/incremental")
def trigger_incremental() -> dict:
    """
    Sync RAPIDA (en proceso, NO subprocess) que solo refresca catalogo:
        - product_types
        - products + variants
        - subcategory_resolver

    NO descarga documentos, NO snapshotea stock, NO recalcula costos.
    Pensada para correr DESPUES de crear/editar product_types o cuando
    aparece un producto nuevo en BSale, asi se ve reflejado al instante.

    Devuelve un mini-informe JSON con stats por entidad.
    """
    from datetime import datetime, timezone

    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "ok": True,
        "operation": "sync_incremental",
        "started_at": started.isoformat(),
        "stats": {},
        "warnings": [],
    }

    try:
        # Import diferido para no penalizar el arranque del API.
        from harvester import db as h_db, sync_masters

        # El harvester tiene su propio pool (separado del de la API).
        # init_pool() es idempotente: si ya esta inicializado, no hace nada.
        h_db.init_pool()

        # 1) Taxonomy NO se toca: vive solo en BD interna.
        # 2) product_types: trae cualquier categoria nueva creada en BSale.
        report["stats"]["product_types"] = sync_masters.sync_product_types()

        # 3) products + variants (sync_variants() crea ambos por FK).
        report["stats"]["variants"] = sync_masters.sync_variants()

    except Exception as exc:
        logger.exception("Error en sync incremental: %s", exc)
        report["ok"] = False
        report["error"] = str(exc)
        finished = datetime.now(timezone.utc)
        report["finished_at"] = finished.isoformat()
        report["duration_s"] = (finished - started).total_seconds()
        raise HTTPException(500, detail=report)

    finished = datetime.now(timezone.utc)
    report["finished_at"] = finished.isoformat()
    report["duration_s"] = (finished - started).total_seconds()

    # Productos huerfanos restantes (sin mapeo via product_type ni override)
    from app.database import fetch_scalar as _fs
    huerfanos = _fs("""
        SELECT COUNT(*) FROM v_products_full
        WHERE department IS NULL
    """) or 0
    report["productos_huerfanos"] = huerfanos
    if huerfanos > 0:
        report["warnings"].append(
            f"Quedan {huerfanos} productos sin mapear. "
            f"Crea product_types o usa PATCH /products/{{id}}/subcategory."
        )

    return report


@router.post("/run")
def trigger_update(payload: SyncRunRequest | None = None) -> dict:
    """
    Dispara update_all.py en background.

    Acepta body JSON (recomendado) o query params:
        POST /sync/run
        {"days": 7, "skip_documents": false, "skip_stock_snapshot": false}

    Retorna un task_id para consultar estado via /sync/tasks/{task_id}.
    """
    params = payload or SyncRunRequest()
    task_id = uuid.uuid4().hex[:10]
    _task_state[task_id] = {
        "task_id": task_id,
        "status": "QUEUED",
        "params": params.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
    }
    # No bloqueamos el request - corre en thread aparte
    thread = threading.Thread(
        target=_run_update_all,
        args=(task_id, params.days, params.skip_documents,
              params.skip_stock_snapshot),
        daemon=True,
    )
    thread.start()
    return {
        "ok": True,
        "message": f"Sync encolada ({params.days} dias)",
        "task_id": task_id,
    }


@router.get("/tasks")
def list_tasks() -> list[dict]:
    """Tareas disparadas desde la API en esta instancia."""
    return list(_task_state.values())


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = _task_state.get(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} no encontrada")
    return task


@router.get("/log")
def sync_log(limit: int = Query(30, ge=1, le=500)) -> list[dict]:
    """Historico de syncs persistido en la tabla sync_log."""
    return fetch_all("""
        SELECT id, entity, status, started_at, finished_at,
               records_fetched, records_inserted,
               records_updated, records_skipped, error_message,
               EXTRACT(EPOCH FROM (finished_at - started_at))::int AS duracion_s
        FROM sync_log
        ORDER BY started_at DESC
        LIMIT %s
    """, (limit,))


@router.get("/log/{entity}")
def sync_log_by_entity(entity: str) -> list[dict]:
    return fetch_all("""
        SELECT id, entity, status, started_at, finished_at,
               records_fetched, records_inserted,
               records_updated, records_skipped, error_message
        FROM sync_log
        WHERE entity = %s
        ORDER BY started_at DESC
        LIMIT 20
    """, (entity,))


@router.get("/data-quality")
def data_quality(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return fetch_all("""
        SELECT id, entity, bsale_id, field, issue_type, description, created_at
        FROM data_quality_issues
        ORDER BY created_at DESC
        LIMIT %s
    """, (limit,))
