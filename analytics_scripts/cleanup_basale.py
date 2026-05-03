"""
Limpieza de product_types BSale huerfanos.

Estrategia:
  A) product_types 100% vacios (sin productos, sin atributos, sin variants, sin ventas)
     -> ELIMINAR en BSale + ELIMINAR en BD local
  B) product_types con atributos huerfanos pero sin productos
     -> ELIMINAR en BSale (cascada borra atributos) + ELIMINAR en BD local
  C) product_types con productos
     -> NO TOCAR. Solo reportar para que el usuario los mapee manualmente.

Uso:
    cd produccion
    python analytics_scripts/cleanup_basale.py            # dry-run
    python analytics_scripts/cleanup_basale.py --apply    # aplica
"""

from __future__ import annotations

import argparse
import io
import sys
import time
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


# ─── SQL para identificar candidatos ──────────────────────────────────────────

SQL_CANDIDATOS_ELIMINAR = """
SELECT
    pt.bsale_product_type_id AS pt_id,
    pt.name                   AS nombre,
    pt.is_active,
    (SELECT COUNT(*) FROM product_type_attributes a
       WHERE a.bsale_product_type_id = pt.bsale_product_type_id) AS n_atributos
FROM product_types pt
WHERE NOT EXISTS (SELECT 1 FROM products p
                  WHERE p.bsale_product_type_id = pt.bsale_product_type_id)
  AND NOT EXISTS (SELECT 1 FROM variants v
                  JOIN products p ON p.bsale_product_id = v.bsale_product_id
                  WHERE p.bsale_product_type_id = pt.bsale_product_type_id)
  AND NOT EXISTS (
      SELECT 1 FROM document_details dd
      JOIN variants v  ON v.bsale_variant_id = dd.bsale_variant_id
      JOIN products p  ON p.bsale_product_id = v.bsale_product_id
      WHERE p.bsale_product_type_id = pt.bsale_product_type_id
  )
ORDER BY pt.name
"""

SQL_PRODUCT_TYPES_CON_PRODUCTOS_SIN_MAPEO = """
SELECT
    pt.bsale_product_type_id AS pt_id,
    pt.name                   AS nombre,
    pt.is_active,
    (SELECT COUNT(*) FROM products p
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_productos,
    (SELECT COUNT(*) FROM document_details dd
       JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
       JOIN products p ON p.bsale_product_id = v.bsale_product_id
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS n_ventas,
    (SELECT STRING_AGG(p.name, ' | ' ORDER BY p.name)
       FROM products p
       WHERE p.bsale_product_type_id = pt.bsale_product_type_id) AS productos_lista
FROM product_types pt
WHERE pt.subcategory_id IS NULL
  AND EXISTS (SELECT 1 FROM products p
              WHERE p.bsale_product_type_id = pt.bsale_product_type_id)
ORDER BY pt.name
"""


def _q(sql: str, params=None) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _exec(sql: str, params=None) -> int:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            n = cur.rowcount
        conn.commit()
    return n


def _eliminar_pt(pt_id: int, nombre: str, n_atrib: int) -> tuple[bool, str]:
    """
    Elimina un product_type en BSale + BD local.
    Retorna: (success, mensaje)
    """
    from harvester import bsale_client

    # 1. Si tiene atributos, los borramos primero (BSale puede no aceptar cascada)
    if n_atrib > 0:
        atribs = _q(
            "SELECT bsale_attribute_id FROM product_type_attributes WHERE bsale_product_type_id = %s",
            (pt_id,),
        )
        for a in atribs:
            try:
                bsale_client.delete(f"product_type_attributes/{a['bsale_attribute_id']}.json")
            except Exception as exc:
                # Si falla la API del atributo, no abortamos — quizas ya no existe en BSale
                msg = str(exc)[:80]
                if "404" not in msg and "no encontr" not in msg.lower():
                    return False, f"Error borrando atributo {a['bsale_attribute_id']}: {msg}"

    # 2. DELETE en BSale
    try:
        bsale_client.delete(f"product_types/{pt_id}.json")
    except Exception as exc:
        msg = str(exc)[:120]
        # Si BSale dice 404 (ya no existe alla), continuamos con el DELETE local
        if "404" in msg or "no encontr" in msg.lower():
            pass  # ya no estaba en BSale, todo bien
        else:
            return False, f"BSale: {msg}"

    # 3. DELETE en BD local (cascada borra atributos huerfanos)
    try:
        _exec("DELETE FROM product_types WHERE bsale_product_type_id = %s", (pt_id,))
    except Exception as exc:
        return False, f"BD local: {str(exc)[:120]}"

    return True, "OK"


def main():
    parser = argparse.ArgumentParser(
        description="Limpieza de product_types BSale huerfanos"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Aplica el borrado en BSale + BD. Default es DRY-RUN (solo lista).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limita la cantidad de product_types a procesar (util para test).",
    )
    parser.add_argument(
        "--delay", type=float, default=0.4,
        help="Segundos de delay entre llamadas a BSale (rate limit). Default 0.4s",
    )
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  KAWII — Limpieza de product_types BSale huerfanos")
    print("=" * 80)

    # 1) Candidatos sin productos / variants / ventas
    candidatos = _q(SQL_CANDIDATOS_ELIMINAR)
    if args.limit:
        candidatos = candidatos[: args.limit]

    # 2) Con productos pero sin mapeo (no se tocan)
    sin_mapeo = _q(SQL_PRODUCT_TYPES_CON_PRODUCTOS_SIN_MAPEO)

    print(f"\n  product_types huerfanos a eliminar : {len(candidatos)}")
    print(f"  product_types con productos sin mapeo (se preservan): {len(sin_mapeo)}")

    # ── Reporte de los que necesitan mapeo manual ─────────────────────────────
    if sin_mapeo:
        print(f"\n  ── ATENCION: estos {len(sin_mapeo)} product_types necesitan MAPEO MANUAL ──")
        print(f"     (tienen productos con ventas historicas, NO se eliminan)\n")
        for r in sin_mapeo:
            print(f"     PT {r['pt_id']:>4} | {r['n_productos']} prods | {r['n_ventas']} ventas | {r['nombre'][:60]}")
            for nombre_prod in (r.get("productos_lista") or "").split(" | "):
                print(f"           - {nombre_prod[:75]}")
            print()
        print("     Para mapearlos, usa:")
        print("       PATCH /product-types/{pt_id}  body={\"subcategory_id\": <id>}")
        print()

    if not candidatos:
        print("\n  ✓ No hay product_types huerfanos para eliminar.")
        return

    # ── Preview de candidatos ─────────────────────────────────────────────────
    activos    = sum(1 for c in candidatos if c.get("is_active"))
    inactivos  = len(candidatos) - activos
    con_atrib  = sum(1 for c in candidatos if (c.get("n_atributos") or 0) > 0)

    print(f"\n  Detalle de candidatos a ELIMINAR:")
    print(f"     - is_active=True  : {activos}")
    print(f"     - is_active=False : {inactivos}")
    print(f"     - con atributos huerfanos : {con_atrib}")

    if not args.apply:
        # Mostrar solo primeros 30 en dry-run
        print(f"\n  ── PRIMEROS 30 candidatos (dry-run) ──")
        print(f"     {'PT_ID':>5}  {'is_active':>10}  {'atrib':>5}  NOMBRE")
        print("     " + "-" * 70)
        for c in candidatos[:30]:
            print(f"     {c['pt_id']:>5}  {str(c['is_active']):>10}  "
                  f"{c['n_atributos']:>5}  {c['nombre'][:60]}")
        if len(candidatos) > 30:
            print(f"     ... y {len(candidatos) - 30} mas")

        print(f"\n  ⏱  Tiempo estimado al aplicar: ~{len(candidatos) * args.delay:.0f} seg "
              f"({len(candidatos) * args.delay / 60:.1f} min) con delay={args.delay}s\n")
        print("  " + "=" * 76)
        print("  MODO DRY-RUN — no se borro nada.")
        print("  Para aplicar: python analytics_scripts/cleanup_basale.py --apply")
        print("  " + "=" * 76)
        return

    # ── Apply ─────────────────────────────────────────────────────────────────
    print(f"\n  APLICANDO BORRADO de {len(candidatos)} product_types en BSale + BD local...")
    print("  " + "=" * 76)

    resultados = {"ok": [], "fallos": []}
    t0 = time.time()

    for i, c in enumerate(candidatos, 1):
        success, msg = _eliminar_pt(
            pt_id=c["pt_id"],
            nombre=c["nombre"],
            n_atrib=c.get("n_atributos") or 0,
        )
        if success:
            resultados["ok"].append(c)
            print(f"  [{i:>3}/{len(candidatos)}] ✓ PT {c['pt_id']:>4} — {c['nombre'][:55]}")
        else:
            resultados["fallos"].append({**c, "error": msg})
            print(f"  [{i:>3}/{len(candidatos)}] ✗ PT {c['pt_id']:>4} — {c['nombre'][:50]} — {msg[:50]}")

        time.sleep(args.delay)

    elapsed = time.time() - t0

    print("\n  " + "=" * 76)
    print(f"  RESUMEN:")
    print(f"     ✓ Eliminados : {len(resultados['ok']):>4} product_types")
    print(f"     ✗ Fallos     : {len(resultados['fallos']):>4} product_types")
    print(f"     ⏱  Tiempo    : {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"     ⊘ Preservados (con productos sin mapeo): {len(sin_mapeo)}")

    if resultados["fallos"]:
        print(f"\n  FALLOS (revisar manualmente):")
        for f in resultados["fallos"][:10]:
            print(f"     PT {f['pt_id']:>4} ({f['nombre'][:40]}): {f['error'][:80]}")
        if len(resultados["fallos"]) > 10:
            print(f"     ... y {len(resultados['fallos']) - 10} mas")
    print()


if __name__ == "__main__":
    main()
