"""Endpoints de taxonomia: departamentos, categorias, subcategorias, arbol."""

from fastapi import APIRouter, HTTPException

from app.database import fetch_all, fetch_one

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/tree")
def get_tree() -> dict:
    """Arbol completo department -> category -> subcategory con conteo de productos.

    El conteo cuenta cada producto considerando override individual:
    si products.subcategory_id está seteado, se usa ese; sino el del product_type.
    """
    # NOTA: v_products_full ya no expone subcategory_id como columna (solo el
    # texto subcategory). Calculamos el conteo desde las tablas base resolviendo
    # la subcategoria efectiva: override individual del producto si existe,
    # sino la del product_type.
    rows = fetch_all("""
        SELECT d.id   AS dep_id,   d.name   AS dep_name,
               c.id   AS cat_id,   c.name   AS cat_name,
               s.id   AS sub_id,   s.name   AS sub_name,
               (SELECT COUNT(*)
                  FROM products p
                  LEFT JOIN product_types pt
                         ON pt.bsale_product_type_id = p.bsale_product_type_id
                 WHERE COALESCE(p.subcategory_id, pt.subcategory_id) = s.id
               ) AS productos
        FROM departments d
        LEFT JOIN categories    c ON c.department_id = d.id
        LEFT JOIN subcategories s ON s.category_id   = c.id
        ORDER BY d.name, c.name, s.name
    """)
    tree: dict = {}
    for r in rows:
        dep = tree.setdefault(r["dep_name"], {"id": r["dep_id"], "categorias": {}})
        if r["cat_name"] is None:
            continue
        cat = dep["categorias"].setdefault(
            r["cat_name"], {"id": r["cat_id"], "subcategorias": []}
        )
        if r["sub_name"] is not None:
            cat["subcategorias"].append({
                "id": r["sub_id"],
                "nombre": r["sub_name"],
                "productos": r["productos"] or 0,
            })
    return {"arbol": tree}


@router.get("/departments")
def list_departments() -> list[dict]:
    return fetch_all(
        "SELECT id, name, slug FROM departments ORDER BY name"
    )


@router.get("/departments/{dep_id}")
def get_department(dep_id: int) -> dict:
    dep = fetch_one(
        "SELECT id, name, slug FROM departments WHERE id = %s", (dep_id,)
    )
    if not dep:
        raise HTTPException(404, "Departamento no encontrado")
    dep["categorias"] = fetch_all(
        "SELECT id, name, slug FROM categories WHERE department_id = %s ORDER BY name",
        (dep_id,),
    )
    return dep


@router.get("/categories")
def list_categories(department_id: int | None = None) -> list[dict]:
    if department_id:
        return fetch_all(
            """SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
               FROM categories c
               JOIN departments d ON d.id = c.department_id
               WHERE c.department_id = %s ORDER BY c.name""",
            (department_id,),
        )
    return fetch_all("""
        SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
        FROM categories c
        JOIN departments d ON d.id = c.department_id
        ORDER BY d.name, c.name
    """)


@router.get("/categories/{cat_id}")
def get_category(cat_id: int) -> dict:
    cat = fetch_one("""
        SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
        FROM categories c
        JOIN departments d ON d.id = c.department_id
        WHERE c.id = %s
    """, (cat_id,))
    if not cat:
        raise HTTPException(404, "Categoria no encontrada")
    cat["subcategorias"] = fetch_all(
        "SELECT id, name, slug FROM subcategories WHERE category_id = %s ORDER BY name",
        (cat_id,),
    )
    return cat


@router.get("/subcategories")
def list_subcategories(category_id: int | None = None) -> list[dict]:
    if category_id:
        return fetch_all(
            """SELECT id, name, slug, category_id FROM subcategories
               WHERE category_id = %s ORDER BY name""",
            (category_id,),
        )
    return fetch_all("""
        SELECT s.id, s.name, s.slug, s.category_id,
               c.name AS category_name, d.name AS department_name
        FROM subcategories s
        JOIN categories c    ON c.id = s.category_id
        JOIN departments d   ON d.id = c.department_id
        ORDER BY d.name, c.name, s.name
    """)
