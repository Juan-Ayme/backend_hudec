"""Endpoints de productos y variantes.

Usa la vista `v_products_full` que aplica override por producto:
- Si products.subcategory_id está seteado, usa ese
- Si no, hereda del product_type (BSale)
"""

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products(
    q: str | None = Query(
        None,
        description="Busqueda por nombre, bsale_product_id (numerico exacto) "
                    "o SKU/code de cualquier variante (ILIKE).",
    ),
    department: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    mapped_only: bool = False,
    override_only: bool = Query(
        False, description="Solo productos con override individual de subcategoría."
    ),
    unmapped_only: bool = Query(
        False, description="Solo productos cuya clasificación final está sin asignar."
    ),
    product_type_id: int | None = Query(
        None, description="Filtra por bsale_product_type_id (útil para drill-down desde huérfanos)."
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
) -> dict:
    where = []
    params = {}

    if q:
        # Busqueda inteligente: nombre, ID exacto si es numerico, SKU de variante.
        clauses = ["v.product_name ILIKE :q"]
        params["q"] = f"%{q}%"
        if q.strip().isdigit():
            clauses.append("v.bsale_product_id = :qid")
            params["qid"] = int(q.strip())
        clauses.append("""EXISTS (
            SELECT 1 FROM variants va
             WHERE va.bsale_product_id = v.bsale_product_id
               AND va.code ILIKE :q
        )""")
        where.append("(" + " OR ".join(clauses) + ")")

    if department:
        where.append("v.department = :department")
        params["department"] = department
    if category:
        where.append("v.category = :category")
        params["category"] = category
    if subcategory:
        where.append("v.subcategory = :subcategory")
        params["subcategory"] = subcategory
    if mapped_only:
        where.append("v.is_mapped = TRUE")
    if override_only:
        where.append("v.has_override = TRUE")
    if unmapped_only:
        where.append("v.subcategory IS NULL")
    if product_type_id is not None:
        where.append("v.bsale_product_type_id = :product_type_id")
        params["product_type_id"] = product_type_id

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql_count = f"""
        SELECT COUNT(*)
        FROM v_products_full v
        {where_sql}
    """
    res_total = await db.execute(text(sql_count), params)
    total = res_total.scalar() or 0

    # Concatenamos hasta 3 SKUs/codes por producto para mostrarlos en el listado
    # sin necesidad de un endpoint extra. STRING_AGG con LIMIT via subquery.
    params["limit"] = limit
    params["offset"] = offset
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
        LIMIT :limit OFFSET :offset
    """
    res = await db.execute(text(sql), params)
    rows = [dict(r) for r in res.mappings().all()]
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows,
    }


@router.get("/{product_id}")
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    res_prod = await db.execute(text("""
        SELECT v.bsale_product_id, v.product_name AS name, v.is_active,
               v.bsale_product_type_id, v.product_type_name,
               v.subcategory, v.category, v.department, v.has_override
        FROM v_products_full v
        WHERE v.bsale_product_id = :product_id
    """), {"product_id": product_id})
    prod_row = res_prod.mappings().first()
    
    if not prod_row:
        raise HTTPException(404, "Producto no encontrado")
        
    prod = dict(prod_row)

    res_var = await db.execute(text("""
        SELECT va.bsale_variant_id, va.code, va.description,
               vc.effective_cost, vc.average_cost, vc.latest_cost, vc.cost_source
        FROM variants va
        LEFT JOIN variant_costs vc
               ON vc.bsale_variant_id = va.bsale_variant_id
        WHERE va.bsale_product_id = :product_id
        ORDER BY va.bsale_variant_id
    """), {"product_id": product_id})
    prod["variantes"] = [dict(r) for r in res_var.mappings().all()]

    # Stock por sucursal
    res_stock = await db.execute(text("""
        SELECT o.name AS sucursal, SUM(sl.quantity_available) AS unidades
        FROM stock_levels sl
        JOIN offices o  ON o.bsale_office_id = sl.bsale_office_id
        JOIN variants v ON v.bsale_variant_id = sl.bsale_variant_id
        WHERE v.bsale_product_id = :product_id
        GROUP BY o.name
        ORDER BY o.name
    """), {"product_id": product_id})
    prod["stock_por_sucursal"] = [dict(r) for r in res_stock.mappings().all()]

    return prod


@router.patch("/{product_id}/subcategory")
async def set_product_subcategory(product_id: int, subcategory_id: int | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Override individual: asigna una subcategoría específica a UN producto.
    Si subcategory_id es null, se elimina el override y vuelve a heredar del product_type.

    Uso:
        PATCH /products/3355/subcategory?subcategory_id=2634
        PATCH /products/3355/subcategory                       (elimina override)
    """
    # Validar que el producto exista
    res_exists = await db.execute(text("SELECT 1 FROM products WHERE bsale_product_id = :product_id"), {"product_id": product_id})
    exists = res_exists.scalar()
    if not exists:
        raise HTTPException(404, f"Producto {product_id} no existe")

    # Validar subcategoría si se provee
    if subcategory_id is not None:
        res_subcat = await db.execute(text("SELECT id, name FROM subcategories WHERE id = :subcategory_id"), {"subcategory_id": subcategory_id})
        subcat = res_subcat.mappings().first()
        if not subcat:
            raise HTTPException(404, f"Subcategoria {subcategory_id} no existe")

    await db.execute(text(
        "UPDATE products SET subcategory_id = :subcategory_id WHERE bsale_product_id = :product_id"
    ), {"subcategory_id": subcategory_id, "product_id": product_id})
    await db.commit()

    res_entity = await db.execute(text("""
        SELECT bsale_product_id, product_name AS name,
               department, category, subcategory, has_override
        FROM v_products_full
        WHERE bsale_product_id = :product_id
    """), {"product_id": product_id})
    return dict(res_entity.mappings().first())


@router.get("/stats/summary")
async def products_summary(db: AsyncSession = Depends(get_db)) -> dict:
    """Resumen global."""
    res_tot_prod = await db.execute(text("SELECT COUNT(*) FROM products"))
    res_tot_var = await db.execute(text("SELECT COUNT(*) FROM variants"))
    res_pt_tot = await db.execute(text("SELECT COUNT(*) FROM product_types"))
    res_pt_map = await db.execute(text("SELECT COUNT(*) FROM product_types WHERE is_mapped = TRUE"))
    res_pt_unmap = await db.execute(text("SELECT COUNT(*) FROM product_types WHERE is_mapped = FALSE"))
    res_prod_over = await db.execute(text("SELECT COUNT(*) FROM products WHERE subcategory_id IS NOT NULL"))
    
    res_huerfanos = await db.execute(text("""
            SELECT pt.bsale_product_type_id AS id, pt.name,
                   COUNT(p.bsale_product_id) AS productos
            FROM product_types pt
            LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
            WHERE NOT pt.is_mapped
              AND p.subcategory_id IS NULL
            GROUP BY 1, 2
            HAVING COUNT(p.bsale_product_id) > 0
            ORDER BY 3 DESC
        """))
    
    return {
        "total_productos":             res_tot_prod.scalar() or 0,
        "total_variantes":             res_tot_var.scalar() or 0,
        "product_types_total":         res_pt_tot.scalar() or 0,
        "product_types_mapeados":      res_pt_map.scalar() or 0,
        "product_types_sin_mapear":    res_pt_unmap.scalar() or 0,
        "productos_con_override":      res_prod_over.scalar() or 0,
        "productos_huerfanos":         [dict(r) for r in res_huerfanos.mappings().all()]
    }
