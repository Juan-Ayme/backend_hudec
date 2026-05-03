"""Endpoints de stock (niveles, valorizacion, historico)."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query

from app.database import fetch_all

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/levels")
def stock_levels(
    office_id: int | None = Query(None, description="Filtrar por sucursal BSale"),
    only_with_stock: bool = True,
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict]:
    where = []
    params: list = []
    if office_id:
        where.append("sl.bsale_office_id = %s")
        params.append(office_id)
    if only_with_stock:
        where.append("sl.quantity_available > 0")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT sl.bsale_variant_id, sl.bsale_office_id,
               o.name AS office_name, v.code AS variant_code,
               p.name AS product_name,
               sl.quantity_available, sl.quantity_reserved
        FROM stock_levels sl
        JOIN offices o          ON o.bsale_office_id = sl.bsale_office_id
        JOIN variants v         ON v.bsale_variant_id = sl.bsale_variant_id
        JOIN products p         ON p.bsale_product_id = v.bsale_product_id
        {where_sql}
        ORDER BY sl.quantity_available DESC
        LIMIT %s
    """
    return fetch_all(sql, tuple(params) + (limit,))


@router.get("/valuation")
def stock_valuation() -> dict:
    """Stock valorizado por sucursal (usa effective_cost)."""
    rows = fetch_all("""
        SELECT o.name AS sucursal,
               ROUND(SUM(sl.quantity_available * COALESCE(vc.effective_cost, 0))::numeric, 2) AS valor_soles,
               SUM(sl.quantity_available) AS unidades
        FROM stock_levels sl
        JOIN offices o              ON o.bsale_office_id  = sl.bsale_office_id
        LEFT JOIN variant_costs vc  ON vc.bsale_variant_id = sl.bsale_variant_id
        WHERE sl.quantity_available > 0
        GROUP BY o.name
        ORDER BY valor_soles DESC
    """)
    total = sum(float(r["valor_soles"] or 0) for r in rows)
    return {
        "total_soles": round(total, 2),
        "por_sucursal": [
            {
                "sucursal": r["sucursal"],
                "valor_soles": float(r["valor_soles"] or 0),
                "unidades": float(r["unidades"] or 0),
            }
            for r in rows
        ],
    }


@router.get("/top")
def stock_top(
    limit: int = Query(20, ge=1, le=200),
) -> list[dict]:
    """Variantes con MAYOR stock total sumando todas las sucursales."""
    return fetch_all("""
        SELECT v.bsale_variant_id, v.code, p.name AS producto,
               SUM(sl.quantity_available) AS unidades
        FROM stock_levels sl
        JOIN variants v  ON v.bsale_variant_id = sl.bsale_variant_id
        JOIN products p  ON p.bsale_product_id  = v.bsale_product_id
        GROUP BY v.bsale_variant_id, v.code, p.name
        HAVING SUM(sl.quantity_available) > 0
        ORDER BY unidades DESC
        LIMIT %s
    """, (limit,))


@router.get("/history")
def stock_history(
    days: int = Query(30, ge=1, le=365),
    variant_id: int | None = None,
) -> list[dict]:
    """Serie temporal del snapshot diario."""
    since = date.today() - timedelta(days=days)
    where = ["sh.snapshot_date >= %s"]
    params: list = [since]
    if variant_id:
        where.append("sh.bsale_variant_id = %s")
        params.append(variant_id)
    where_sql = "WHERE " + " AND ".join(where)

    return fetch_all(f"""
        SELECT sh.snapshot_date, o.name AS sucursal,
               SUM(sh.quantity_available) AS unidades
        FROM stock_history sh
        JOIN offices o ON o.bsale_office_id = sh.bsale_office_id
        {where_sql}
        GROUP BY sh.snapshot_date, o.name
        ORDER BY sh.snapshot_date, o.name
    """, tuple(params))
