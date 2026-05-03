"""
Endpoints de ADMINISTRACIÓN de taxonomía interna.

Cada operación devuelve un mini-informe JSON estandarizado:
{
    "ok": bool,
    "operation": "create_subcategory",
    "timestamp": "2026-04-25T01:30:00Z",
    "entity": {...},
    "report": {
        "rows_affected": int,
        "scope": "internal_db" | "bsale+internal",
        "warnings": []
    }
}

IMPORTANTE: Department / Category / Subcategory existen sólo en TU BD.
            BSale no tiene esos conceptos. Por eso estas operaciones
            NO tocan BSale (scope=internal_db).
"""

from datetime import datetime, timezone
import re
import unicodedata

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.database import fetch_all, fetch_one, fetch_scalar, get_conn

router = APIRouter(prefix="/taxonomy", tags=["taxonomy-admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convierte 'Hogar y Decoración' -> 'hogar-y-decoracion'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"[\s-]+", "-", text) or "sin-nombre"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report(operation: str, entity: dict | None, rows: int = 1,
            scope: str = "internal_db", warnings: list[str] | None = None) -> dict:
    """Construye un informe JSON estándar."""
    return {
        "ok": True,
        "operation": operation,
        "timestamp": _now(),
        "entity": entity,
        "report": {
            "rows_affected": rows,
            "scope": scope,
            "warnings": warnings or [],
        },
    }


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------

class DepartmentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class CategoryIn(BaseModel):
    department_id: int
    name: str = Field(..., min_length=1, max_length=120)


class SubcategoryIn(BaseModel):
    category_id: int
    name: str = Field(..., min_length=1, max_length=120)


class RenameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


# ---------------------------------------------------------------------------
# DEPARTMENTS
# ---------------------------------------------------------------------------

@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn) -> dict:
    existing = fetch_one("SELECT id FROM departments WHERE name = %s", (body.name,))
    if existing:
        raise HTTPException(409, f"Ya existe un departamento con nombre '{body.name}'")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO departments (name, slug) VALUES (%s, %s) RETURNING id",
            (body.name, _slugify(body.name)),
        )
        new_id = cur.fetchone()[0]

    entity = fetch_one("SELECT id, name, slug FROM departments WHERE id = %s", (new_id,))
    return _report("create_department", entity)


@router.patch("/departments/{dep_id}")
def rename_department(dep_id: int, body: RenameIn) -> dict:
    if not fetch_scalar("SELECT 1 FROM departments WHERE id = %s", (dep_id,)):
        raise HTTPException(404, f"Departamento {dep_id} no existe")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE departments SET name = %s, slug = %s WHERE id = %s",
            (body.name, _slugify(body.name), dep_id),
        )

    entity = fetch_one("SELECT id, name, slug FROM departments WHERE id = %s", (dep_id,))
    return _report("rename_department", entity)


@router.delete("/departments/{dep_id}")
def delete_department(dep_id: int, force: bool = False) -> dict:
    """
    Elimina un departamento. Sólo permite si no tiene categorías
    (a menos que force=true, lo cual hace cascada en mi BD pero NO en BSale).
    """
    dept = fetch_one("SELECT id, name FROM departments WHERE id = %s", (dep_id,))
    if not dept:
        raise HTTPException(404, f"Departamento {dep_id} no existe")

    n_cats = fetch_scalar("SELECT COUNT(*) FROM categories WHERE department_id = %s",
                          (dep_id,)) or 0
    warnings = []
    if n_cats > 0 and not force:
        raise HTTPException(
            409,
            f"Departamento '{dept['name']}' tiene {n_cats} categorias. "
            f"Use ?force=true para eliminar en cascada (los productos quedaran sin clasificar)."
        )
    if n_cats > 0:
        warnings.append(f"Cascada: se eliminaron {n_cats} categorias y sus subcategorias")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM departments WHERE id = %s", (dep_id,))

    return _report("delete_department", dept, warnings=warnings)


# ---------------------------------------------------------------------------
# CATEGORIES
# ---------------------------------------------------------------------------

@router.post("/categories", status_code=201)
def create_category(body: CategoryIn) -> dict:
    dept = fetch_one("SELECT id, name FROM departments WHERE id = %s",
                     (body.department_id,))
    if not dept:
        raise HTTPException(404, f"Departamento {body.department_id} no existe")

    existing = fetch_one(
        "SELECT id FROM categories WHERE department_id = %s AND name = %s",
        (body.department_id, body.name),
    )
    if existing:
        raise HTTPException(
            409,
            f"Ya existe una categoría '{body.name}' dentro del departamento '{dept['name']}'",
        )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO categories (department_id, name, slug)
               VALUES (%s, %s, %s) RETURNING id""",
            (body.department_id, body.name,
             _slugify(f"{dept['name']}-{body.name}")),
        )
        new_id = cur.fetchone()[0]

    entity = fetch_one("""
        SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
        FROM categories c JOIN departments d ON d.id = c.department_id
        WHERE c.id = %s
    """, (new_id,))
    return _report("create_category", entity)


@router.patch("/categories/{cat_id}")
def rename_category(cat_id: int, body: RenameIn) -> dict:
    cat = fetch_one("""
        SELECT c.id, c.department_id, d.name AS department_name
        FROM categories c JOIN departments d ON d.id = c.department_id
        WHERE c.id = %s
    """, (cat_id,))
    if not cat:
        raise HTTPException(404, f"Categoria {cat_id} no existe")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE categories SET name = %s, slug = %s WHERE id = %s",
            (body.name, _slugify(f"{cat['department_name']}-{body.name}"), cat_id),
        )

    entity = fetch_one("""
        SELECT c.id, c.name, c.slug, c.department_id, d.name AS department_name
        FROM categories c JOIN departments d ON d.id = c.department_id
        WHERE c.id = %s
    """, (cat_id,))
    return _report("rename_category", entity)


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, force: bool = False) -> dict:
    cat = fetch_one("SELECT id, name FROM categories WHERE id = %s", (cat_id,))
    if not cat:
        raise HTTPException(404, f"Categoria {cat_id} no existe")

    n_subs = fetch_scalar("SELECT COUNT(*) FROM subcategories WHERE category_id = %s",
                          (cat_id,)) or 0
    warnings = []
    if n_subs > 0 and not force:
        raise HTTPException(
            409,
            f"Categoria '{cat['name']}' tiene {n_subs} subcategorias. "
            f"Use ?force=true para eliminar en cascada."
        )
    if n_subs > 0:
        warnings.append(f"Cascada: se eliminaron {n_subs} subcategorias")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (cat_id,))

    return _report("delete_category", cat, warnings=warnings)


# ---------------------------------------------------------------------------
# CLEANUP: categorias vacias (sin productos ni historial)
# ---------------------------------------------------------------------------

# Query base para detectar categorias 100% vacias.
# Una categoria es 100% vacia cuando ningun camino la conecta a datos:
#   - Cero product_types (BSale) con subcategory_id apuntando a sus subcats
#   - Cero products con subcategory_id override apuntando a sus subcats
#   - Cero products clasificados via product_type -> subcat -> esta categoria
#   - Cero document_details (ventas) vinculados via cualquiera de los caminos
_SQL_AUDIT_EMPTY_CATEGORIES = """
WITH conteos AS (
  SELECT
    c.id   AS cat_id,
    c.name AS categoria,
    d.name AS departamento,
    (SELECT COUNT(*) FROM subcategories s
       WHERE s.category_id = c.id)                            AS n_subcats,
    (SELECT COUNT(*) FROM product_types pt
       JOIN subcategories s ON s.id = pt.subcategory_id
       WHERE s.category_id = c.id)                            AS n_product_types,
    (SELECT COUNT(*) FROM products p
       JOIN subcategories s ON s.id = p.subcategory_id
       WHERE s.category_id = c.id)                            AS n_prod_override,
    (SELECT COUNT(DISTINCT p.bsale_product_id)
       FROM products p
       JOIN product_types pt ON pt.bsale_product_type_id = p.bsale_product_type_id
       JOIN subcategories s  ON s.id = pt.subcategory_id
       WHERE s.category_id = c.id)                            AS n_prod_via_pt,
    (SELECT COUNT(*) FROM document_details dd
       JOIN variants v       ON v.bsale_variant_id = dd.bsale_variant_id
       JOIN products p       ON p.bsale_product_id = v.bsale_product_id
       LEFT JOIN product_types pt
              ON pt.bsale_product_type_id = p.bsale_product_type_id
       LEFT JOIN subcategories s_pt ON s_pt.id = pt.subcategory_id
       LEFT JOIN subcategories s_ov ON s_ov.id = p.subcategory_id
       WHERE s_pt.category_id = c.id OR s_ov.category_id = c.id)
                                                              AS n_ventas_total
  FROM categories c
  JOIN departments d ON d.id = c.department_id
)
SELECT *,
  CASE
    WHEN n_product_types = 0
     AND n_prod_override = 0
     AND n_prod_via_pt   = 0
     AND n_ventas_total  = 0
    THEN TRUE ELSE FALSE
  END AS puede_borrarse
FROM conteos
ORDER BY departamento, categoria
"""


@router.get("/categories/empty/audit")
def audit_empty_categories() -> dict:
    """
    Lista las categorias que NO tienen productos ni ventas historicas.

    Una categoria se considera 'vacia' cuando todos sus contadores estan en cero:
      - n_product_types  = 0  (ningun product_type BSale apunta a sus subcats)
      - n_prod_override  = 0  (ningun producto con override directo)
      - n_prod_via_pt    = 0  (ningun producto clasificado via product_type)
      - n_ventas_total   = 0  (ninguna venta historica vinculada)

    Pueden borrarse con DELETE /taxonomy/categories/empty (cleanup masivo)
    o individualmente con DELETE /taxonomy/categories/{cat_id}?force=true.
    """
    rows = fetch_all(_SQL_AUDIT_EMPTY_CATEGORIES)
    candidatos = [r for r in rows if r.get("puede_borrarse")]
    no_candidatos = [r for r in rows if not r.get("puede_borrarse")]

    return {
        "ok": True,
        "operation": "audit_empty_categories",
        "timestamp": _now(),
        "report": {
            "total_categorias":       len(rows),
            "candidatas_a_borrar":    len(candidatos),
            "categorias_con_datos":   len(no_candidatos),
            "scope":                  "internal_db",
        },
        "candidatas":      candidatos,
        "todas":           rows,
    }


@router.delete("/categories/empty")
def delete_empty_categories(
    confirm: bool = False,
    dry_run: bool = True,
) -> dict:
    """
    Elimina TODAS las categorias 100% vacias (sin productos ni ventas).

    SEGURIDAD:
      - Por defecto corre en dry_run (NO borra, solo lista).
      - Para borrar de verdad: ?dry_run=false&confirm=true
      - El borrado es en cascada via FK: subcategories(category_id) ON DELETE CASCADE.
      - product_types y products no se ven afectados (ninguno apunta a subcats vacias).

    Devuelve la lista de categorias eliminadas con sus contadores antes del borrado.
    """
    rows = fetch_all(_SQL_AUDIT_EMPTY_CATEGORIES)
    candidatas = [r for r in rows if r.get("puede_borrarse")]

    if not candidatas:
        return {
            "ok":        True,
            "operation": "delete_empty_categories",
            "timestamp": _now(),
            "report":    {"eliminadas": 0, "scope": "internal_db",
                          "message": "No hay categorias 100% vacias"},
            "candidatas": [],
        }

    if dry_run or not confirm:
        return {
            "ok":        True,
            "operation": "delete_empty_categories_DRY_RUN",
            "timestamp": _now(),
            "report": {
                "eliminadas":   0,
                "candidatas":   len(candidatas),
                "scope":        "internal_db",
                "message":      "DRY RUN — pasa ?dry_run=false&confirm=true para borrar",
            },
            "candidatas": candidatas,
        }

    # Borrado real (cascada via FK borra subcats vacias automaticamente)
    ids = [r["cat_id"] for r in candidatas]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM categories WHERE id = ANY(%s)",
            (ids,),
        )
        rows_affected = cur.rowcount

    return {
        "ok":        True,
        "operation": "delete_empty_categories",
        "timestamp": _now(),
        "report": {
            "eliminadas":      rows_affected,
            "scope":           "internal_db",
            "subcats_cascada": sum(int(r.get("n_subcats") or 0) for r in candidatas),
        },
        "eliminadas": candidatas,
    }


# ---------------------------------------------------------------------------
# SUBCATEGORIES
# ---------------------------------------------------------------------------

@router.post("/subcategories", status_code=201)
def create_subcategory(body: SubcategoryIn) -> dict:
    cat = fetch_one("""
        SELECT c.id, c.name AS cat_name, d.name AS dept_name
        FROM categories c JOIN departments d ON d.id = c.department_id
        WHERE c.id = %s
    """, (body.category_id,))
    if not cat:
        raise HTTPException(404, f"Categoria {body.category_id} no existe")

    existing = fetch_one(
        "SELECT id FROM subcategories WHERE category_id = %s AND name = %s",
        (body.category_id, body.name),
    )
    if existing:
        raise HTTPException(
            409,
            f"Ya existe la subcategoria '{body.name}' dentro de '{cat['cat_name']}'",
        )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO subcategories (category_id, name, slug)
               VALUES (%s, %s, %s) RETURNING id""",
            (body.category_id, body.name,
             _slugify(f"{cat['dept_name']}-{cat['cat_name']}-{body.name}")),
        )
        new_id = cur.fetchone()[0]

    entity = fetch_one("""
        SELECT s.id, s.name, s.slug, s.category_id,
               c.name AS category_name, d.name AS department_name
        FROM subcategories s
        JOIN categories c   ON c.id = s.category_id
        JOIN departments d  ON d.id = c.department_id
        WHERE s.id = %s
    """, (new_id,))
    return _report("create_subcategory", entity)


@router.patch("/subcategories/{sub_id}")
def rename_subcategory(sub_id: int, body: RenameIn) -> dict:
    sub = fetch_one("""
        SELECT s.id, c.name AS cat_name, d.name AS dept_name
        FROM subcategories s
        JOIN categories c  ON c.id = s.category_id
        JOIN departments d ON d.id = c.department_id
        WHERE s.id = %s
    """, (sub_id,))
    if not sub:
        raise HTTPException(404, f"Subcategoria {sub_id} no existe")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE subcategories SET name = %s, slug = %s WHERE id = %s",
            (body.name,
             _slugify(f"{sub['dept_name']}-{sub['cat_name']}-{body.name}"),
             sub_id),
        )

    entity = fetch_one("""
        SELECT s.id, s.name, s.slug, s.category_id,
               c.name AS category_name, d.name AS department_name
        FROM subcategories s
        JOIN categories c  ON c.id = s.category_id
        JOIN departments d ON d.id = c.department_id
        WHERE s.id = %s
    """, (sub_id,))
    return _report("rename_subcategory", entity)


@router.delete("/subcategories/{sub_id}")
def delete_subcategory(sub_id: int, force: bool = False) -> dict:
    sub = fetch_one("""
        SELECT s.id, s.name, c.name AS cat_name, d.name AS dept_name
        FROM subcategories s
        JOIN categories c  ON c.id = s.category_id
        JOIN departments d ON d.id = c.department_id
        WHERE s.id = %s
    """, (sub_id,))
    if not sub:
        raise HTTPException(404, f"Subcategoria {sub_id} no existe")

    # Cuántos product_types y productos individuales apuntan aquí
    n_pt = fetch_scalar(
        "SELECT COUNT(*) FROM product_types WHERE subcategory_id = %s", (sub_id,)
    ) or 0
    n_prods = fetch_scalar(
        "SELECT COUNT(*) FROM products WHERE subcategory_id = %s", (sub_id,)
    ) or 0
    refs = n_pt + n_prods
    warnings = []
    if refs > 0 and not force:
        raise HTTPException(
            409,
            f"Subcategoria '{sub['name']}' está referenciada por {n_pt} product_types "
            f"y {n_prods} productos (override). Use ?force=true (la FK pondrá NULL "
            f"en el lado override; los product_types quedaran sin mapear)."
        )
    if refs > 0:
        warnings.append(
            f"FK ON DELETE SET NULL: {n_prods} productos perderán su override "
            f"y {n_pt} product_types quedarán sin mapear"
        )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM subcategories WHERE id = %s", (sub_id,))

    return _report("delete_subcategory", sub, warnings=warnings)
