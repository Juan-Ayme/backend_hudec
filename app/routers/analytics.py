"""Endpoints analiticos: KPIs, ventas por dimension, rankings.

Solo considera las sucursales activas (configurables en
analytics_scripts/config.py via OFFICE_IDS). Se aplica el mismo filtro
que en los scripts de analytics avanzado para mantener consistencia.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Query

from analytics_scripts.config import OFFICE_IDS
from app.database import fetch_all, fetch_scalar

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Clausulas SQL reutilizables para filtrar por sucursales activas.
# _DOC: cuando hay alias 'doc'   |   _PLAIN: cuando no hay alias.
_OFFICE_IDS_SQL  = ", ".join(str(i) for i in OFFICE_IDS)
_OFFICE_FILTER_DOC   = f"doc.bsale_office_id IN ({_OFFICE_IDS_SQL})"
_OFFICE_FILTER_PLAIN = f"bsale_office_id IN ({_OFFICE_IDS_SQL})"


def _default_range(days: int) -> tuple[date, date]:
    """Rango de fechas: ultimos N dias (hoy incluido).
    
    days=7 → desde hace 6 dias hasta fin de hoy = 7 dias exactos.
    Esto coincide con como BSale interpreta "ultimos 7 dias".
    """
    today = date.today()
    return today - timedelta(days=days - 1), today + timedelta(days=1)


@router.get("/kpis")
def kpis(days: int = Query(30, ge=1, le=365)) -> dict:
    """Tarjetas del dashboard.

    Ventas se calculan desde doc.total_amount (no desde detalles) para
    coincidir exactamente con lo que reporta BSale en su interfaz.
    El ticket promedio excluye documentos con total_amount = 0.
    """
    dfrom, dto = _default_range(days)

    # Ventas totales — desde la cabecera del documento (mas preciso)
    ventas = fetch_scalar(f"""
        SELECT COALESCE(SUM(total_amount), 0)
        FROM documents
        WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
    """, (dfrom, dto)) or 0

    # Tickets totales (excluyendo notas de credito)
    tickets = fetch_scalar(f"""
        SELECT COUNT(*)
        FROM documents
        WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
    """, (dfrom, dto)) or 0

    # Tickets con monto > 0 para ticket promedio real
    tickets_con_monto = fetch_scalar(f"""
        SELECT COUNT(*)
        FROM documents
        WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND total_amount > 0
          AND {_OFFICE_FILTER_PLAIN}
    """, (dfrom, dto)) or 0

    prod_tot = fetch_scalar("SELECT COUNT(*) FROM products") or 0
    # Producto "mapeado" = ubicado en un departamento (ya sea via product_type o via override)
    prod_mapeados = fetch_scalar("""
        SELECT COUNT(*) FROM v_products_full WHERE department IS NOT NULL
    """) or 0

    variantes = fetch_scalar("SELECT COUNT(*) FROM variants") or 0

    stock_valor = fetch_scalar("""
        SELECT COALESCE(SUM(sl.quantity_available * COALESCE(vc.effective_cost, 0)), 0)
        FROM stock_levels sl
        LEFT JOIN variant_costs vc ON vc.bsale_variant_id = sl.bsale_variant_id
        WHERE sl.quantity_available > 0
    """) or 0

    sucursales = fetch_scalar("SELECT COUNT(*) FROM offices") or 0

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
def sales_by_day(days: int = Query(30, ge=1, le=365)) -> list[dict]:
    dfrom, dto = _default_range(days)
    return fetch_all(f"""
        SELECT (emission_date AT TIME ZONE 'UTC')::DATE AS dia,
               ROUND(SUM(total_amount)::numeric, 2) AS ventas,
               COUNT(*) AS tickets,
               ROUND(AVG(CASE WHEN total_amount > 0 THEN total_amount END)::numeric, 2) AS ticket_promedio
        FROM documents
        WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_PLAIN}
        GROUP BY dia
        ORDER BY dia
    """, (dfrom, dto))


@router.get("/sales-by-department")
def sales_by_department(days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Ventas por departamento. Usa v_products_full (respeta override por producto)."""
    dfrom, dto = _default_range(days)
    return fetch_all(f"""
        SELECT vpf.department AS departamento,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets,
               ROUND(AVG(dd.total_amount)::numeric, 2) AS ticket_promedio_linea
        FROM document_details dd
        JOIN documents doc       ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v          ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id  = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (doc.emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department
        ORDER BY ventas DESC
    """, (dfrom, dto))


@router.get("/sales-by-category")
def sales_by_category(days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Ventas por categoría. Usa v_products_full (respeta override por producto)."""
    dfrom, dto = _default_range(days)
    return fetch_all(f"""
        SELECT vpf.department AS departamento, vpf.category AS categoria,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets
        FROM document_details dd
        JOIN documents doc       ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v          ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id  = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (doc.emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department, vpf.category
        ORDER BY ventas DESC
    """, (dfrom, dto))


@router.get("/top-products")
def top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=200),
) -> list[dict]:
    dfrom, dto = _default_range(days)
    return fetch_all(f"""
        SELECT p.bsale_product_id, p.name AS producto,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               SUM(dd.quantity) AS unidades
        FROM document_details dd
        JOIN documents doc ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants v    ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN products p    ON p.bsale_product_id    = v.bsale_product_id
        WHERE (doc.emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (doc.emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
        GROUP BY p.bsale_product_id, p.name
        ORDER BY ventas DESC
        LIMIT %s
    """, (dfrom, dto, limit))


@router.get("/sales-by-office")
def sales_by_office(days: int = Query(30, ge=1, le=365)) -> list[dict]:
    dfrom, dto = _default_range(days)
    return fetch_all(f"""
        SELECT o.name AS sucursal,
               ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
               COUNT(DISTINCT doc.bsale_document_id)   AS tickets
        FROM document_details dd
        JOIN documents doc ON doc.bsale_document_id  = dd.bsale_document_id
        LEFT JOIN offices o ON o.bsale_office_id     = doc.bsale_office_id
        WHERE (doc.emission_date AT TIME ZONE 'UTC')::DATE >= %s AND (doc.emission_date AT TIME ZONE 'UTC')::DATE < %s
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND {_OFFICE_FILTER_DOC}
        GROUP BY o.name
        ORDER BY ventas DESC
    """, (dfrom, dto))
