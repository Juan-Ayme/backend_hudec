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

from fastapi import Depends, APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.database import get_db
from harvester import bsale_client


router = APIRouter(prefix="/audits", tags=["audits"])


# ---------------------------------------------------------------------------
# METADATA por tipo de issue — el frontend la consume para decir CLARAMENTE
# de qué lado del sistema viene el problema (BSale / BD local / Mixto), qué
# significa, y qué acción concreta lo resuelve. Cambiar acá basta para que el
# tooltip y los badges se actualicen en la UI sin tocar el frontend.
# ---------------------------------------------------------------------------
# source ∈ {"bsale", "local_db", "both"}:
#   - bsale     : el problema NACE en BSale (ERP). Para arreglarlo de raíz hay
#                 que tocar BSale, aunque el síntoma se vea acá.
#   - local_db  : el problema vive solo en TU base/taxonomía. BSale no sabe ni
#                 le importa. Se arregla 100% acá (página Taxonomía/Configuración).
#   - both      : involucra a los dos. El auto-fix de KAWII suele tocar ambos.
ISSUES_META: dict[str, dict] = {
    "naming_mismatches": {
        "source": "both",
        "where": "BSale (nombre actual) + BD local (nombre esperado)",
        "what": (
            "Hay product_types cuyo nombre en BSale NO sigue la convención "
            "'Categoría / Subcategoría' que define tu taxonomía local."
        ),
        "impact": (
            "Los reportes que parsean el nombre del PT pueden romper o caer en "
            "categorías equivocadas. La integración cross-sistema se desincroniza."
        ),
        "fix_hint": (
            "Usa el botón 'Corregir nombres' arriba: renombra en BSale por API "
            "y actualiza tu BD en una sola operación."
        ),
        "fix_link": None,
        "row_label": "PT en BSale",
    },
    "orphan_product_types_with_products": {
        "source": "local_db",
        "where": "BD local (mapeo de PT → subcategoría faltante)",
        "what": (
            "BSale tiene product_types con productos vendiéndose, pero tu BD no "
            "los ha mapeado a una subcategoría — por eso esos productos caen "
            "fuera de la taxonomía."
        ),
        "impact": (
            "Los productos asociados a esos PT NO aparecen en matrices/reportes "
            "agrupados por departamento."
        ),
        "fix_hint": (
            "Ve a la página Taxonomía → asigna cada uno a su subcategoría. "
            "Si el PT no debería usarse, desactívalo en BSale."
        ),
        "fix_link": "/taxonomia",
        "row_label": "PT en BSale",
    },
    "inactive_but_mapped": {
        "source": "bsale",
        "where": "BSale (PT marcado inactivo allá)",
        "what": (
            "Estos product_types están INACTIVOS en BSale pero tu BD todavía "
            "los tiene mapeados a una subcategoría."
        ),
        "impact": (
            "Confunde reportes históricos: el PT no recibe productos nuevos pero "
            "sigue contando en la jerarquía."
        ),
        "fix_hint": (
            "Decide: si fue desactivado a propósito, desmapéalo en tu BD. "
            "Si fue por error, reactívalo en BSale."
        ),
        "fix_link": None,
        "row_label": "PT inactivo en BSale",
    },
    "subcategories_without_product_type": {
        "source": "local_db",
        "where": "BD local (subcategoría sin product_type apuntando)",
        "what": (
            "Subcategorías que existen en TU taxonomía pero a las que ningún "
            "product_type de BSale apunta. BSale no enviará productos ahí."
        ),
        "impact": (
            "Subcategorías 'vacías' que ensucian dropdowns y reportes. Solo se "
            "llenan con overrides manuales de producto."
        ),
        "fix_hint": (
            "O creas un product_type en BSale que apunte a esta subcat, o la "
            "eliminas de tu taxonomía si ya no la usas."
        ),
        "fix_link": "/taxonomia",
        "row_label": "Subcategoría local",
    },
    "categories_without_subcategories": {
        "source": "local_db",
        "where": "BD local (taxonomía incompleta)",
        "what": "Categorías locales que no tienen ninguna subcategoría.",
        "impact": (
            "Incompletas → sus productos no pueden mapearse a un nivel SubCat. "
            "Causa filas '—' en reportes jerárquicos."
        ),
        "fix_hint": "Agrega subcategorías desde la página Taxonomía.",
        "fix_link": "/taxonomia",
        "row_label": "Categoría local",
    },
    "departments_without_categories": {
        "source": "local_db",
        "where": "BD local (taxonomía incompleta)",
        "what": "Departamentos locales sin ninguna categoría debajo.",
        "impact": "Ramas vacías del árbol — invisibles en reportes.",
        "fix_hint": "Agrega categorías desde la página Taxonomía.",
        "fix_link": "/taxonomia",
        "row_label": "Departamento local",
    },
    "duplicate_product_type_names": {
        "source": "bsale",
        "where": "BSale (varios PTs con el mismo nombre)",
        "what": (
            "BSale tiene más de un product_type con exactamente el mismo nombre. "
            "Los reportes y joins por nombre se vuelven ambiguos."
        ),
        "impact": (
            "Productos del mismo 'nombre' pueden venir de PTs distintos y "
            "duplicar/dispersar la información."
        ),
        "fix_hint": (
            "En BSale: renombra el duplicado o desactiva el que no se usa. "
            "Confirma luego con un sync."
        ),
        "fix_link": None,
        "row_label": "Nombre duplicado en BSale",
    },
    "products_without_classification": {
        "source": "both",
        "where": "BSale (productos) sin mapeo en BD local",
        "what": (
            "Productos de BSale cuyo product_type no está mapeado a ninguna "
            "subcategoría en tu taxonomía local — caen sin departamento."
        ),
        "impact": (
            "Estos SKUs no aparecen en matrices/Resumen ni en reportes por "
            "departamento. Quedan 'invisibles' para el análisis."
        ),
        "fix_hint": (
            "Mapea los PTs huérfanos (ver 'Tipos huérfanos con productos' arriba) "
            "desde la página Taxonomía."
        ),
        "fix_link": "/taxonomia",
        "row_label": "Producto BSale sin clasificar",
    },
}


# ---------------------------------------------------------------------------
# DETECCION (cada funcion recibe `db` como parametro)
# ---------------------------------------------------------------------------

async def _audit_naming_mismatches(db: AsyncSession) -> list[dict]:
    """product_types mapeados cuyo nombre != 'Categoria / Subcategoria'."""
    res = await db.execute(text("""
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
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_orphan_pts_with_products(db: AsyncSession) -> list[dict]:
    """product_types sin mapeo a subcategoria pero con productos asociados."""
    res = await db.execute(text("""
        SELECT pt.bsale_product_type_id AS id, pt.name,
               COUNT(p.bsale_product_id) AS productos
        FROM product_types pt
        LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
        WHERE NOT pt.is_mapped
        GROUP BY 1, 2
        HAVING COUNT(p.bsale_product_id) > 0
        ORDER BY 3 DESC
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_inactive_pts_mapped(db: AsyncSession) -> list[dict]:
    """product_types inactivos en BSale pero todavia mapeados."""
    res = await db.execute(text("""
        SELECT pt.bsale_product_type_id AS id, pt.name,
               s.name AS subcategory,
               c.name AS category, d.name AS department,
               (SELECT COUNT(*) FROM products p
                 WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS productos,
               pt.synced_at AS ultimo_sync
        FROM product_types pt
        LEFT JOIN subcategories s ON s.id = pt.subcategory_id
        LEFT JOIN categories    c ON c.id = s.category_id
        LEFT JOIN departments   d ON d.id = c.department_id
        WHERE pt.is_active = FALSE AND pt.is_mapped = TRUE
        ORDER BY pt.name
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_subs_without_pt(db: AsyncSession) -> list[dict]:
    """Subcategorias a las que no apunta ningun product_type.
    Productos de BSale nunca caeran ahi salvo via override individual.
    """
    res = await db.execute(text("""
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
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_cats_without_subs(db: AsyncSession) -> list[dict]:
    res = await db.execute(text("""
        SELECT c.id, c.name AS category, d.name AS department
        FROM categories c
        JOIN departments d ON d.id = c.department_id
        LEFT JOIN subcategories s ON s.category_id = c.id
        GROUP BY c.id, c.name, d.name
        HAVING COUNT(s.id) = 0
        ORDER BY d.name, c.name
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_depts_without_cats(db: AsyncSession) -> list[dict]:
    res = await db.execute(text("""
        SELECT d.id, d.name AS department
        FROM departments d
        LEFT JOIN categories c ON c.department_id = d.id
        GROUP BY d.id, d.name
        HAVING COUNT(c.id) = 0
        ORDER BY d.name
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_duplicate_pt_names(db: AsyncSession) -> list[dict]:
    res = await db.execute(text("""
        SELECT name, COUNT(*) AS count,
               ARRAY_AGG(bsale_product_type_id ORDER BY bsale_product_type_id) AS ids
        FROM product_types
        GROUP BY name
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, name
    """))
    return [dict(r) for r in res.mappings().all()]


async def _audit_products_without_classification(db: AsyncSession) -> int:
    """Cuantos productos no tienen department (ni via product_type ni via override)."""
    return await db.scalar(text("""
        SELECT COUNT(*) FROM v_products_full WHERE department IS NULL
    """)) or 0


async def _audit_products_without_classification_sample(
    db: AsyncSession, limit: int = 50,
) -> list[dict]:
    """Muestra (hasta `limit`) productos sin clasificar — incluye el PT de BSale
    que los referencia, para que el usuario sepa CUÁL mapeo crear."""
    res = await db.execute(text("""
        SELECT v.bsale_product_id AS id,
               v.product_name AS producto,
               v.bsale_product_type_id AS bsale_pt_id,
               pt.name AS bsale_pt_name,
               pt.is_active AS bsale_pt_active,
               pt.is_mapped AS local_mapped
          FROM v_products_full v
          LEFT JOIN product_types pt
            ON pt.bsale_product_type_id = v.bsale_product_type_id
         WHERE v.department IS NULL
         ORDER BY pt.name NULLS LAST, v.product_name
         LIMIT :lim
    """), {"lim": limit})
    return [dict(r) for r in res.mappings().all()]


# ---------------------------------------------------------------------------
# ENDPOINT PRINCIPAL
# ---------------------------------------------------------------------------

@router.get("")
async def run_audits(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Ejecuta todas las auditorias y devuelve un resumen estructurado.

    El frontend usa esto para mostrar tarjetas con conteos y, al expandir,
    la lista de items afectados.
    """
    naming      = await _audit_naming_mismatches(db)
    orphans     = await _audit_orphan_pts_with_products(db)
    inactive    = await _audit_inactive_pts_mapped(db)
    subs_empty  = await _audit_subs_without_pt(db)
    cats_empty  = await _audit_cats_without_subs(db)
    depts_empty = await _audit_depts_without_cats(db)
    dup         = await _audit_duplicate_pt_names(db)
    sin_clasif  = await _audit_products_without_classification(db)
    sin_clasif_sample = (
        await _audit_products_without_classification_sample(db)
        if sin_clasif > 0 else []
    )

    severity = "ok"
    if naming or orphans or inactive or dup or sin_clasif > 0:
        severity = "warning"
    if sin_clasif > 50 or len(orphans) > 10:
        severity = "critical"

    # Conteos agregados por LADO del sistema — el frontend los muestra como
    # KPIs para responder al ojo "¿dónde está el problema?" antes de detalles.
    side_counts = {"bsale": 0, "local_db": 0, "both": 0}
    for key, count in {
        "naming_mismatches":                  len(naming),
        "orphan_product_types_with_products": len(orphans),
        "inactive_but_mapped":                len(inactive),
        "subcategories_without_product_type": len(subs_empty),
        "categories_without_subcategories":   len(cats_empty),
        "departments_without_categories":     len(depts_empty),
        "duplicate_product_type_names":       len(dup),
        "products_without_classification":    sin_clasif,
    }.items():
        if count <= 0:
            continue
        src = ISSUES_META.get(key, {}).get("source", "both")
        side_counts[src] = side_counts.get(src, 0) + count

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "summary": {
            "naming_mismatches":                   len(naming),
            "orphan_product_types_with_products":  len(orphans),
            "inactive_but_mapped":                 len(inactive),
            "subcategories_without_product_type":  len(subs_empty),
            "categories_without_subcategories":    len(cats_empty),
            "departments_without_categories":      len(depts_empty),
            "duplicate_product_type_names":        len(dup),
            "products_without_classification":     sin_clasif,
        },
        "side_counts": side_counts,
        "meta": ISSUES_META,
        "issues": {
            "naming_mismatches":                   naming,
            "orphan_product_types_with_products":  orphans,
            "inactive_but_mapped":                 inactive,
            "subcategories_without_product_type":  subs_empty,
            "categories_without_subcategories":    cats_empty,
            "departments_without_categories":      depts_empty,
            "duplicate_product_type_names":        dup,
            "products_without_classification":     sin_clasif_sample,
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
async def fix_naming(
    body: FixNamingIn | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Renombra product_types en BSale + BD interna para que cumplan la convencion
    'Categoria / Subcategoria'.

    Devuelve un informe detallado: que cambio, cuales fallaron y por que.
    """
    payload    = body or FixNamingIn()
    candidates = await _audit_naming_mismatches(db)

    if payload.ids is not None:
        wanted     = set(payload.ids)
        candidates = [c for c in candidates if c["id"] in wanted]

    fixed:   list[dict] = []
    failed:  list[dict] = []
    skipped: list[dict] = []

    for c in candidates:
        pt_id    = c["id"]
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
            await db.execute(text("""
                UPDATE product_types
                   SET name = :name, synced_at = NOW()
                 WHERE bsale_product_type_id = :pt_id
            """), {"name": new_name, "pt_id": pt_id})
            await db.commit()
        except Exception as exc:
            await db.rollback()
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
            "fixed":      len(fixed),
            "failed":     len(failed),
            "skipped":    len(skipped),
        },
        "fixed":   fixed,
        "failed":  failed,
        "skipped": skipped,
        "scope": "bsale+internal" if not payload.dry_run else "noop",
    }


# ---------------------------------------------------------------------------
# AUTO-FIX: limpiar product_types huerfanos sin productos
# ---------------------------------------------------------------------------

@router.get("/orphans-without-products")
async def orphans_without_products(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """product_types sin mapeo y sin productos: candidatos seguros a borrar."""
    res = await db.execute(text("""
        SELECT pt.bsale_product_type_id AS id, pt.name, pt.is_active
        FROM product_types pt
        LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
        WHERE NOT pt.is_mapped
        GROUP BY pt.bsale_product_type_id, pt.name, pt.is_active
        HAVING COUNT(p.bsale_product_id) = 0
        ORDER BY pt.name
    """))
    return [dict(r) for r in res.mappings().all()]
