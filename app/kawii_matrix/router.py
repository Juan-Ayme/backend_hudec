"""
Endpoints REST para el sistema KAWII Matrix.

Expone las 4 matrices analíticas como JSON, con filtros, paginación,
agregaciones (distribución, grupos de acción) y vistas especializadas
(transferencias, resumen ejecutivo).
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.kawii_matrix import service
from app.kawii_matrix.schemas import (
    MatrixResponse,
    DistributionResponse,
    TransferResponse,
    ActionGroupsResponse,
    SummaryResponse,
)


router = APIRouter(prefix="/matrix", tags=["matrix"])


# ─────────────────────────────────────────────────────────────────────────
# Endpoint principal: ejecutar una matriz por su ID con filtros
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}",
    response_model=MatrixResponse,
    summary="Ejecuta una matriz KAWII y devuelve los SKUs clasificados",
)
async def get_matrix(
    module_id: str = Path(..., pattern="^(04|04b|05|06|07)$", description="ID del módulo"),
    sucursal: str | None = Query(None, description="Filtro: Magdalena, Asamblea"),
    departamento: str | None = Query(None, description="Filtro por nombre de departamento"),
    categoria: str | None = Query(None, description="Filtro por categoría"),
    subcategoria: str | None = Query(None, description="Filtro por subcategoría"),
    sku: str | None = Query(None, description="Filtro exacto por código SKU"),
    clasificacion_contains: str | None = Query(
        None,
        description="Filtra por texto contenido en la clasificación (ej: 'ALTA ROTACIÓN', 'EXITOSO')",
    ),
    nivel: str | None = Query(
        None,
        description="Solo módulo 07: filtrar por nivel jerárquico (DEPARTAMENTO/CATEGORÍA/SUBCATEGORÍA/SKU)",
    ),
    limit: int | None = Query(None, ge=1, le=10000, description="Máximo de filas a retornar"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    db: AsyncSession = Depends(get_db),
):
    """
    Módulos disponibles:
      - **04**: Matriz 90d (foto operativa — 90 días, vista por sucursal)
      - **04b**: Matriz 90d Jerárquica (+ totales en S/ por Subcat/Cat/Depto)
      - **05**: Matriz Operativa (90d + contexto lifetime + IC)
      - **06**: Histórico Productos (lifetime, autopsia de ciclo de vida)
      - **07**: Informe Consolidado (jerárquico DEPT→CAT→SUBCAT→SKU con ABC Pareto)
    """
    try:
        return await service.run_matrix(
            db,
            module_id,
            sucursal=sucursal,
            departamento=departamento,
            categoria=categoria,
            subcategoria=subcategoria,
            sku=sku,
            clasificacion_contains=clasificacion_contains,
            nivel=nivel,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Distribución por categoría
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}/distribution",
    response_model=DistributionResponse,
    summary="Distribución de SKUs por etiqueta de clasificación",
)
async def get_distribution(
    module_id: str = Path(..., pattern="^(04|04b|05|06|07)$"),
    sucursal: str | None = Query(None, description="Filtro opcional por sucursal"),
    db: AsyncSession = Depends(get_db),
):
    """
    Devuelve cuántos productos están en cada categoría.
    Útil para gráficos de pie/donut en el dashboard.
    """
    try:
        return await service.get_distribution(db, module_id, sucursal=sucursal)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Transferencias inter-sucursal
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}/transfers",
    response_model=TransferResponse,
    summary="Sugerencias de transferencia inter-sucursal (solo módulos 04 y 05)",
)
async def get_transfers(
    module_id: str = Path(..., pattern="^(04|04b|05)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    Detecta productos con EXCESO en una sucursal mientras la otra tiene DÉFICIT.
    Sugiere cantidad a transferir manteniendo 1 mes de stock al donante.
    """
    try:
        return await service.get_transfers(db, module_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Grupos de acción (urgente_comprar, reponer, descatalogar, etc.)
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/{module_id}/action-groups",
    response_model=ActionGroupsResponse,
    summary="Agrupa SKUs por acción de negocio (urgente/reponer/descatalogar/...)",
)
async def get_action_groups(
    module_id: str = Path(..., pattern="^(04|04b|05|06|07)$"),
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
# Resumen ejecutivo
# ─────────────────────────────────────────────────────────────────────────

@router.get(
    "/_/summary",
    response_model=SummaryResponse,
    summary="Resumen ejecutivo de los 2 sucursales (vista operativa 90d)",
)
async def get_summary(db: AsyncSession = Depends(get_db)):
    """
    Devuelve KPIs operativos:
      - Total SKUs activos por sucursal
      - Cuántos urgentes, reponer, saludables, descatalogar, exceso
      - Cantidad de transferencias inter-sucursal sugeridas
      - Productos creciendo vs decayendo en últimos 45d
    """
    return await service.get_summary(db)


# ─────────────────────────────────────────────────────────────────────────
# Lista de módulos disponibles
# ─────────────────────────────────────────────────────────────────────────

@router.get("/", summary="Lista los módulos disponibles")
async def list_modules():
    """Devuelve los IDs y descripciones de cada matriz."""
    return {
        "modules": [
            {
                "id": "04",
                "name": "Matriz 90d",
                "description": "Foto operativa del 'ahora' (ventana 90 días, por sucursal)",
                "endpoint": "/matrix/04",
            },
            {
                "id": "04b",
                "name": "Matriz 90d Jerárquica",
                "description": "Matriz 90d + totales en S/ por Subcategoría, Categoría y Departamento",
                "endpoint": "/matrix/04b",
            },
            {
                "id": "05",
                "name": "Matriz Operativa Enriquecida",
                "description": "Matriz 90d + contexto lifetime (Mejor Mes, IC, Sell-Through Lifetime)",
                "endpoint": "/matrix/05",
            },
            {
                "id": "06",
                "name": "Histórico Productos",
                "description": "Autopsia lifetime: ciclo de vida completo del SKU",
                "endpoint": "/matrix/06",
            },
            {
                "id": "07",
                "name": "Informe Consolidado",
                "description": "Vista jerárquica DEPT→CAT→SUBCAT→SKU con ABC Pareto",
                "endpoint": "/matrix/07",
            },
        ],
        "endpoints_especiales": {
            "summary": "/matrix/_/summary",
            "distribution": "/matrix/{module_id}/distribution",
            "transfers": "/matrix/{module_id}/transfers",
            "action_groups": "/matrix/{module_id}/action-groups",
        },
    }
