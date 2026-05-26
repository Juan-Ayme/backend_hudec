"""Endpoints de taxonomia: departamentos, categorias, subcategorias, arbol."""

from fastapi import Depends, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/tree")
async def get_tree(db: AsyncSession = Depends(get_db)) -> dict:
    """Arbol completo department -> category -> subcategory con conteo de productos."""
    query = """
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
    """
    res = await db.execute(text(query))
    rows = [dict(r) for r in res.mappings().all()]

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
async def list_departments(db: AsyncSession = Depends(get_db)) -> list[dict]:
    query = "SELECT id, name, slug FROM departments ORDER BY name"
    res = await db.execute(text(query))
    return [dict(r) for r in res.mappings().all()]


# GET /taxonomy/departments/{dep_id} eliminado — no consumido por el frontend


@router.get("/categories")
async def list_categories(department_id: int | None = None, db: AsyncSession = Depends(get_db)) -> list[dict]:
    if department_id:
        query = """SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
                   FROM categories c
                   JOIN departments d ON d.id = c.department_id
                   WHERE c.department_id = :department_id ORDER BY c.name"""
        res = await db.execute(text(query), {"department_id": department_id})
    else:
        query = """
            SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
            FROM categories c
            JOIN departments d ON d.id = c.department_id
            ORDER BY d.name, c.name
        """
        res = await db.execute(text(query))
    return [dict(r) for r in res.mappings().all()]


# GET /taxonomy/categories/{cat_id} eliminado — no consumido por el frontend


@router.get("/subcategories")
async def list_subcategories(category_id: int | None = None, db: AsyncSession = Depends(get_db)) -> list[dict]:
    if category_id:
        query = """SELECT id, name, slug, category_id 
                   FROM subcategories
                   WHERE category_id = :category_id ORDER BY name"""
        res = await db.execute(text(query), {"category_id": category_id})
    else:
        query = """
            SELECT s.id, s.name, s.slug, s.category_id,
                   c.name AS category_name, d.name AS department_name
            FROM subcategories s
            JOIN categories c    ON c.id = s.category_id
            JOIN departments d   ON d.id = c.department_id
            ORDER BY d.name, c.name, s.name
        """
        res = await db.execute(text(query))
    return [dict(r) for r in res.mappings().all()]
