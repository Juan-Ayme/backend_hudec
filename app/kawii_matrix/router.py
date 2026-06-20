"""
Endpoints REST para el sistema KAWII Matrix.

Tras el cleanup en cascada solo sobrevive el módulo **04b** (matriz 90d
jerárquica con totales en S/), que alimenta a `/reportes/tablero` (action-groups)
y `/reportes/diario` (action-groups + excel).
"""

import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.excel_executive import build_executive_workbook
from app.config import get_settings
from app.database import get_db
from app.kawii_matrix import service
from app.kawii_matrix.schemas import ActionGroupsResponse

# Metadatos que aparecen en la Portada del Excel.
_MODULE_META: dict[str, dict[str, str]] = {
    "04b": {
        "titulo": "Matriz 90d Jerárquica",
        "sql_file": "04b_matriz_90d_jerarquico.sql",
        "descripcion": (
            "Variante del módulo 04 con totales agregados por Subcategoría, "
            "Categoría y Departamento (en unidades y S/), más el % de "
            "participación del SKU en cada nivel."
        ),
    },
}


router = APIRouter(prefix="/matrix", tags=["matrix"])


# ─────────────────────────────────────────────────────────────────────────
# Grupos de acción (urgente_comprar, reponer, descatalogar, etc.)
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}/action-groups",
    response_model=ActionGroupsResponse,
    summary="Agrupa SKUs por acción de negocio (urgente/reponer/descatalogar/...)",
)
async def get_action_groups(
    module_id: str = Path(..., pattern="^04b$"),
    db: AsyncSession = Depends(get_db),
):
    """
    Agrupa las ~26 etiquetas en 7 grupos accionables:
      - **urgente_comprar**: QUIEBRE Alta Rotación, Lote vendido rápido
      - **reponer**: STOCK PREVIO, POTENCIAL ACTIVO, EXITOSO, LOTE AGOTADO RÁPIDO
      - **saludable**: ALTA/ACTIVA/SANA/MEDIA ROTACIÓN
      - **exceso**: EXCESO INVENTARIO
      - **liquidar**: BAJA ROT 45d, MUERTO con stock
      - **descatalogar**: MARGINAL, RESIDUO, HISTÓRICO
      - **evaluar**: NUEVO, EMERGENTE, ESCONDIDO, ALERTA VISUAL
    """
    try:
        return await service.get_action_groups(db, module_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Descarga del reporte como Excel (.xlsx) bien maquetado
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}/excel",
    summary="Descarga el reporte de la matriz como Excel (.xlsx) bien maquetado",
    response_class=StreamingResponse,
)
async def get_matrix_excel(
    module_id: str = Path(..., pattern="^04b$"),
    sucursal: str | None = Query(None, description="Filtro opcional por sucursal"),
    accion: str | None = Query(
        None,
        description=(
            "Filtro opcional por ACCIÓN de negocio (buckets separados por coma): "
            "urgente_comprar, reponer, saludable, exceso, liquidar, descatalogar, "
            "evaluar. Ej: 'urgente_comprar,reponer' para el reporte de Compra urgente."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera un Excel con layout ejecutivo (jerarquía DEPT→CAT→SUBCAT→SKU,
    cabecera naranja, sumas por nivel).

    Lo usa `/reportes/diario` para los botones "Compra urgente" y "Alertas de
    quiebre" — filtra por `accion` con los mismos buckets que `/action-groups`.
    """
    settings = get_settings()
    meta = _MODULE_META[module_id]

    try:
        started = datetime.now()
        result = await service.run_matrix(
            db,
            module_id,
            sucursal=sucursal,
            limit=None,  # exportamos TODO lo que matchea los filtros
            offset=0,
        )
        elapsed = (datetime.now() - started).total_seconds()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    titulo = meta["titulo"]

    # Filtro opcional por ACCIÓN de negocio (mismos buckets que /action-groups).
    accion_label_map = {
        "urgente_comprar": "Compra urgente",
        "reponer": "Reponer",
        "saludable": "Saludable",
        "exceso": "Exceso",
        "liquidar": "Liquidar",
        "descatalogar": "Descatalogar",
        "evaluar": "Evaluar",
        "otro": "Otro",
    }
    accion_label = None
    if accion:
        wanted = {a.strip() for a in accion.split(",") if a.strip()}
        invalid = wanted - set(service.ACTION_BUCKETS)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Acción(es) inválida(s): {', '.join(sorted(invalid))}. "
                       f"Válidas: {', '.join(service.ACTION_BUCKETS)}",
            )
        label_col = service.find_label_column(result["columns"])
        if not label_col:
            raise HTTPException(
                status_code=400,
                detail=f"El módulo {module_id} no tiene columna de clasificación; "
                       "no se puede filtrar por acción.",
            )
        result["rows"] = [
            r for r in result["rows"]
            if (not r.get("Nivel") or r["Nivel"] == "SKU")
            and service.classify_action(str(r.get(label_col) or "")) in wanted
        ]
        accion_label = " + ".join(
            accion_label_map[a] for a in service.ACTION_BUCKETS if a in wanted
        )
        titulo = f"{titulo} — {accion_label}"

    cols: list[str] = result["columns"]
    # Builders esperan rows como tuplas/listas (compat con cursor.fetchall);
    # convertimos cada dict a tupla en el orden de las columnas.
    rows_tuples = [tuple(row.get(c) for c in cols) for row in result["rows"]]

    wb = build_executive_workbook(
        cols=cols,
        rows=rows_tuples,
        modulo_id=module_id,
        titulo=titulo,
        sql_file=meta["sql_file"],
        descripcion=meta["descripcion"],
        classification_col=settings.CLASSIFICATION_LABEL,
        elapsed_seconds=elapsed,
        brand_name=settings.BRAND_NAME,
        sucursal=sucursal,
        accion_label=accion_label,
        periodo_dias=90,
    )

    # Serializar a bytes en memoria (no toca el filesystem)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    fecha = datetime.now().strftime("%Y-%m-%d")
    safe_title = titulo.replace("—", "-").replace("/", "_").replace(":", "").replace(" ", "_")
    filename = f"{module_id}_{safe_title}_{fecha}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Total-Rows": str(len(rows_tuples)),
        },
    )
