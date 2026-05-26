"""
KAWII - Actualizacion COMPLETA (masters + transaccional + reporte)
===================================================================

Diseñado para ejecutarse cuando hubo cambios en BSale (productos nuevos,
categorias nuevas, recepciones, ventas). Refresca todo el pipeline y al
final imprime un informe detallado de salud de la base de datos.

Uso:
    python update_all.py                    # ultimos 7 dias de documentos
    python update_all.py --days 30          # ultimo mes
    python update_all.py --days 3650        # full (~63 min)
    python update_all.py --days 7 --json reporte.json  # guarda JSON
    python update_all.py --skip-documents   # solo masters + stock

Fases:
    1. Taxonomia (departments, categories, subcategories) desde JSON
    2. Masters de BSale (offices, product_types, document_types, variants)
    3. Costos y stock actual + snapshot del dia
    4. Atributos
    5. Recepciones ultimos N dias
    6. Documentos ultimos N dias (TURBO, 6 workers)
    7. Reporte detallado (stdout + JSON opcional)

Idempotente: UPSERT en todas las tablas -> ejecutar multiples veces NO duplica.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from harvester import db
from harvester.sync_masters import (
    sync_taxonomy,
    sync_offices,
    sync_product_types,
    sync_document_types,
    sync_variants,
    sync_variant_costs,
    sync_stock_levels,
    snapshot_stock_history,
    sync_product_type_attributes,
    sync_variant_attribute_values,
)
from harvester.sync_transactions import sync_documents, sync_receptions, sync_consumptions


LOG_FMT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FMT,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("update_all.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# REPORTE
# ---------------------------------------------------------------------------

def _q(sql: str, params: tuple = ()) -> list[tuple]:
    """Ejecuta SELECT y retorna todas las filas."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _scalar(sql: str, params: tuple = ()) -> object:
    rows = _q(sql, params)
    return rows[0][0] if rows else None


def build_report(phase_results: dict, elapsed_sec: float) -> dict:
    """Construye el reporte final leyendo el estado actual de la BD."""
    report: dict = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "duracion_segundos": round(elapsed_sec, 2),
        "duracion_minutos": round(elapsed_sec / 60, 2),
        "fases": phase_results,
    }

    # --- Conteos globales ---
    counts = {}
    tablas = [
        "departments", "categories", "subcategories",
        "offices", "product_types", "document_types",
        "products", "variants", "variant_costs",
        "stock_levels", "stock_history",
        "receptions", "reception_details",
        "documents", "document_details",
        "product_type_attributes", "variant_attribute_values",
        "sync_log", "data_quality_issues",
    ]
    for t in tablas:
        try:
            counts[t] = _scalar(f"SELECT COUNT(*) FROM {t}")
        except Exception as exc:
            counts[t] = f"ERROR: {exc}"
    report["conteos"] = counts

    # --- Salud de la taxonomia ---
    report["taxonomia"] = {
        "departamentos": _scalar("SELECT COUNT(*) FROM departments"),
        "categorias": _scalar("SELECT COUNT(*) FROM categories"),
        "subcategorias": _scalar("SELECT COUNT(*) FROM subcategories"),
        "product_types_mapeados": _scalar(
            "SELECT COUNT(*) FROM product_types WHERE is_mapped = TRUE"
        ),
        "product_types_sin_mapear": _scalar(
            "SELECT COUNT(*) FROM product_types WHERE is_mapped = FALSE"
        ),
    }

    # --- Productos huerfanos (categorias BSale con productos pero sin mapeo).
    # Excluye productos que tengan subcategory_id override (ya estan ubicados).
    huerfanos = _q("""
        SELECT pt.bsale_product_type_id, pt.name, COUNT(p.bsale_product_id)
        FROM product_types pt
        LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
        WHERE NOT pt.is_mapped
          AND p.subcategory_id IS NULL
        GROUP BY 1, 2
        HAVING COUNT(p.bsale_product_id) > 0
        ORDER BY 3 DESC
    """)
    report["alertas"] = {
        "product_types_sin_mapear_con_productos": [
            {"id": r[0], "nombre": r[1], "productos": r[2]} for r in huerfanos
        ],
        "productos_huerfanos_total": sum(r[2] for r in huerfanos),
    }

    # --- Top departamentos por productos (usa la vista con override aplicado) ---
    top_deps = _q("""
        SELECT department, COUNT(DISTINCT bsale_product_id)
        FROM v_products_full
        WHERE department IS NOT NULL
        GROUP BY department
        ORDER BY 2 DESC NULLS LAST
        LIMIT 10
    """)
    report["top_departamentos_por_productos"] = [
        {"departamento": r[0], "productos": r[1]} for r in top_deps
    ]

    # --- Ventas ultimos 30 dias (top departamentos, usa v_products_full) ---
    # Solo sucursales activas (alineado con analytics/core/config.py).
    try:
        from analytics.core.config import OFFICE_IDS as _OIDS
        _office_ids_sql = ", ".join(str(i) for i in _OIDS)
        top_ventas = _q(f"""
            SELECT vpf.department,
                   ROUND(SUM(dd.total_amount)::numeric, 2) AS ventas,
                   COUNT(DISTINCT doc.bsale_document_id)   AS tickets
            FROM document_details dd
            JOIN documents doc       ON doc.bsale_document_id  = dd.bsale_document_id
            JOIN variants v          ON v.bsale_variant_id     = dd.bsale_variant_id
            JOIN v_products_full vpf ON vpf.bsale_product_id   = v.bsale_product_id
            WHERE (doc.emission_date AT TIME ZONE 'America/Lima')::date >= CURRENT_DATE - 30
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND doc.bsale_office_id IN ({_office_ids_sql})
              AND vpf.department IS NOT NULL
            GROUP BY vpf.department
            ORDER BY ventas DESC
            LIMIT 10
        """)
        report["ventas_30d_top_departamentos"] = [
            {"departamento": r[0], "ventas": float(r[1] or 0), "tickets": r[2]}
            for r in top_ventas
        ]
    except Exception as exc:
        report["ventas_30d_top_departamentos"] = {"error": str(exc)}

    # --- Stock valorizado por sucursal ---
    try:
        stock_val = _q("""
            SELECT o.name,
                   ROUND(SUM(sl.quantity_available * COALESCE(vc.effective_cost, 0))::numeric, 2) AS valor,
                   SUM(sl.quantity_available) AS unidades
            FROM stock_levels sl
            JOIN offices o          ON o.bsale_office_id = sl.bsale_office_id
            LEFT JOIN variant_costs vc ON vc.bsale_variant_id = sl.bsale_variant_id
            WHERE sl.quantity_available > 0
            GROUP BY o.name
            ORDER BY valor DESC
        """)
        report["stock_valorizado_por_sucursal"] = [
            {"sucursal": r[0], "valor_soles": float(r[1] or 0), "unidades": float(r[2] or 0)}
            for r in stock_val
        ]
    except Exception as exc:
        report["stock_valorizado_por_sucursal"] = {"error": str(exc)}

    # --- Documento mas reciente ---
    try:
        doc_reciente = _q("""
            SELECT MAX(emission_date), COUNT(*) FILTER (WHERE emission_date >= NOW() - INTERVAL '7 days')
            FROM documents
        """)[0]
        report["documentos"] = {
            "mas_reciente": doc_reciente[0].isoformat() if doc_reciente[0] else None,
            "ultimos_7_dias": doc_reciente[1],
        }
    except Exception as exc:
        report["documentos"] = {"error": str(exc)}

    # --- Ultimas syncs (historial reciente) ---
    try:
        syncs = _q("""
            SELECT entity, status, started_at, finished_at,
                   records_fetched, records_inserted, records_updated, records_skipped,
                   EXTRACT(EPOCH FROM (finished_at - started_at))::int AS duracion_s
            FROM sync_log
            ORDER BY started_at DESC
            LIMIT 15
        """)
        report["historial_sync_reciente"] = [
            {
                "entidad": r[0], "status": r[1],
                "inicio": r[2].isoformat() if r[2] else None,
                "fin": r[3].isoformat() if r[3] else None,
                "fetched": r[4], "inserted": r[5], "updated": r[6], "skipped": r[7],
                "duracion_s": r[8],
            }
            for r in syncs
        ]
    except Exception as exc:
        report["historial_sync_reciente"] = {"error": str(exc)}

    return report


def print_report(report: dict) -> None:
    """Imprime el reporte en formato legible."""
    R = report
    print()
    print("=" * 72)
    print(f"  INFORME FINAL - {R['generado_en']}")
    print(f"  Duracion: {R['duracion_minutos']:.2f} min ({R['duracion_segundos']:.1f} s)")
    print("=" * 72)

    print("\n-- FASES EJECUTADAS --")
    for fase, resultado in R["fases"].items():
        print(f"  {fase:25s} -> {resultado}")

    print("\n-- CONTEOS DE TABLAS --")
    for t, n in R["conteos"].items():
        print(f"  {t:30s} {n:>10}")

    tax = R["taxonomia"]
    print("\n-- TAXONOMIA --")
    print(f"  Departamentos              {tax['departamentos']:>10}")
    print(f"  Categorias                 {tax['categorias']:>10}")
    print(f"  Subcategorias              {tax['subcategorias']:>10}")
    print(f"  Product_types mapeados     {tax['product_types_mapeados']:>10}")
    print(f"  Product_types sin mapear   {tax['product_types_sin_mapear']:>10}")

    alertas = R["alertas"]
    print("\n-- ALERTAS DE CALIDAD --")
    total = alertas["productos_huerfanos_total"]
    n_cats = len(alertas["product_types_sin_mapear_con_productos"])
    if total == 0:
        print("  [OK] 0 productos huerfanos (todas las categorias BSale con "
              "productos estan mapeadas)")
    else:
        print(f"  [!] {total} productos en {n_cats} categorias BSale SIN mapear:")
        for h in alertas["product_types_sin_mapear_con_productos"]:
            print(f"      - id {h['id']:4d} | {h['productos']:3d} prods | {h['nombre']}")

    print("\n-- TOP 10 DEPARTAMENTOS POR PRODUCTOS --")
    for d in R["top_departamentos_por_productos"]:
        print(f"  {d['departamento']:30s} {d['productos']:>6}")

    if isinstance(R.get("ventas_30d_top_departamentos"), list):
        print("\n-- VENTAS ULTIMOS 30 DIAS (TOP 10) --")
        for v in R["ventas_30d_top_departamentos"]:
            print(f"  {v['departamento']:30s} S/{v['ventas']:>12,.2f}  ({v['tickets']} tickets)")

    if isinstance(R.get("stock_valorizado_por_sucursal"), list):
        print("\n-- STOCK VALORIZADO POR SUCURSAL --")
        for s in R["stock_valorizado_por_sucursal"]:
            print(f"  {s['sucursal']:30s} S/{s['valor_soles']:>12,.2f}  "
                  f"({s['unidades']:,.0f} unidades)")

    docs = R.get("documentos")
    if isinstance(docs, dict) and "mas_reciente" in docs:
        print("\n-- DOCUMENTOS --")
        print(f"  Mas reciente                 {docs['mas_reciente']}")
        print(f"  Ultimos 7 dias               {docs['ultimos_7_dias']:>10}")

    print("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="KAWII - Actualizacion completa con informe"
    )
    parser.add_argument("--days", type=int, default=7,
                        help="Cuantos dias atras sincronizar documentos/recepciones (default: 7)")
    parser.add_argument("--json", type=str, default=None,
                        help="Ruta para guardar el reporte en JSON")
    parser.add_argument("--skip-documents", action="store_true",
                        help="Saltar la fase de documentos (util si solo cambio catalogo)")
    parser.add_argument("--skip-stock-snapshot", action="store_true",
                        help="Saltar el snapshot diario de stock_history")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    logger = logging.getLogger("update_all")

    # FIX TIMEZONE: calcular "medianoche Lima" hace N dias, no medianoche UTC.
    # Antes: medianoche UTC = 19:00 Lima del dia anterior -> perdiamos 5h de ventas.
    # Ahora: medianoche Lima hace N dias -> rango correcto que coincide con BSale.
    _lima_tz = ZoneInfo("America/Lima")
    _now_lima = datetime.now(_lima_tz)
    since_dt_lima = (_now_lima - timedelta(days=args.days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    since_unix = int(since_dt_lima.timestamp())
    since_dt = since_dt_lima  # para el logger

    logger.info("=" * 72)
    logger.info("  KAWII UPDATE ALL - %d dias atras", args.days)
    logger.info("  Desde: %s (unix=%d)", since_dt.strftime("%Y-%m-%d %H:%M"), since_unix)
    logger.info("  Inicio: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 72)

    db.init_pool()
    t_total = time.time()
    phase_results: dict = {}

    try:
        # --- 1. Taxonomia + Masters ---
        logger.info(">>> FASE 1: Taxonomia y Masters")
        for nombre, func in [
            ("1.Taxonomia",         sync_taxonomy),
            ("2.Sucursales",        sync_offices),
            ("3.Categorias(BSale)", sync_product_types),
            ("4.Tipos Documento",   sync_document_types),
            ("5.Productos+Variant", sync_variants),
            ("6.Attrs Categoria",   sync_product_type_attributes),
            ("7.Attrs Variantes",   sync_variant_attribute_values),
        ]:
            t0 = time.time()
            try:
                r = func()
                dur = time.time() - t0
                phase_results[nombre] = {"resultado": str(r), "duracion_s": round(dur, 1)}
                logger.info("  %s: %.1fs | %s", nombre, dur, r)
            except Exception as exc:
                phase_results[nombre] = {"ERROR": str(exc)}
                logger.exception("  %s FALLO: %s", nombre, exc)

        # --- 2. Stock y costos ---
        logger.info(">>> FASE 2: Stock y Costos")
        t0 = time.time()
        r = sync_stock_levels()
        phase_results["8.Stock"] = {"resultado": str(r), "duracion_s": round(time.time() - t0, 1)}
        logger.info("  Stock: %.1fs | %s", time.time() - t0, r)

        t0 = time.time()
        r = sync_variant_costs()
        phase_results["9.Costos"] = {"resultado": str(r), "duracion_s": round(time.time() - t0, 1)}
        logger.info("  Costos: %.1fs | %s", time.time() - t0, r)

        # --- 2b. Snapshot de stock ---
        if not args.skip_stock_snapshot:
            logger.info(">>> FASE 2b: Snapshot Stock History")
            t0 = time.time()
            try:
                r = snapshot_stock_history()
                phase_results["10.StockHistory"] = {
                    "resultado": str(r), "duracion_s": round(time.time() - t0, 1),
                }
                logger.info("  Stock History: %.1fs | %s", time.time() - t0, r)
            except Exception as exc:
                phase_results["10.StockHistory"] = {"ERROR": str(exc)}
                logger.exception("  StockHistory FALLO: %s", exc)

        # --- 3. Recepciones ---
        logger.info(">>> FASE 3: Recepciones")
        t0 = time.time()
        try:
            r = sync_receptions()
            phase_results["11.Recepciones"] = {
                "resultado": str(r), "duracion_s": round(time.time() - t0, 1),
            }
            logger.info("  Recepciones: %.1fs | %s", time.time() - t0, r)
        except Exception as exc:
            phase_results["11.Recepciones"] = {"ERROR": str(exc)}
            logger.exception("  Recepciones FALLO: %s", exc)

        # --- 3.5 Consumos ---
        logger.info(">>> FASE 3.5: Consumos")
        t0 = time.time()
        try:
            r = sync_consumptions()
            phase_results["11.5.Consumos"] = {
                "resultado": str(r), "duracion_s": round(time.time() - t0, 1),
            }
            logger.info("  Consumos: %.1fs | %s", time.time() - t0, r)
        except Exception as exc:
            phase_results["11.5.Consumos"] = {"ERROR": str(exc)}
            logger.exception("  Consumos FALLO: %s", exc)

        # --- 4. Documentos ---
        if not args.skip_documents:
            logger.info(">>> FASE 4: Documentos (TURBO, desde %s)",
                        since_dt.strftime("%Y-%m-%d"))
            t0 = time.time()
            try:
                r = sync_documents(since_unix=since_unix)
                phase_results["12.Documentos"] = {
                    "resultado": str(r), "duracion_s": round(time.time() - t0, 1),
                }
                logger.info("  Documentos: %.1fs | %s", time.time() - t0, r)
            except Exception as exc:
                phase_results["12.Documentos"] = {"ERROR": str(exc)}
                logger.exception("  Documentos FALLO: %s", exc)

        elapsed = time.time() - t_total
        logger.info("=" * 72)
        logger.info("  Todas las fases completadas en %.1f min", elapsed / 60)
        logger.info("=" * 72)

        # --- 5. Reporte ---
        report = build_report(phase_results, elapsed)
        print_report(report)

        if args.json:
            out = Path(args.json)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            logger.info("Reporte JSON guardado en: %s", out.resolve())

        return 0

    except KeyboardInterrupt:
        logger.warning("Interrumpido por el usuario")
        return 130
    except Exception as exc:
        logger.exception("Error fatal: %s", exc)
        return 1
    finally:
        db.close_pool()


if __name__ == "__main__":
    sys.exit(main())
