"""
Endpoints de AUDITORIA del catalogo.

Detectan inconsistencias entre tu BD interna y BSale:

  - product_types con nombre que no cumple "Categoria / Subcategoria"
  - product_types huerfanos (sin subcategoria) que tienen productos
  - product_types inactivos pero con mapeo activo
  - subcategorias sin ningun product_type apuntando a ellas
  - categorias sin subcategorias
  - departamentos sin categorias
  - product_types con nombre duplicado (mismo name, distinto bsale_id)

Cada bloque devuelve la lista de filas afectadas + un conteo total,
asi el frontend puede mostrar tarjetas/contadores y permitir auto-fix.

Tambien expone POST /audits/fix-naming para renombrar en BSale + BD
todos los product_types mal nombrados (o un subset por ids).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import fetch_all, fetch_one, get_conn
from harvester import bsale_client


router = APIRouter(prefix="/audits", tags=["audits"])


# ---------------------------------------------------------------------------
# DETECCION
# ---------------------------------------------------------------------------

def _audit_naming_mismatches() -> list[dict]:
    """product_types mapeados cuyo nombre != 'Categoria / Subcategoria'."""
    return fetch_all("""
        SELECT pt.bsale_product_type_id AS id,
               pt.name AS current_name,
               c.name || ' / ' || s.name AS expected_name,
               s.name AS subcategory, c.name AS category, d.name AS department,
               pt.subcategory_id,
               (SELECT COUNT(*) FROM products p
                 WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS productos
        FROM product_types pt
        JOIN subcategories s ON s.id = pt.subcategory_id
        JOIN categories    c ON c.id = s.category_id
        JOIN departments   d ON d.id = c.department_id
        WHERE pt.is_mapped = TRUE
          AND pt.name <> c.name || ' / ' || s.name
        ORDER BY d.name, c.name, s.name
    """)


def _audit_orphan_pts_with_products() -> list[dict]:
    """product_types sin mapeo a subcategoria pero con productos asociados."""
    return fetch_all("""
        SELECT pt.bsale_product_type_id AS id, pt.name,
               COUNT(p.bsale_product_id) AS productos
        FROM product_types pt
        LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
        WHERE NOT pt.is_mapped
        GROUP BY 1, 2
        HAVING COUNT(p.bsale_product_id) > 0
        ORDER BY 3 DESC
    """)


def _audit_inactive_pts_mapped() -> list[dict]:
    """product_types inactivos en BSale pero todavia mapeados."""
    return fetch_all("""
        SELECT pt.bsale_product_type_id AS id, pt.name,
               s.name AS subcategory,
               (SELECT COUNT(*) FROM products p
                 WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS productos
        FROM product_types pt
        LEFT JOIN subcategories s ON s.id = pt.subcategory_id
        WHERE pt.is_active = FALSE AND pt.is_mapped = TRUE
        ORDER BY pt.name
    """)


def _audit_subs_without_pt() -> list[dict]:
    """Subcategorias a las que no apunta ningun product_type.
    Productos de BSale nunca caeran ahi salvo via override individual.
    """
    return fetch_all("""
        SELECT s.id, s.name AS subcategory,
               c.name AS category, d.name AS department,
               (SELECT COUNT(*) FROM products p WHERE p.subcategory_id = s.id)
                   AS productos_override
        FROM subcategories s
        JOIN categories    c ON c.id = s.category_id
        JOIN departments   d ON d.id = c.department_id
        LEFT JOIN product_types pt ON pt.subcategory_id = s.id
        WHERE pt.bsale_product_type_id IS NULL
        ORDER BY d.name, c.name, s.name
    """)


def _audit_cats_without_subs() -> list[dict]:
    return fetch_all("""
        SELECT c.id, c.name AS category, d.name AS department
        FROM categories c
        JOIN departments d ON d.id = c.department_id
        LEFT JOIN subcategories s ON s.category_id = c.id
        GROUP BY c.id, c.name, d.name
        HAVING COUNT(s.id) = 0
        ORDER BY d.name, c.name
    """)


def _audit_depts_without_cats() -> list[dict]:
    return fetch_all("""
        SELECT d.id, d.name AS department
        FROM departments d
        LEFT JOIN categories c ON c.department_id = d.id
        GROUP BY d.id, d.name
        HAVING COUNT(c.id) = 0
        ORDER BY d.name
    """)


def _audit_duplicate_pt_names() -> list[dict]:
    return fetch_all("""
        SELECT name, COUNT(*) AS count,
               ARRAY_AGG(bsale_product_type_id ORDER BY bsale_product_type_id) AS ids
        FROM product_types
        GROUP BY name
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, name
    """)


def _audit_products_without_classification() -> int:
    """Cuantos productos no tienen department (ni via product_type ni via override)."""
    from app.database import fetch_scalar
    return fetch_scalar("""
        SELECT COUNT(*) FROM v_products_full WHERE department IS NULL
    """) or 0


# ---------------------------------------------------------------------------
# ENDPOINT PRINCIPAL
# ---------------------------------------------------------------------------

@router.get("")
def run_audits() -> dict:
    """
    Ejecuta todas las auditorias y devuelve un resumen estructurado.

    El frontend usa esto para mostrar tarjetas con conteos y, al expandir,
    la lista de items afectados.
    """
    naming = _audit_naming_mismatches()
    orphans = _audit_orphan_pts_with_products()
    inactive = _audit_inactive_pts_mapped()
    subs_empty = _audit_subs_without_pt()
    cats_empty = _audit_cats_without_subs()
    depts_empty = _audit_depts_without_cats()
    dup = _audit_duplicate_pt_names()
    sin_clasif = _audit_products_without_classification()

    severity = "ok"
    if naming or orphans or inactive or dup or sin_clasif > 0:
        severity = "warning"
    if sin_clasif > 50 or len(orphans) > 10:
        severity = "critical"

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "summary": {
            "naming_mismatches": len(naming),
            "orphan_product_types_with_products": len(orphans),
            "inactive_but_mapped": len(inactive),
            "subcategories_without_product_type": len(subs_empty),
            "categories_without_subcategories": len(cats_empty),
            "departments_without_categories": len(depts_empty),
            "duplicate_product_type_names": len(dup),
            "products_without_classification": sin_clasif,
        },
        "issues": {
            "naming_mismatches": naming,
            "orphan_product_types_with_products": orphans,
            "inactive_but_mapped": inactive,
            "subcategories_without_product_type": subs_empty,
            "categories_without_subcategories": cats_empty,
            "departments_without_categories": depts_empty,
            "duplicate_product_type_names": dup,
        },
    }


# ---------------------------------------------------------------------------
# AUTO-FIX: nombres
# ---------------------------------------------------------------------------

class FixNamingIn(BaseModel):
    ids: list[int] | None = Field(
        None,
        description="Lista de bsale_product_type_id a renombrar. "
                    "Si es null, renombra TODOS los detectados.",
    )
    dry_run: bool = Field(
        False,
        description="Si es True, solo simula y devuelve la lista de cambios "
                    "sin tocar BSale ni la BD.",
    )


@router.post("/fix-naming")
def fix_naming(body: FixNamingIn | None = None) -> dict:
    """
    Renombra product_types en BSale + BD interna para que cumplan la convencion
    'Categoria / Subcategoria'.

    Devuelve un informe detallado: que cambio, cuales fallaron y por que.
    """
    payload = body or FixNamingIn()
    candidates = _audit_naming_mismatches()

    if payload.ids is not None:
        wanted = set(payload.ids)
        candidates = [c for c in candidates if c["id"] in wanted]

    fixed: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []

    for c in candidates:
        pt_id = c["id"]
        new_name = c["expected_name"]
        old_name = c["current_name"]

        if payload.dry_run:
            skipped.append({"id": pt_id, "from": old_name, "to": new_name,
                            "reason": "dry_run"})
            continue

        # 1) BSale
        try:
            bsale_client.put(f"product_types/{pt_id}.json", {"name": new_name})
        except Exception as exc:
            failed.append({"id": pt_id, "from": old_name, "to": new_name,
                           "step": "bsale", "error": str(exc)})
            continue

        # 2) BD interna
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE product_types
                       SET name = %s, synced_at = NOW()
                     WHERE bsale_product_type_id = %s
                    """,
                    (new_name, pt_id),
                )
        except Exception as exc:
            failed.append({"id": pt_id, "from": old_name, "to": new_name,
                           "step": "internal_db", "error": str(exc)})
            continue

        fixed.append({"id": pt_id, "from": old_name, "to": new_name})

    return {
        "ok": True,
        "operation": "fix_naming",
        "dry_run": payload.dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "candidates": len(candidates),
            "fixed": len(fixed),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "fixed": fixed,
        "failed": failed,
        "skipped": skipped,
        "scope": "bsale+internal" if not payload.dry_run else "noop",
    }


# ---------------------------------------------------------------------------
# AUTO-FIX: limpiar product_types huerfanos sin productos
# ---------------------------------------------------------------------------

@router.get("/orphans-without-products")
def orphans_without_products() -> list[dict]:
    """product_types sin mapeo y sin productos: candidatos seguros a borrar."""
    return fetch_all("""
        SELECT pt.bsale_product_type_id AS id, pt.name, pt.is_active
        FROM product_types pt
        LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
        WHERE NOT pt.is_mapped
        GROUP BY pt.bsale_product_type_id, pt.name, pt.is_active
        HAVING COUNT(p.bsale_product_id) = 0
        ORDER BY pt.name
    """)
