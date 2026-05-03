"""
CLI de analisis KAWII — imprime todos los resultados por consola.

Uso:
    cd produccion
    python analytics_scripts/run_all.py                  # todo
    python analytics_scripts/run_all.py --ticket         # solo ticket
    python analytics_scripts/run_all.py --inventory      # solo inventario
    python analytics_scripts/run_all.py --months 6       # ultimos 6 meses
    python analytics_scripts/run_all.py --top 30         # limitar filas
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Forzar UTF-8 en Windows (cp1252 no soporta caracteres de caja)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Asegurar que 'produccion/' este en el path para imports absolutos
_PRODUCCION_DIR = Path(__file__).resolve().parent.parent
if str(_PRODUCCION_DIR) not in sys.path:
    sys.path.insert(0, str(_PRODUCCION_DIR))

import pandas as pd
import numpy as np

# ── Intento de rich (colores en consola) ──────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    _RICH = True
    _console = Console()
except ImportError:
    _RICH = False
    _console = None

# ── Configurar logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,   # solo warnings y errores durante el analisis
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def _sep(title: str = "", char: str = "=", width: int = 90):
    if title:
        pad   = max(0, (width - len(title) - 2) // 2)
        print(f"\n{char * pad} {title} {char * (width - pad - len(title) - 2)}")
    else:
        print(char * width)


def _banner(text: str):
    _sep()
    print(f"  {text}")
    _sep()


def _ok(msg: str):
    prefix = "[OK]" if not _RICH else "[green][OK][/green]"
    if _RICH:
        _console.print(f"{prefix} {msg}")
    else:
        print(f"{prefix} {msg}")


def _warn(msg: str):
    prefix = "[!!]" if not _RICH else "[bold yellow][!!][/bold yellow]"
    if _RICH:
        _console.print(f"{prefix} {msg}")
    else:
        print(f"{prefix} {msg}")


def _error(msg: str):
    prefix = "[XX]" if not _RICH else "[bold red][XX][/bold red]"
    if _RICH:
        _console.print(f"{prefix} {msg}")
    else:
        print(f"{prefix} {msg}")


def _print_df(df: pd.DataFrame, max_rows: int = 30, title: str = ""):
    """Imprime un DataFrame como tabla legible."""
    if df.empty:
        _warn("  (sin datos)")
        return
    if title:
        print(f"\n  >>> {title}")

    # Reemplazar NaN por "-" para display
    display = (
        df.head(max_rows)
        .replace({np.nan: None})
        .fillna("-")
    )

    if _RICH and _console:
        _print_rich_table(display)
    else:
        _print_plain_table(display)

    omitted = len(df) - max_rows
    if omitted > 0:
        print(f"  ... (+{omitted} filas omitidas)")


def _print_plain_table(df: pd.DataFrame):
    try:
        from tabulate import tabulate
        print(tabulate(df, headers="keys", tablefmt="rounded_outline",
                       showindex=False, floatfmt=".2f"))
    except ImportError:
        # Fallback: pandas to_string
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 160)
        pd.set_option("display.float_format", "{:,.2f}".format)
        print(df.to_string(index=False))


def _print_rich_table(df: pd.DataFrame):
    table = Table(show_header=True, header_style="bold cyan",
                  border_style="dim", show_lines=False)
    for col in df.columns:
        table.add_column(str(col), overflow="fold")
    for _, row in df.iterrows():
        cells = []
        for v in row:
            s = str(v)
            # Colorear estados
            if s == "BAJO ROP - REORDENAR":
                s = f"[bold red]{s}[/bold red]"
            elif s == "BAJA" or s == "BAJANDO" or s == "ARRASTRA":
                s = f"[red]{s}[/red]"
            elif s == "SUBE" or s == "SUBIENDO" or s == "IMPULSA":
                s = f"[green]{s}[/green]"
            elif s == "AX":
                s = f"[bold green]{s}[/bold green]"
            elif s == "AZ" or s == "BZ" or s == "CZ":
                s = f"[bold red]{s}[/bold red]"
            cells.append(s)
        table.add_row(*cells)
    _console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# SECCION: TICKET PROMEDIO
# ─────────────────────────────────────────────────────────────────────────────

def run_ticket_analysis(months: int = 12, top: int = 30):
    from analytics_scripts.ticket_analysis import (
        tendencia_mensual,
        analisis_sucursales,
        profundidad_ticket,
        ticket_por_categoria,
        diagnostico_completo,
    )

    _banner("ANALISIS DEL TICKET PROMEDIO")

    # ── 1. Tendencia mensual ──────────────────────────────────────────────────
    _sep("1. Tendencia Mensual")
    t0 = time.time()
    tm = tendencia_mensual(months)
    print(f"  Cargado en {time.time()-t0:.1f}s\n")

    res = tm.get("resumen", {})
    print(f"  Ticket primer mes : ${res.get('primer_mes', 0):,.0f}")
    print(f"  Ticket ultimo mes : ${res.get('ultimo_mes', 0):,.0f}")
    print(f"  Cambio total      : {res.get('cambio_total_pct', 0):+.1f}%")
    print(f"  Meses a la baja   : {res.get('meses_a_la_baja', 0)}")
    print(f"  Meses al alza     : {res.get('meses_al_alza', 0)}")

    if tm["data"]:
        df_tm = pd.DataFrame(tm["data"])
        cols  = ["mes", "venta_total", "tickets", "ticket_promedio",
                 "var_ticket_pct", "estado"]
        _print_df(df_tm[[c for c in cols if c in df_tm.columns]],
                  max_rows=months, title="Evolucion mes a mes")

    # ── 2. Por sucursal ───────────────────────────────────────────────────────
    _sep("2. Por Sucursal")
    suc = analisis_sucursales(months * 30)
    print(f"  Ticket promedio global: ${suc.get('avg_global', 0):,.0f}\n")
    if suc["data"]:
        df_suc = pd.DataFrame(suc["data"])
        _print_df(df_suc, max_rows=top)

    # ── 3. Profundidad del ticket ─────────────────────────────────────────────
    _sep("3. Profundidad del Ticket (Items por Compra)")
    prof = profundidad_ticket(months)
    cambios = prof.get("cambios", {})
    print(f"  Cambio ticket       : {cambios.get('ticket_pct', 0):+.1f}%")
    print(f"  Cambio items/ticket : {cambios.get('items_pct', 0):+.1f}%")
    print(f"  Cambio precio prom  : {cambios.get('precio_prom_pct', 0):+.1f}%")
    print(f"\n  DIAGNOSTICO: {prof.get('diagnostico', '')}")
    if prof["data"]:
        df_prof = pd.DataFrame(prof["data"])
        cols    = ["mes", "ticket_promedio", "items_por_ticket",
                   "precio_unitario_prom", "var_ticket_pct",
                   "var_items_pct", "var_precio_pct"]
        _print_df(df_prof[[c for c in cols if c in df_prof.columns]],
                  max_rows=months)

    # ── 4. Por categoria ──────────────────────────────────────────────────────
    _sep("4. Ticket Promedio por Categoria")
    cat = ticket_por_categoria(months * 30)
    print(f"  Media global por linea: ${cat.get('avg_global', 0):,.0f}")
    if cat.get("top_arrastran"):
        print("\n  TOP CATEGORIAS QUE ARRASTRAN EL PROMEDIO HACIA ABAJO:")
        for c in cat["top_arrastran"]:
            print(f"    • {c['categoria']:<40} ticket=${c['ticket_prom_linea']:,.0f}"
                  f"  peso={c['peso_en_ventas_pct']:.1f}%")
    if cat["data"]:
        df_cat = pd.DataFrame(cat["data"])
        cols   = ["departamento", "categoria", "tickets", "venta_total",
                  "ticket_prom_linea", "precio_unitario_prom",
                  "vs_global_pct", "alerta"]
        _print_df(df_cat[[c for c in cols if c in df_cat.columns]],
                  max_rows=top)

    # ── 5. Recomendaciones ────────────────────────────────────────────────────
    diag = diagnostico_completo(months)
    _sep("RECOMENDACIONES EJECUTIVAS")
    for i, r in enumerate(diag.get("recomendaciones", []), 1):
        if "baja" in r.lower() or "debil" in r.lower() or "bajo" in r.lower():
            _warn(f"  {i}. {r}")
        else:
            _ok(f"  {i}. {r}")


# ─────────────────────────────────────────────────────────────────────────────
# SECCION: INVENTARIO
# ─────────────────────────────────────────────────────────────────────────────

def run_inventory_analysis(top: int = 30):
    from analytics_scripts.inventory_analysis import (
        calcular_abc_xyz,
        calcular_safety_stock_rop,
        calcular_eoq,
        calcular_gmroi,
    )

    _banner("ANALISIS DE INVENTARIO (ABC×XYZ / SS / ROP / EOQ / GMROI)")

    # ── 1. Matriz ABC×XYZ ─────────────────────────────────────────────────────
    _sep("1. Clasificacion ABC x XYZ")
    t0 = time.time()
    abcxyz = calcular_abc_xyz()
    print(f"  Calculado en {time.time()-t0:.1f}s\n")

    if abcxyz.get("resumen"):
        df_res = pd.DataFrame(abcxyz["resumen"])
        print("  RESUMEN POR CUADRANTE:")
        _print_df(df_res, max_rows=9)

    if abcxyz.get("leyenda"):
        print("\n  LEYENDA:")
        for k, v in abcxyz["leyenda"].items():
            print(f"    {k}: {v}")

    if abcxyz.get("data"):
        df_full = pd.DataFrame(abcxyz["data"])
        cols    = ["bsale_product_id", "product_name", "department", "category",
                   "abc", "xyz", "abc_xyz", "tendencia", "pct_30d_vs_90d",
                   "demand_diaria_efectiva", "revenue_90d"]
        _print_df(df_full[[c for c in cols if c in df_full.columns]],
                  max_rows=top, title="Top productos por revenue (90d)")

    # ── 2. Alertas de reposicion ───────────────────────────────────────────────
    _sep("2. Safety Stock / Reorder Point (ROP) — ALERTAS")
    rop_data = calcular_safety_stock_rop()
    total_bajo = rop_data.get("total_bajo_rop", 0)
    params     = rop_data.get("parametros", {})

    print(f"  Nivel de servicio : {params.get('nivel_servicio', '95%')}")
    print(f"  Lead time         : {params.get('lead_time_d', 7)} dias")
    print(f"  Z (factor)        : {params.get('z', 1.65)}")
    print(f"\n  Productos BAJO ROP: {total_bajo}")

    if rop_data.get("alertas"):
        _warn(f"\n  PRODUCTOS QUE NECESITAN REPOSICION ({total_bajo}):")
        df_alertas = pd.DataFrame(rop_data["alertas"])
        _print_df(df_alertas, max_rows=top)

    if rop_data.get("data"):
        df_rop = pd.DataFrame(rop_data["data"])
        cols   = ["product_name", "abc", "xyz",
                  "demand_diaria_efectiva", "stock_total",
                  "safety_stock", "rop", "estado_stock", "tendencia"]
        _print_df(df_rop[[c for c in cols if c in df_rop.columns]],
                  max_rows=top, title="Todos los productos ordenados por urgencia")

    # ── 3. EOQ ────────────────────────────────────────────────────────────────
    _sep("3. Economic Order Quantity (EOQ)")
    eoq_data = calcular_eoq()
    params_eoq = eoq_data.get("parametros", {})
    print(f"  Costo fijo de pedido : ${params_eoq.get('costo_pedido_clp', 0):,.0f} CLP")
    print(f"  Tasa de holding      : {params_eoq.get('tasa_holding_pct', 20):.0f}% anual")

    if eoq_data.get("data"):
        df_eoq = pd.DataFrame(eoq_data["data"])
        cols   = ["product_name", "abc", "demand_diaria_efectiva",
                  "costo_unitario", "eoq", "rev_anual_est"]
        _print_df(df_eoq[[c for c in cols if c in df_eoq.columns]],
                  max_rows=top)

    # ── 4. GMROI y Turnover ───────────────────────────────────────────────────
    _sep("4. GMROI y Rotacion de Inventario (anualizado)")
    gmroi_data = calcular_gmroi(top_n=top)
    res_gmroi  = gmroi_data.get("resumen", {})
    print(f"  Inventario total (costo) : ${res_gmroi.get('inventario_total_costo', 0):,.0f}")
    print(f"  Revenue anual estimado   : ${res_gmroi.get('revenue_anual_estimado', 0):,.0f}")
    print(f"  GMROI global             : {res_gmroi.get('gmroi_global', 0):.2f}x")
    print()
    if gmroi_data.get("data"):
        df_g = pd.DataFrame(gmroi_data["data"])
        cols = ["product_name", "abc", "inv_valor_costo",
                "gmroi", "inventory_turnover", "rev_anual_est"]
        _print_df(df_g[[c for c in cols if c in df_g.columns]],
                  max_rows=top, title=f"Top {top} productos por GMROI")

    _sep()
    _ok("Analisis de inventario completado.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="KAWII Analytics CLI",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--ticket",    action="store_true",
                        help="Solo analisis de ticket promedio")
    parser.add_argument("--inventory", action="store_true",
                        help="Solo analisis de inventario (ABC/XYZ/ROP/EOQ/GMROI)")
    parser.add_argument("--months",    type=int, default=12,
                        help="Meses de historial para ticket (default: 12)")
    parser.add_argument("--top",       type=int, default=30,
                        help="Maximo de filas a mostrar por tabla (default: 30)")
    args = parser.parse_args()

    run_ticket    = args.ticket or (not args.ticket and not args.inventory)
    run_inventory = args.inventory or (not args.ticket and not args.inventory)

    t_total = time.time()

    print()
    print("=" * 64)
    print("       KAWII -- Sistema de Analisis de Datos")
    print("=" * 64)
    print()

    if run_ticket:
        try:
            run_ticket_analysis(months=args.months, top=args.top)
        except Exception as exc:
            _error(f"Error en analisis de ticket: {exc}")
            import traceback
            traceback.print_exc()

    if run_inventory:
        try:
            run_inventory_analysis(top=args.top)
        except Exception as exc:
            _error(f"Error en analisis de inventario: {exc}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - t_total
    print()
    _sep()
    _ok(f"Analisis completo en {elapsed:.1f} segundos.")
    print()


if __name__ == "__main__":
    main()
