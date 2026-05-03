"""
Limpieza de categorias huerfanas que no tienen productos ni historial de ventas.

Uso:
    cd produccion

    # 1. Listar candidatas (dry-run, default)
    python analytics_scripts/cleanup_empty_categories.py

    # 2. Aplicar borrado (cascada via FK borra subcats vacias automaticamente)
    python analytics_scripts/cleanup_empty_categories.py --apply

Una categoria se considera 100% vacia cuando:
  - Cero product_types (BSale) apuntando a sus subcategorias
  - Cero productos con override (subcategory_id) apuntando a sus subcategorias
  - Cero productos clasificados via product_type -> subcat -> esta categoria
  - Cero ventas historicas (document_details) vinculadas
  → es seguro borrarla porque no afecta a BSale ni al historial de ventas.
"""

from __future__ import annotations

import argparse
import io
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Path setup ──────────────────────────────────────────────────────────────────
_PRODUCCION = Path(__file__).resolve().parent.parent
if str(_PRODUCCION) not in sys.path:
    sys.path.insert(0, str(_PRODUCCION))

# Windows UTF-8 fix
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from analytics_scripts.db_helper import _get_conn  # noqa: E402


_SQL_AUDIT = """
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
    WHEN n_product_types = 0 AND n_prod_override = 0
     AND n_prod_via_pt   = 0 AND n_ventas_total = 0
    THEN TRUE ELSE FALSE
  END AS puede_borrarse
FROM conteos
ORDER BY departamento, categoria
"""


def _listar_categorias() -> list[dict]:
    """Devuelve la lista completa con contadores."""
    import psycopg2.extras
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SQL_AUDIT)
            return [dict(r) for r in cur.fetchall()]


def _borrar(ids: list[int]) -> int:
    """Elimina las categorias en cascada (subcats vacias se borran por FK)."""
    if not ids:
        return 0
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM categories WHERE id = ANY(%s)", (ids,))
            n = cur.rowcount
        conn.commit()
    return n


def _imprimir_tabla(rows: list[dict], titulo: str = "") -> None:
    if titulo:
        print(f"\n{titulo}")
        print("=" * 100)
    if not rows:
        print("  (ninguna)")
        return

    # Encabezado
    cols = ["cat_id", "departamento", "categoria",
            "n_subcats", "n_product_types", "n_prod_override",
            "n_prod_via_pt", "n_ventas_total"]
    headers = ["ID", "Depto", "Categoria",
               "Subcats", "PT", "Override", "Prods PT", "Ventas"]
    widths  = [4, 18, 30, 8, 5, 9, 9, 8]

    line_fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(line_fmt.format(*headers))
    print("  " + "-" * (sum(widths) + (len(widths) - 1) * 2))

    for r in rows:
        vals = []
        for c, w in zip(cols, widths):
            v = r.get(c, "")
            if isinstance(v, str) and len(v) > w:
                v = v[: w - 1] + "…"
            vals.append(str(v))
        print(line_fmt.format(*vals))
    print(f"\n  Total: {len(rows)} categoria(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Limpieza de categorias vacias (sin productos ni historial)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Aplica el borrado de verdad. Por defecto es DRY-RUN (solo lista).",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  KAWII — Auditoria de categorias vacias")
    print("=" * 70)

    rows = _listar_categorias()
    candidatas = [r for r in rows if r.get("puede_borrarse")]
    con_datos  = [r for r in rows if not r.get("puede_borrarse")]

    print(f"\n  Total categorias en BD : {len(rows)}")
    print(f"  Con productos / ventas : {len(con_datos)}")
    print(f"  Candidatas a borrar    : {len(candidatas)}")

    _imprimir_tabla(candidatas, "CANDIDATAS A BORRAR (100% vacias)")

    if not candidatas:
        print("\n  No hay categorias para limpiar. ✓")
        return

    if not args.apply:
        print("\n" + "=" * 70)
        print("  MODO DRY-RUN — no se borro nada.")
        print("  Para aplicar el borrado, vuelve a ejecutar con --apply:")
        print("    python analytics_scripts/cleanup_empty_categories.py --apply")
        print("=" * 70)
        return

    # Apply real
    print("\n" + "=" * 70)
    print(f"  APLICANDO BORRADO de {len(candidatas)} categoria(s)...")
    print("=" * 70)

    ids = [r["cat_id"] for r in candidatas]
    n_eliminadas = _borrar(ids)
    n_subcats = sum(int(r.get("n_subcats") or 0) for r in candidatas)

    print(f"\n  ✓ Eliminadas    : {n_eliminadas} categoria(s)")
    print(f"  ✓ Cascada subcats: {n_subcats} subcategoria(s) vacia(s)")
    print(f"  ✓ BSale          : NO afectado (categories es solo interna)")
    print()


if __name__ == "__main__":
    main()
