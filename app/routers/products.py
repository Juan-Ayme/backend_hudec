"""Endpoints de productos y variantes.

Usa la vista `v_products_full` que aplica override por producto:
- Si products.subcategory_id está seteado, usa ese
- Si no, hereda del product_type (BSale)
"""

from fastapi import APIRouter, HTTPException, Query

from app.database import fetch_all, fetch_one, fetch_scalar

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    q: str | None = Query(
        None,
        description="Busqueda por nombre, bsale_product_id (numerico exacto) "
                    "o SKU/code de cualquier variante (ILIKE).",
    ),
    department: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    mapped_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    where = []
    params: list = []

    if q:
        # Busqueda inteligente: nombre, ID exacto si es numerico, SKU de variante.
        clauses = ["v.product_name ILIKE %s"]
        sub_params: list = [f"%{q}%"]
        if q.strip().isdigit():
            clauses.append("v.bsale_product_id = %s")
            sub_params.append(int(q.strip()))
        clauses.append("""EXISTS (
            SELECT 1 FROM variants va
             WHERE va.bsale_product_id = v.bsale_product_id
               AND va.code ILIKE %s
        )""")
        sub_params.append(f"%{q}%")
        where.append("(" + " OR ".join(clauses) + ")")
        params.extend(sub_params)
    if department:
        where.append("v.department = %s")
        params.append(department)
    if category:
        where.append("v.category = %s")
        params.append(category)
    if subcategory:
        where.append("v.subcategory = %s")
        params.append(subcategory)
    if mapped_only:
        where.append("v.is_mapped = TRUE")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql_count = f"""
        SELECT COUNT(*)
        FROM v_products_full v
        {where_sql}
    """
    total = fetch_scalar(sql_count, tuple(params)) or 0

    # Concatenamos hasta 3 SKUs/codes por producto para mostrarlos en el listado
    # sin necesidad de un endpoint extra. STRING_AGG con LIMIT via subquery.
    sql = f"""
        SELECT v.bsale_product_id, v.product_name AS name, v.is_active,
               v.bsale_product_type_id, v.product_type_name,
               v.subcategory, v.category, v.department,
               v.has_override,
               (SELECT STRING_AGG(va.code, ', ' ORDER BY va.code)
                  FROM (
                       SELECT code FROM variants
                        WHERE bsale_product_id = v.bsale_product_id
                          AND code IS NOT NULL AND code <> ''
                        ORDER BY code
                        LIMIT 3
                  ) va
               ) AS skus,
               (SELECT COUNT(*) FROM variants
                 WHERE bsale_product_id = v.bsale_product_id) AS variantes_count
        FROM v_products_full v
        {where_sql}
        ORDER BY v.product_name
        LIMIT %s OFFSET %s
    """
    rows = fetch_all(sql, tuple(params) + (limit, offset))
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows,
    }


@router.get("/{product_id}")
def get_product(product_id: int) -> dict:
    prod = fetch_one("""
        SELECT v.bsale_product_id, v.product_name AS name, v.is_active,
               v.bsale_product_type_id, v.product_type_name,
               v.subcategory, v.category, v.department, v.has_override
        FROM v_products_full v
        WHERE v.bsale_product_id = %s
    """, (product_id,))
    if not prod:
        raise HTTPException(404, "Producto no encontrado")

    prod["variantes"] = fetch_all("""
        SELECT va.bsale_variant_id, va.code, va.description,
               vc.effective_cost, vc.average_cost, vc.latest_cost, vc.cost_source
        FROM variants va
        LEFT JOIN variant_costs vc
               ON vc.bsale_variant_id = va.bsale_variant_id
        WHERE va.bsale_product_id = %s
        ORDER BY va.bsale_variant_id
    """, (product_id,))

    # Stock por sucursal
    prod["stock_por_sucursal"] = fetch_all("""
        SELECT o.name AS sucursal, SUM(sl.quantity_available) AS unidades
        FROM stock_levels sl
        JOIN offices o  ON o.bsale_office_id = sl.bsale_office_id
        JOIN variants v ON v.bsale_variant_id = sl.bsale_variant_id
        WHERE v.bsale_product_id = %s
        GROUP BY o.name
        ORDER BY o.name
    """, (product_id,))

    return prod


@router.patch("/{product_id}/subcategory")
def set_product_subcategory(product_id: int, subcategory_id: int | None = None) -> dict:
    """
    Override individual: asigna una subcategoría específica a UN producto.
    Si subcategory_id es null, se elimina el override y vuelve a heredar del product_type.

    Uso:
        PATCH /products/3355/subcategory?subcategory_id=2634
        PATCH /products/3355/subcategory                       (elimina override)
    """
    # Validar que el producto exista
    exists = fetch_scalar(
        "SELECT 1 FROM products WHERE bsale_product_id = %s", (product_id,)
    )
    if not exists:
        raise HTTPException(404, f"Producto {product_id} no existe")

    # Validar subcategoría si se provee
    if subcategory_id is not None:
        subcat = fetch_one(
            "SELECT id, name FROM subcategories WHERE id = %s", (subcategory_id,)
        )
        if not subcat:
            raise HTTPException(404, f"Subcategoria {subcategory_id} no existe")

    from app.database import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE products SET subcategory_id = %s WHERE bsale_product_id = %s",
            (subcategory_id, product_id),
        )

    return fetch_one("""
        SELECT bsale_product_id, product_name AS name,
               department, category, subcategory, has_override
        FROM v_products_full
        WHERE bsale_product_id = %s
    """, (product_id,))


@router.get("/stats/summary")
def products_summary() -> dict:
    """Resumen global."""
    return {
        "total_productos":             fetch_scalar("SELECT COUNT(*) FROM products"),
        "total_variantes":             fetch_scalar("SELECT COUNT(*) FROM variants"),
        "product_types_total":         fetch_scalar("SELECT COUNT(*) FROM product_types"),
        "product_types_mapeados":      fetch_scalar(
            "SELECT COUNT(*) FROM product_types WHERE is_mapped = TRUE"
        ),
        "product_types_sin_mapear":    fetch_scalar(
            "SELECT COUNT(*) FROM product_types WHERE is_mapped = FALSE"
        ),
        "productos_con_override":      fetch_scalar(
            "SELECT COUNT(*) FROM products WHERE subcategory_id IS NOT NULL"
        ),
        "productos_huerfanos": fetch_all("""
            SELECT pt.bsale_product_type_id AS id, pt.name,
                   COUNT(p.bsale_product_id) AS productos
            FROM product_types pt
            LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
            WHERE NOT pt.is_mapped
              AND p.subcategory_id IS NULL
            GROUP BY 1, 2
            HAVING COUNT(p.bsale_product_id) > 0
            ORDER BY 3 DESC
        """),
    }
