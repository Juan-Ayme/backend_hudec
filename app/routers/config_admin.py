"""
Configuración runtime editable (tabla `app_config`).

Gestiona las **exclusiones** de departamentos/categorías que se ocultan POR COMPLETO
de las matrices de clasificación. La DB es la fuente de verdad (editable en vivo desde
la UI); el `.env` ya NO controla esto.

★ Se guardan por NOMBRE (no por ID) porque los IDs de la taxonomía se reasignan cuando
  un sync re-siembra `departments`/`categories`. Guardar el nombre sobrevive a esos
  re-seeds; el ID actual se resuelve en cada consulta. Los nombres se almacenan como
  JSON (algunos nombres tienen comas, ej. "Vinos, Licores y Cervezas").

Solo las matrices usan estas exclusiones; analytics/documents filtran por sucursal.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel

from app.database import get_db

router = APIRouter(prefix="/config", tags=["config"])


def _parse_names(value: str | None) -> list[str]:
    """Parsea el valor JSON guardado a lista de nombres. Tolera vacío/legado/basura."""
    if not value:
        return []
    try:
        arr = json.loads(value)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except (ValueError, TypeError):
        pass
    return []  # legado (ej. "21,12") o corrupto → sin exclusiones


async def resolve_department_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """Convierte nombres de departamento a sus IDs ACTUALES (robusto a re-seeds)."""
    if not names:
        return []
    return list(
        (await db.execute(
            text("SELECT id FROM departments WHERE name = ANY(:n)"), {"n": names}
        )).scalars().all()
    )


async def resolve_category_ids(db: AsyncSession, names: list[str]) -> list[int]:
    if not names:
        return []
    return list(
        (await db.execute(
            text("SELECT id FROM categories WHERE name = ANY(:n)"), {"n": names}
        )).scalars().all()
    )


async def _read_cfg_names(db: AsyncSession, key: str) -> list[str]:
    val = await db.scalar(text("SELECT value FROM app_config WHERE key = :k"), {"k": key})
    return _parse_names(val)


async def get_exclusions(db: AsyncSession) -> dict:
    """Exclusiones vigentes resueltas a IDs ACTUALES (para parametrizar las matrices).

    Returns: {"departments": [int], "categories": [int], "department_names": [...], ...}
    """
    dep_names = await _read_cfg_names(db, "excluded_departments")
    cat_names = await _read_cfg_names(db, "excluded_categories")
    return {
        "departments": await resolve_department_ids(db, dep_names),
        "categories": await resolve_category_ids(db, cat_names),
        "department_names": dep_names,
        "category_names": cat_names,
    }


async def get_seasonal(db: AsyncSession) -> list[int]:
    """IDs ACTUALES de los departamentos estacionales (config en app_config, por nombre)."""
    names = await _read_cfg_names(db, "seasonal_departments")
    return await resolve_department_ids(db, names)


# ──────────────────────────────────────────────────────────────────────────────
# Metas de venta (KPI "Venta acumulada vs meta"). Manuales: gerencia las carga.
#
# Se guardan como JSON en app_config bajo la clave 'sales_goals', keyed por mes
# ("YYYY-MM") para conservar historia y permitir cargar el mes siguiente con
# anticipación. Montos en S/ (moneda de la venta). Estructura:
#   {"2026-06": {"global": 500000, "1": 300000, "3": 200000}, ...}
# Las claves numéricas son bsale_office_id; "global" es la meta de toda la empresa.
# A diferencia de las exclusiones (taxonomía), las oficinas tienen IDs estables,
# así que aquí guardamos por ID directamente (no por nombre).
# ──────────────────────────────────────────────────────────────────────────────

GOALS_KEY = "sales_goals"


async def get_goals(db: AsyncSession) -> dict:
    """Todas las metas configuradas: {"YYYY-MM": {"global": x, "<office_id>": y}}.

    Devuelve {} si no hay nada cargado o el valor está corrupto (degradación segura)."""
    val = await db.scalar(text("SELECT value FROM app_config WHERE key = :k"), {"k": GOALS_KEY})
    if not val:
        return {}
    try:
        data = json.loads(val)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def goal_for_month(goals: dict, month: str) -> tuple[dict, str]:
    """Meta vigente para `month` ("YYYY-MM"). Si ese mes no tiene meta cargada,
    hereda la del último mes configurado <= month (fallback).

    Returns: (dict_meta, fuente) donde fuente ∈ {"exacta", "heredada:<mes>", "no_configurada"}.
    """
    if month in goals and goals[month]:
        return goals[month], "exacta"
    past = sorted(m for m in goals if m <= month and goals[m])
    if past:
        return goals[past[-1]], f"heredada:{past[-1]}"
    return {}, "no_configurada"


async def set_goals_month(db: AsyncSession, month: str, month_goals: dict) -> dict:
    """Reemplaza (upsert) la meta de UN mes y persiste todo el JSON. Devuelve el dict completo."""
    goals = await get_goals(db)
    goals[month] = month_goals
    await db.execute(
        text(
            "INSERT INTO app_config (key, value, updated_at) VALUES (:k, :v, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"k": GOALS_KEY, "v": json.dumps(goals, ensure_ascii=False)},
    )
    await db.commit()
    return goals


class ExclusionsBody(BaseModel):
    excluded_departments: list[int]  # IDs actuales (la UI trabaja con IDs)
    excluded_categories: list[int]
    seasonal_departments: list[int] = []  # departamentos de campaña (estacionales)


async def _dept_names(db: AsyncSession, ids: list[int]) -> list[str]:
    if not ids:
        return []
    return list(
        (await db.execute(
            text("SELECT name FROM departments WHERE id = ANY(:ids)"), {"ids": ids}
        )).scalars().all()
    )


@router.get("/exclusions")
async def read_exclusions(db: AsyncSession = Depends(get_db)) -> dict:
    """Exclusiones + estacionales actuales (IDs resueltos) + todos los departamentos con sus flags."""
    excl = await get_exclusions(db)
    seasonal_ids = await get_seasonal(db)
    dep_excluded = set(excl["departments"])
    dep_seasonal = set(seasonal_ids)
    depts = (
        await db.execute(text("SELECT id, name FROM departments ORDER BY name"))
    ).mappings().all()
    return {
        "excluded_departments": excl["departments"],
        "excluded_categories": excl["categories"],
        "excluded_department_names": excl["department_names"],
        "seasonal_departments": seasonal_ids,
        "departments": [
            {
                "id": d["id"],
                "name": d["name"],
                "excluded": d["id"] in dep_excluded,
                "seasonal": d["id"] in dep_seasonal,
            }
            for d in depts
        ],
    }


@router.put("/exclusions")
async def write_exclusions(
    body: ExclusionsBody, db: AsyncSession = Depends(get_db)
) -> dict:
    """Reemplaza exclusiones y estacionales. La UI envía IDs actuales; se convierten a
    NOMBRES para guardar (robusto a re-seeds). Efecto inmediato y global en las matrices."""
    excl_dep = await _dept_names(db, body.excluded_departments)
    seasonal_dep = await _dept_names(db, body.seasonal_departments)
    cat_names: list[str] = []
    if body.excluded_categories:
        cat_names = list(
            (await db.execute(
                text("SELECT name FROM categories WHERE id = ANY(:ids)"),
                {"ids": body.excluded_categories},
            )).scalars().all()
        )
    for key, names in [
        ("excluded_departments", excl_dep),
        ("excluded_categories", cat_names),
        ("seasonal_departments", seasonal_dep),
    ]:
        await db.execute(
            text(
                "INSERT INTO app_config (key, value, updated_at) "
                "VALUES (:k, :v, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"k": key, "v": json.dumps(names, ensure_ascii=False)},
        )
    await db.commit()
    return {
        "ok": True,
        "operation": "set_config",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "excluded_department_names": excl_dep,
        "excluded_category_names": cat_names,
        "seasonal_department_names": seasonal_dep,
    }
