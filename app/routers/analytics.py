"""Endpoints analíticos: KPIs, ventas por dimensión, rankings.

Solo considera las sucursales activas.

FIX (2026-05-06): Corregido bug de zona horaria.
  Antes usábamos AT TIME ZONE 'UTC' para extraer fechas, lo que causaba que
  ventas emitidas después de las 19:00 hora Lima (UTC-5) aparecieran
  asignadas al día siguiente, sin coincidir con los reportes de BSale.

  Solución: todas las conversiones de timestamp a date ahora usan
  AT TIME ZONE 'America/Lima' para reflejar la hora local de Perú.
"""

from datetime import date, timedelta
from typing import Any

from fastapi import Depends, APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from analytics.core.config import OFFICE_IDS
from app.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])

_OFFICE_IDS_SQL  = ", ".join(str(i) for i in OFFICE_IDS)
_OFFICE_FILTER_DOC   = f"doc.bsale_office_id IN ({_OFFICE_IDS_SQL})"
_OFFICE_FILTER_PLAIN = f"bsale_office_id IN ({_OFFICE_IDS_SQL})"

# Zona horaria del negocio (Perú / Lima = UTC-5)
_TZ = "America/Lima"


def _default_range(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=days - 1), today + timedelta(days=1)


@router.get("/kpis")
async def kpis(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> dict:
    dfrom, dto = _default_range(days)

    ventas_q = f"""
        SELECT COALESCE(SUM(total_amount), 0)
        FROM documents
        WHERE (emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
    """
    ventas = await db.scalar(text(ventas_q), {"dfrom": dfrom, "dto": dto}) or 0

    tickets_q = f"""
        SELECT COUNT(*)
        FROM documents
        WHERE (emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
    """
    tickets = await db.scalar(text(tickets_q), {"dfrom": dfrom, "dto": dto}) or 0

    tickets_monto_q = f"""
        SELECT COUNT(*)
        FROM documents
        WHERE (emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND total_amount > 0
          AND {_OFFICE_FILTER_PLAIN}
    """
    tickets_con_monto = await db.scalar(text(tickets_monto_q), {"dfrom": dfrom, "dto": dto}) or 0

    prod_tot = await db.scalar(text("SELECT COUNT(*) FROM products")) or 0
    prod_mapeados = await db.scalar(text("SELECT COUNT(*) FROM v_products_full WHERE department IS NOT NULL")) or 0
    variantes = await db.scalar(text("SELECT COUNT(*) FROM variants")) or 0

    stock_valor_q = """
        SELECT COALESCE(SUM(sl.quantity_available * COALESCE(vc.effective_cost, 0)), 0)
        FROM stock_levels sl
        LEFT JOIN variant_costs vc ON vc.bsale_variant_id = sl.bsale_variant_id
        WHERE sl.quantity_available > 0
    """
    stock_valor = await db.scalar(text(stock_valor_q)) or 0
    sucursales = await db.scalar(text("SELECT COUNT(*) FROM offices")) or 0

    return {
        "periodo_dias": days,
        "ventas": float(ventas),
        "tickets": tickets,
        "tickets_con_monto": tickets_con_monto,
        "ticket_promedio": float(ventas) / tickets_con_monto if tickets_con_monto else 0.0,
        "productos_total": prod_tot,
        "productos_mapeados": prod_mapeados,
        "variantes_total": variantes,
        "stock_valorizado": float(stock_valor),
        "sucursales": sucursales,
    }


@router.get("/sales-by-day")
async def sales_by_day(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT (emission_date AT TIME ZONE '{_TZ}')::DATE AS dia,
               ROUND(SUM(total_amount)::numeric, 2) AS ventas,
               COUNT(*) AS tickets,
               ROUND(AVG(CASE WHEN total_amount > 0 THEN total_amount END)::numeric, 2) AS ticket_promedio
        FROM documents
        WHERE (emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
        GROUP BY dia
        ORDER BY dia
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto})
    return [dict(r) for r in res.mappings().all()]


@router.get("/sales-by-department")
async def sales_by_department(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT vpf.department AS departamento,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets,
               ROUND(AVG(dd.total_amount)::numeric, 2) AS ticket_promedio_linea
        FROM document_details dd
        JOIN documents doc       ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v          ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id  = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (doc.emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department
        ORDER BY ventas DESC
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto})
    return [dict(r) for r in res.mappings().all()]


@router.get("/sales-by-category")
async def sales_by_category(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT vpf.department AS departamento, vpf.category AS categoria,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets
        FROM document_details dd
        JOIN documents doc       ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v          ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id  = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (doc.emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department, vpf.category
        ORDER BY ventas DESC
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto})
    return [dict(r) for r in res.mappings().all()]


@router.get("/sales-by-subcategory")
async def sales_by_subcategory(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT vpf.department AS departamento, vpf.category AS categoria, vpf.subcategory AS subcategoria,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets
        FROM document_details dd
        JOIN documents doc       ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v          ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id  = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (doc.emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department, vpf.category, vpf.subcategory
        ORDER BY ventas DESC
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto})
    return [dict(r) for r in res.mappings().all()]


@router.get("/top-products")
async def top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
    ) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT p.bsale_product_id, p.name AS producto,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               SUM(dd.quantity) AS unidades
        FROM document_details dd
        JOIN documents doc ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v    ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN products p    ON p.bsale_product_id    = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (doc.emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
        GROUP BY p.bsale_product_id, p.name
        ORDER BY ventas DESC
        LIMIT :limit
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto, "limit": limit})
    return [dict(r) for r in res.mappings().all()]


@router.get("/sales-by-office")
async def sales_by_office(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> list[dict]:
    dfrom, dto = _default_range(days)
    query = f"""
        SELECT o.name AS sucursal,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets
        FROM document_details dd
        JOIN documents doc ON doc.bsale_document_id  = dd.bsale_document_id
        LEFT JOIN offices o ON o.bsale_office_id     = doc.bsale_office_id
        WHERE (doc.emission_date AT TIME ZONE '{_TZ}')::DATE >= :dfrom
          AND (doc.emission_date AT TIME ZONE '{_TZ}')::DATE < :dto
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
        GROUP BY o.name
        ORDER BY ventas DESC
    """
    res = await db.execute(text(query), {"dfrom": dfrom, "dto": dto})
    return [dict(r) for r in res.mappings().all()]
