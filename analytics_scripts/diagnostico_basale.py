"""
Diagnostico de elementos huerfanos / desincronizados con BSale.

Investiga 3 puntos:
  1. product_types (categorias BSale) que no tienen NADA conectado
     → candidatos a eliminar en BSale
  2. product_types con productos pero subcategory_id NULL (los 2 alertados)
     → necesitan mapeo o eliminacion
  3. productos en nuestra BD que parecen estar eliminados en BSale
     → is_active=false, sin variants activas, sin ventas recientes

Solo lectura (no modifica nada). Imprime tablas con candidatos.
"""

from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

_PRODUCCION = Path(__file__).resolve().parent.parent
if str(_PRODUCCION) not in sys.path:
    sys.path.insert(0, str(_PRODUCCION))

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from analytics_scripts.db_helper import _get_conn  # noqa: E402
import psycopg2.extras  # noqa: E402


def _q(sql: str, params=None) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _print_section(titulo: str):
    print(f"\n{'=' * 90}")
    print(f"  {titulo}")
    print('=' * 90)


def _print_table(rows: list[dict], cols: list[tuple[str, int]], titulo: str = ""):
    """cols: lista de tuplas (nombre_col, ancho)"""
    if titulo:
        print(f"\n  ── {titulo} ──")
    if not rows:
        print("    (ninguno)")
        return

    line_fmt = "    " + "  ".join(f"{{:<{w}}}" for _, w in cols)
    print(line_fmt.format(*[c.upper() for c, _ in cols]))
    print("    " + "-" * (sum(w for _, w in cols) + (len(cols) - 1) * 2))

    for r in rows:
        vals = []
        for c, w in cols:
            v = r.get(c, "")
            if v is None:
                v = "-"
            v = str(v)
            if len(v) > w:
                v = v[: w - 1] + "…"
            vals.append(v)
        print(line_fmt.format(*vals))
    print(f"\n    Total: {len(rows)}")


# ── 1. product_types huerfanos (sin productos, sin atributos, sin nada) ──
SQL_PT_HUERFANOS = """
SELECT
    pt.bsale_product_type_id           AS pt_id,
    pt.name                             AS nombre,
    pt.subcategory_id,
    pt.is_active,
    pt.is_mapped,
    (SELECT COUNT(*) FROM products p
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_productos,
    (SELECT COUNT(*) FROM product_type_attributes a
       WHERE a.bsale_product_type_id = pt.bsale_product_type_id) AS n_atributos,
    (SELECT COUNT(DISTINCT v.bsale_variant_id) FROM variants v
       JOIN products p ON p.bsale_product_id = v.bsale_product_id
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_variants,
    (SELECT COUNT(*) FROM document_details dd
       JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
       JOIN products p ON p.bsale_product_id = v.bsale_product_id
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_ventas
FROM product_types pt
ORDER BY n_productos ASC, n_ventas ASC, pt.name
"""


# ── 2. product_types con productos pero sin mapeo a subcategory ──
SQL_PT_SIN_MAPEO_CON_PROD = """
SELECT
    pt.bsale_product_type_id           AS pt_id,
    pt.name                             AS nombre,
    pt.is_active,
    (SELECT COUNT(*) FROM products p
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_productos,
    (SELECT STRING_AGG(p.name, ' | ' ORDER BY p.name)
       FROM products p
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS productos_lista,
    (SELECT COUNT(*) FROM document_details dd
       JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
       JOIN products p ON p.bsale_product_id = v.bsale_product_id
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_ventas
FROM product_types pt
WHERE pt.subcategory_id IS NULL
  AND EXISTS (SELECT 1 FROM products p
                WHERE p.bsale_product_type_id = pt.bsale_product_type_id)
ORDER BY n_productos DESC, pt.name
"""


# ── 3. Productos posiblemente eliminados en BSale (inactivos / sin sync reciente) ──
SQL_PRODUCTOS_INACTIVOS = """
SELECT
    p.bsale_product_id            AS prod_id,
    p.name                          AS nombre,
    p.is_active,
    p.bsale_product_type_id        AS pt_id,
    p.synced_at::date               AS ultima_sync,
    NOW()::date - p.synced_at::date AS dias_sin_sync,
    (SELECT COUNT(*) FROM variants v
       WHERE v.bsale_product_id = p.bsale_product_id) AS n_variants,
    (SELECT COUNT(*) FROM variants v
       WHERE v.bsale_product_id = p.bsale_product_id
         AND v.is_active = TRUE) AS n_variants_activas,
    (SELECT COUNT(*) FROM document_details dd
       JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
       WHERE v.bsale_product_id = p.bsale_product_id) AS n_ventas_total,
    (SELECT MAX(doc.emission_date)::date
       FROM document_details dd
       JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
       JOIN documents doc ON doc.bsale_document_id = dd.bsale_document_id
       WHERE v.bsale_product_id = p.bsale_product_id) AS ultima_venta
FROM products p
WHERE p.is_active = FALSE
   OR NOT EXISTS (
       SELECT 1 FROM variants v
       WHERE v.bsale_product_id = p.bsale_product_id
         AND v.is_active = TRUE
   )
ORDER BY p.synced_at DESC
"""


# ── 4. Ultima sync de productos (para detectar productos no sincronizados) ──
SQL_RANGO_SYNC = """
SELECT
    MIN(synced_at)::date AS sync_mas_antigua,
    MAX(synced_at)::date AS sync_mas_reciente,
    COUNT(*)              AS total_productos,
    COUNT(*) FILTER (WHERE is_active)        AS activos,
    COUNT(*) FILTER (WHERE NOT is_active)    AS inactivos
FROM products
"""


def main():
    print("\n" + "=" * 90)
    print("  KAWII — Diagnostico de huerfanos / desincronizados con BSale")
    print("=" * 90)

    # ── 0. Contexto general ────────────────────────────────────────────────
    rango = _q(SQL_RANGO_SYNC)[0]
    print(f"\n  Total productos en BD : {rango['total_productos']}")
    print(f"  Activos               : {rango['activos']}")
    print(f"  Inactivos             : {rango['inactivos']}")
    print(f"  Sync mas antigua      : {rango['sync_mas_antigua']}")
    print(f"  Sync mas reciente     : {rango['sync_mas_reciente']}")

    # ── 1. product_types huerfanos puros ───────────────────────────────────
    _print_section("1. PRODUCT_TYPES BSALE — sin productos, sin atributos, sin variants")
    huerf = _q(SQL_PT_HUERFANOS)
    sin_nada = [r for r in huerf if r["n_productos"] == 0 and r["n_atributos"] == 0
                and r["n_variants"] == 0 and r["n_ventas"] == 0]
    sin_prod_con_data = [r for r in huerf if r["n_productos"] == 0 and r["n_ventas"] == 0
                         and (r["n_atributos"] > 0 or r["n_variants"] > 0)]

    print(f"\n  Total product_types : {len(huerf)}")
    print(f"  100% huerfanos      : {len(sin_nada)}  ← candidatos a ELIMINAR de BSale")
    print(f"  Sin prod pero c/ atrib o variants : {len(sin_prod_con_data)}  ← candidatos a DESACTIVAR")

    cols_pt = [
        ("pt_id", 6), ("nombre", 50), ("subcategory_id", 6),
        ("is_active", 6), ("n_productos", 6), ("n_atributos", 6),
        ("n_variants", 6), ("n_ventas", 6),
    ]
    _print_table(sin_nada, cols_pt, "Candidatos a ELIMINAR (100% vacios)")
    if sin_prod_con_data:
        _print_table(sin_prod_con_data, cols_pt,
                     "Candidatos a DESACTIVAR (tienen atributos pero ningun producto)")

    # ── 2. product_types sin mapeo con productos ────────────────────────────
    _print_section("2. PRODUCT_TYPES con productos pero SIN MAPEO a subcategoria interna")
    sin_map = _q(SQL_PT_SIN_MAPEO_CON_PROD)
    print(f"\n  Total product_types sin mapeo y con productos: {len(sin_map)}")

    cols_sm = [
        ("pt_id", 6), ("nombre", 50), ("is_active", 6),
        ("n_productos", 5), ("n_ventas", 6),
    ]
    _print_table(sin_map, cols_sm, "Necesitan accion (mapear, eliminar o desactivar)")

    if sin_map:
        print("\n  Lista de productos asociados:")
        for r in sin_map:
            print(f"\n    PT {r['pt_id']} ({r['nombre']}):")
            for nombre in (r.get("productos_lista") or "").split(" | "):
                print(f"      - {nombre}")

    # ── 3. Productos huerfanos (parecen eliminados en BSale) ────────────────
    _print_section("3. PRODUCTOS posiblemente ELIMINADOS en BSale")
    inact = _q(SQL_PRODUCTOS_INACTIVOS)

    sin_ventas      = [r for r in inact if r["n_ventas_total"] == 0]
    con_ventas_old  = [r for r in inact if r["n_ventas_total"] > 0
                       and r["ultima_venta"] is not None]

    print(f"\n  Productos inactivos / sin variants activas: {len(inact)}")
    print(f"    - Sin ventas historicas (seguros de eliminar): {len(sin_ventas)}")
    print(f"    - Con ventas historicas (preservar para reportes): {len(con_ventas_old)}")

    cols_p = [
        ("prod_id", 8), ("nombre", 35), ("is_active", 6),
        ("n_variants", 5), ("n_variants_activas", 5),
        ("n_ventas_total", 6), ("ultima_venta", 12), ("dias_sin_sync", 6),
    ]
    _print_table(
        sin_ventas[:20], cols_p,
        f"PRIMEROS 20 sin ventas — seguros de eliminar (total: {len(sin_ventas)})",
    )
    _print_table(
        con_ventas_old[:10], cols_p,
        f"PRIMEROS 10 con ventas — preservar (total: {len(con_ventas_old)})",
    )

    # ── 4. Resumen / acciones recomendadas ──────────────────────────────────
    _print_section("RESUMEN — acciones recomendadas")
    print(f"""
    A) ELIMINAR en BSale:    {len(sin_nada):4d} product_types 100% vacios
    B) DESACTIVAR:           {len(sin_prod_con_data):4d} product_types con atributos huerfanos
    C) MAPEAR o eliminar:    {len(sin_map):4d} product_types con productos pero sin subcat
    D) ELIMINAR (sin ventas):{len(sin_ventas):4d} productos huerfanos sin historial
    E) PRESERVAR:            {len(con_ventas_old):4d} productos inactivos con ventas historicas
    """)

    print("    Para ejecutar el cleanup automatico, corre:")
    print("      python analytics_scripts/cleanup_basale.py --apply")
    print()


if __name__ == "__main__":
    main()
