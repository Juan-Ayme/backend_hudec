"""
Servicio que ejecuta los SQL de las matrices de clasificación y aplica filtros.

Los SQL se cargan al iniciar y se cachean en memoria.
Las consultas SQL se ejecutan con parámetros de entorno cargados dinámicamente
y los nombres de las columnas se mapean según la configuración de marca.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings

# Ruta absoluta a la carpeta sql/
_SQL_DIR = Path(__file__).parent / "sql"

MATRIX_MAP = {
    "04":  "04_matriz_90d.sql",
    "04b": "04b_matriz_90d_jerarquico.sql",  # Matriz 90d + totales jerárquicos en S/
    "05":  "05_matriz_operativa.sql",
    "06":  "06_historico_productos.sql",
    "07":  "07_informe_consolidado.sql",
}


@lru_cache(maxsize=8)
def _load_sql(module_id: str) -> str:
    """Carga el SQL del módulo (cacheado en memoria)."""
    if module_id not in MATRIX_MAP:
        raise ValueError(f"Módulo desconocido: {module_id}. Opciones: {list(MATRIX_MAP)}")
    path = _SQL_DIR / MATRIX_MAP[module_id]
    if not path.exists():
        raise FileNotFoundError(f"SQL no encontrado: {path}")
    return path.read_text(encoding="utf-8")


def _get_query_params() -> dict:
    """Genera el diccionario de parámetros operacionales para el motor de base de datos."""
    from harvester.config import (
        OFFICES_TIENDA,
        TIPOS_VENTA,
        TIPOS_DEVOLUCION,
        EXCLUDED_DEPARTMENTS,
        EXCLUDED_CATEGORIES,
    )
    settings = get_settings()
    return {
        "sucursales_objetivo": OFFICES_TIENDA,
        "tipos_venta": TIPOS_VENTA,
        "tipos_devolucion": TIPOS_DEVOLUCION,
        "excluded_departments": EXCLUDED_DEPARTMENTS,
        "excluded_categories": EXCLUDED_CATEGORIES,
        "timezone": settings.TIMEZONE,
    }


async def _execute_query_to_dicts(db: AsyncSession, sql: str) -> tuple[list[str], list[dict]]:
    """Ejecuta una consulta SQL parametrizada y mapea sus columnas de clasificación dinámicamente."""
    settings = get_settings()
    params = _get_query_params()
    result = await db.execute(text(sql), params)
    
    raw_columns = list(result.keys())
    columns = [settings.CLASSIFICATION_LABEL if col == "Clasificación" else col for col in raw_columns]
    raw_rows = result.fetchall()
    
    rows: list[dict] = []
    for row in raw_rows:
        row_dict = {}
        for col_name, val in zip(raw_columns, row):
            target_col = settings.CLASSIFICATION_LABEL if col_name == "Clasificación" else col_name
            row_dict[target_col] = val
        rows.append(row_dict)
        
    return columns, rows


async def run_matrix(
    db: AsyncSession,
    module_id: str,
    *,
    sucursal: str | None = None,
    departamento: str | None = None,
    categoria: str | None = None,
    subcategoria: str | None = None,
    sku: str | None = None,
    clasificacion_contains: str | None = None,
    nivel: str | None = None,         # Solo aplica al 07 (DEPARTAMENTO/CATEGORÍA/SUBCATEGORÍA/SKU)
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Ejecuta una matriz y aplica filtros post-query.

    Returns:
        {
            "module": "04",
            "total": int,       # filas tras filtros
            "limit": int | None,
            "offset": int,
            "columns": list[str],
            "rows": list[dict],
        }
    """
    sql = _load_sql(module_id)
    columns, all_rows = await _execute_query_to_dicts(db, sql)
    settings = get_settings()

    # ---- Filtros (case-insensitive containment para texto) ----
    def _match(row: dict, col: str, value: str | None, exact: bool = False) -> bool:
        if value is None:
            return True
        cell = row.get(col)
        if cell is None:
            return False
        cell_s = str(cell).strip()
        val_s = value.strip()
        if exact:
            return cell_s.casefold() == val_s.casefold()
        return val_s.casefold() in cell_s.casefold()

    filtered = []
    for row in all_rows:
        if not _match(row, "Sucursal", sucursal):
            continue
        if not _match(row, "Departamento", departamento):
            continue
        if not _match(row, "Categoría", categoria):
            continue
        if not _match(row, "Subcategoría", subcategoria):
            continue
        if sku is not None and not _match(row, "Código SKU", sku, exact=True):
            continue
        # Clasificación: puede llamarse mediante CLASSIFICATION_LABEL, "Prioridad / Recomendación",
        # "Diagnóstico Ciclo Vida" o "Diagnóstico" según el módulo. Buscamos en cualquiera.
        if clasificacion_contains is not None:
            label_cols = [
                settings.CLASSIFICATION_LABEL,
                "Prioridad / Recomendación",
                "Diagnóstico",
                "Diagnóstico Ciclo Vida",
            ]
            found = False
            for lc in label_cols:
                if lc in row and row[lc] and clasificacion_contains.casefold() in str(row[lc]).casefold():
                    found = True
                    break
            if not found:
                continue
        if nivel is not None and "Nivel" in row:
            if not _match(row, "Nivel", nivel, exact=True):
                continue
        filtered.append(row)

    total = len(filtered)

    if limit is not None:
        filtered = filtered[offset : offset + limit]
    elif offset > 0:
        filtered = filtered[offset:]

    return {
        "module": module_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "columns": columns,
        "rows": filtered,
    }


async def get_distribution(
    db: AsyncSession,
    module_id: str,
    *,
    sucursal: str | None = None,
) -> dict[str, Any]:
    """
    Devuelve la distribución de clasificaciones de un módulo.
    Útil para dashboards: cuántos productos en cada categoría.
    """
    sql = _load_sql(module_id)
    columns, rows = await _execute_query_to_dicts(db, sql)
    settings = get_settings()

    # Detectar columna de clasificación (varía por módulo)
    label_col = None
    for candidate in [
        settings.CLASSIFICATION_LABEL,
        "Prioridad / Recomendación",
        "Diagnóstico Ciclo Vida",
    ]:
        if candidate in columns:
            label_col = candidate
            break
    if not label_col:
        raise RuntimeError(f"No se encontró columna de clasificación en módulo {module_id}")

    if sucursal:
        rows = [r for r in rows if r.get("Sucursal") and sucursal.casefold() in str(r["Sucursal"]).casefold()]

    counts: dict[str, int] = {}
    for r in rows:
        label = str(r.get(label_col) or "(sin)")
        counts[label] = counts.get(label, 0) + 1

    items = [{"label": k, "count": v} for k, v in counts.items()]
    items.sort(key=lambda x: -x["count"])
    return {
        "module": module_id,
        "label_column": label_col,
        "sucursal_filter": sucursal,
        "total_skus": sum(c["count"] for c in items),
        "categories": items,
    }


async def get_transfers(db: AsyncSession, module_id: str = "04") -> dict[str, Any]:
    """
    Devuelve solo los productos con sugerencia de transferencia inter-sucursal.
    Solo aplica a módulos 04 y 05 que tienen esta columna.
    """
    if module_id not in ("04", "05"):
        raise ValueError("Sugerencia Transferencia solo disponible en módulos 04 y 05")

    sql = _load_sql(module_id)
    columns, rows = await _execute_query_to_dicts(db, sql)
    if "Sugerencia Transferencia" not in columns:
        raise RuntimeError(f"Módulo {module_id} no tiene columna 'Sugerencia Transferencia'")

    transfers = [
        r for r in rows
        if r.get("Sugerencia Transferencia") and "Transferir" in str(r["Sugerencia Transferencia"])
    ]
    return {
        "module": module_id,
        "total": len(transfers),
        "transfers": transfers,
    }


async def get_action_groups(db: AsyncSession, module_id: str = "04") -> dict[str, Any]:
    """
    Agrupa SKUs por ACCIÓN de negocio (no por etiqueta exacta).
    Útil para el dashboard ejecutivo.
    """
    sql = _load_sql(module_id)
    columns, rows = await _execute_query_to_dicts(db, sql)
    settings = get_settings()

    label_col = None
    for c in [settings.CLASSIFICATION_LABEL, "Prioridad / Recomendación", "Diagnóstico Ciclo Vida"]:
        if c in columns:
            label_col = c
            break
    if not label_col:
        raise RuntimeError(f"No se encontró columna de clasificación en módulo {module_id}")

    groups = {
        "urgente_comprar": [],
        "reponer": [],
        "saludable": [],
        "exceso": [],
        "liquidar": [],
        "descatalogar": [],
        "evaluar": [],
        "otro": [],
    }

    for r in rows:
        # Solo SKUs (no rollups del módulo 07)
        if r.get("Nivel") and r["Nivel"] != "SKU":
            continue
        label = str(r.get(label_col) or "")
        L = label.upper()

        if "QUIEBRE" in L and "ALTA" in L:
            groups["urgente_comprar"].append(r)
        elif "URGENTE" in L:
            groups["urgente_comprar"].append(r)
        elif any(k in L for k in ("STOCK PREVIO", "POTENCIAL ACTIVO", "EXITOSO", "LOTE AGOTADO RÁPIDO")):
            groups["reponer"].append(r)
        elif any(k in L for k in ("ALTA ROTACIÓN", "ROTACIÓN ACTIVA", "INVENTARIO SANO", "MEDIA ROTACIÓN")):
            groups["saludable"].append(r)
        elif "EXCESO" in L:
            groups["exceso"].append(r)
        elif "MUERTO" in L or "BAJA ROT" in L:
            groups["liquidar"].append(r)
        elif any(k in L for k in ("MARGINAL", "RESIDUO", "HISTÓRICO", "FRACASO", "RECIBIDO")):
            groups["descatalogar"].append(r)
        elif any(k in L for k in ("NUEVO", "EMERGENTE", "ESCONDIDO", "ALERTA VISUAL")):
            groups["evaluar"].append(r)
        else:
            groups["otro"].append(r)

    return {
        "module": module_id,
        "label_column": label_col,
        "summary": {k: len(v) for k, v in groups.items()},
        "groups": groups,
    }


async def get_summary(db: AsyncSession) -> dict[str, Any]:
    """
    Resumen ejecutivo combinando los 3 módulos operativos (04, 05, 07).
    Útil para mostrar en una tarjeta del dashboard.
    """
    sql = _load_sql("04")
    columns, rows = await _execute_query_to_dicts(db, sql)
    settings = get_settings()

    by_branch: dict[str, dict] = {}
    transfers_count = 0
    growing = 0
    declining = 0

    for r in rows:
        suc = str(r.get("Sucursal") or "—")
        if suc not in by_branch:
            by_branch[suc] = {
                "total_skus": 0,
                "urgente": 0,
                "reponer": 0,
                "saludable": 0,
                "descatalogar": 0,
                "exceso": 0,
            }
        b = by_branch[suc]
        b["total_skus"] += 1

        label = str(r.get(settings.CLASSIFICATION_LABEL) or "").upper()
        if "QUIEBRE" in label and "ALTA" in label:
            b["urgente"] += 1
        elif any(k in label for k in ("STOCK PREVIO", "POTENCIAL", "EXITOSO", "LOTE AGOTADO RÁPIDO")):
            b["reponer"] += 1
        elif any(k in label for k in ("ALTA ROTACIÓN", "ROTACIÓN ACTIVA", "SANO", "MEDIA")):
            b["saludable"] += 1
        elif "EXCESO" in label:
            b["exceso"] += 1
        elif any(k in label for k in ("MARGINAL", "RESIDUO", "HISTÓRICO")):
            b["descatalogar"] += 1

        # Transferencias y tendencia
        if r.get("Sugerencia Transferencia") and "Transferir" in str(r["Sugerencia Transferencia"]):
            transfers_count += 1
        tend = str(r.get("Tendencia") or "")
        if "Creciendo" in tend:
            growing += 1
        elif "Decayendo" in tend:
            declining += 1

    return {
        "total_skus": len(rows),
        "by_branch": by_branch,
        "transfers_sugeridas": transfers_count,
        "tendencia_creciendo": growing,
        "tendencia_decayendo": declining,
    }
