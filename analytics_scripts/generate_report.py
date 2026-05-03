"""
Genera el informe PDF completo de analisis KAWII.

Uso:
    cd produccion
    python analytics_scripts/generate_report.py
    python analytics_scripts/generate_report.py --output informe.pdf --months 12
"""

from __future__ import annotations

import argparse
import io
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Path setup ────────────────────────────────────────────────────────────────
_PRODUCCION = Path(__file__).resolve().parent.parent
if str(_PRODUCCION) not in sys.path:
    sys.path.insert(0, str(_PRODUCCION))

# ── Matplotlib backend no interactivo ────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ── ReportLab ─────────────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ─── Paleta KAWII ─────────────────────────────────────────────────────────────
C_PURPLE  = "#6D28D9"
C_PINK    = "#EC4899"
C_GREEN   = "#059669"
C_RED     = "#DC2626"
C_AMBER   = "#D97706"
C_BLUE    = "#2563EB"
C_GRAY    = "#6B7280"
C_LGRAY   = "#E5E7EB"
C_BGLIGHT = "#F5F3FF"
C_DARK    = "#1E1B4B"
C_WHITE   = "#FFFFFF"

_QUAD_COLORS = {
    "AX": "#059669", "AY": "#34D399", "AZ": "#F97316",
    "BX": "#3B82F6", "BY": "#93C5FD", "BZ": "#FCD34D",
    "CX": "#D1D5DB", "CY": "#9CA3AF", "CZ": "#FCA5A5",
}

# Dimensiones utiles A4 (con margenes 1.5cm c/lado)
_W_FULL = 17.0   # cm, ancho de contenido
_PAGE_W, _PAGE_H = A4


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS GLOBALES
# ─────────────────────────────────────────────────────────────────────────────

def _estilos():
    def s(**kw):
        kw.setdefault("fontName", "Helvetica")
        return ParagraphStyle(**kw)
    return {
        "titulo":    s(name="T",  fontSize=28, textColor=colors.HexColor(C_PURPLE),
                       alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=4),
        "subtitulo": s(name="S",  fontSize=13, textColor=colors.HexColor(C_GRAY),
                       alignment=TA_CENTER, spaceAfter=4),
        "h1":        s(name="H1", fontSize=15, textColor=colors.HexColor(C_PURPLE),
                       fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4),
        "h2":        s(name="H2", fontSize=11, textColor=colors.HexColor(C_DARK),
                       fontName="Helvetica-Bold", spaceBefore=5, spaceAfter=3),
        "body":      s(name="B",  fontSize=9,  textColor=colors.HexColor(C_DARK),
                       spaceAfter=3, leading=14),
        "small":     s(name="Sm", fontSize=8,  textColor=colors.HexColor(C_GRAY),
                       spaceAfter=2, leading=12),
        "alerta":    s(name="Al", fontSize=9,  textColor=colors.HexColor(C_RED),
                       fontName="Helvetica-Bold", spaceAfter=3),
        "exito":     s(name="Ex", fontSize=9,  textColor=colors.HexColor(C_GREEN),
                       fontName="Helvetica-Bold", spaceAfter=3),
        "footer":    s(name="F",  fontSize=7,  textColor=colors.HexColor(C_GRAY),
                       alignment=TA_CENTER),
    }


def _fig_to_rl(fig, w_cm: float = 17.0, h_cm: float = 8.0) -> RLImage:
    """Convierte figura matplotlib → RLImage. Usa tight_layout para evitar recortes."""
    try:
        fig.tight_layout(pad=0.5)
    except Exception:
        pass
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    buf.seek(0)
    plt.close(fig)
    return RLImage(buf, width=w_cm * cm, height=h_cm * cm)


def _ax_clean(ax, title="", xlabel="", ylabel=""):
    """Aplica el estilo limpio estandar a un eje."""
    ax.set_facecolor("#FAFAFE")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(C_LGRAY)
    ax.spines["bottom"].set_color(C_LGRAY)
    ax.grid(axis="y", color=C_LGRAY, linewidth=0.7, zorder=0)
    ax.tick_params(colors=C_GRAY, labelsize=8)
    if title:   ax.set_title(title,  fontsize=10, fontweight="bold", color=C_DARK, pad=6)
    if xlabel:  ax.set_xlabel(xlabel, fontsize=8.5, color=C_GRAY)
    if ylabel:  ax.set_ylabel(ylabel, fontsize=8.5, color=C_GRAY)


def _fmt_clp(x, _=None):
    if x >= 1_000_000: return f"${x/1e6:.1f}M"
    if x >= 1_000:     return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def _hr():
    return HRFlowable(width="100%", thickness=1,
                      color=colors.HexColor(C_LGRAY), spaceAfter=5)


def _sp(h=0.3):
    return Spacer(1, h * cm)


def _tbl_style_base(header_bg=C_PURPLE):
    return [
        ("BACKGROUND",     (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor(C_BGLIGHT), colors.white]),
        ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor(C_LGRAY)),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS (una sola vez, comparte entre todas las paginas)
# ─────────────────────────────────────────────────────────────────────────────

class _Datos:
    """Carga y cachea todos los datos para que el PDF no consulte la BD dos veces."""

    def __init__(self, months: int = 12):
        self.months = months

        print("  [1/3] Cargando analisis de ticket...")
        from analytics_scripts.ticket_analysis import tendencia_mensual
        from analytics_scripts.ticket_diagnostico import (
            waterfall_ticket, distribucion_ticket,
            mix_categorias_evolucion, ticket_por_dia_semana,
            productos_ancla, diagnostico_avanzado,
        )
        self.tm     = tendencia_mensual(months)
        self.diag_avanzado = diagnostico_avanzado(months)
        # Extraer sub-modulos del diagnostico (ya calculados, no recalcular)
        self.wf     = self.diag_avanzado["waterfall"]
        self.dist   = self.diag_avanzado["distribucion"]
        self.mix    = self.diag_avanzado["mix"]
        self.dias   = self.diag_avanzado["dias_semana"]
        self.anclas = self.diag_avanzado["productos_ancla"]

        print("  [2/3] Cargando analisis de inventario (puede tardar)...")
        from analytics_scripts.inventory_analysis import (
            calcular_abc_xyz, calcular_safety_stock_rop, calcular_gmroi,
        )
        self.abcxyz = calcular_abc_xyz()
        self.rop    = calcular_safety_stock_rop()
        self.gmroi  = calcular_gmroi(top_n=50)
        print("  [3/3] Datos listos.")


# ─────────────────────────────────────────────────────────────────────────────
# HEADER / FOOTER
# ─────────────────────────────────────────────────────────────────────────────

def _on_page(canvas, doc):
    w, h = A4
    canvas.saveState()
    # Header
    canvas.setStrokeColor(colors.HexColor(C_PURPLE))
    canvas.setLineWidth(1.5)
    canvas.line(1.5*cm, h - 1.15*cm, w - 1.5*cm, h - 1.15*cm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor(C_PURPLE))
    canvas.drawString(1.5*cm, h - 0.95*cm, "KAWII")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor(C_GRAY))
    canvas.drawRightString(w - 1.5*cm, h - 0.95*cm,
                           f"Informe de Analisis — {datetime.now().strftime('%B %Y')}")
    # Footer
    canvas.setStrokeColor(colors.HexColor(C_LGRAY))
    canvas.setLineWidth(0.5)
    canvas.line(1.5*cm, 1.15*cm, w - 1.5*cm, 1.15*cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor(C_GRAY))
    canvas.drawCentredString(w / 2, 0.8*cm,
                             f"Pagina {doc.page}  |  KAWII Analytics v1.0  |  Confidencial")
    canvas.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 1 — PORTADA
# ─────────────────────────────────────────────────────────────────────────────

def _portada(story, est, d: _Datos):
    story.append(_sp(2.5))
    story.append(Paragraph("KAWII", est["titulo"]))
    story.append(Paragraph("Informe de Analisis de Datos", est["subtitulo"]))
    story.append(Paragraph(
        f"Periodo: ultimos {d.months} meses  —  {datetime.now().strftime('%d/%m/%Y')}",
        est["subtitulo"],
    ))
    story.append(_sp(0.8))
    story.append(_hr())
    story.append(_sp(0.6))

    # KPI boxes ────────────────────────────────────────────────────────────────
    diag   = d.diag_avanzado
    wf_d   = diag.get("waterfall", {}).get("waterfall", {})
    res    = d.tm.get("resumen", {})
    bajo   = d.rop.get("total_bajo_rop", 0)
    delta  = float(wf_d.get("delta_total", 0))
    ultimo = float(res.get("ultimo_mes", 0))

    signo      = "+" if delta >= 0 else ""
    pct_cambio = round(delta / max(float(wf_d.get("ticket_inicio", 1)), 1) * 100, 1)
    c_delta    = C_GREEN if delta >= 0 else C_RED

    causa_txt = diag.get("causa_principal", "Ver informe")
    # Truncar si muy largo
    if len(causa_txt) > 28:
        causa_txt = causa_txt[:25] + "..."

    def _kpi(valor, etiqueta, color=C_PURPLE):
        estilo_v = ParagraphStyle("kv", fontName="Helvetica-Bold",
                                  fontSize=22, alignment=TA_CENTER,
                                  textColor=colors.HexColor(color))
        estilo_l = ParagraphStyle("kl", fontSize=8, alignment=TA_CENTER,
                                  textColor=colors.HexColor(C_GRAY), leading=10)
        return [Paragraph(str(valor), estilo_v),
                Paragraph(etiqueta,   estilo_l)]

    kpi_data = [[
        _kpi(f"${ultimo:,.0f}",           "Ticket Promedio Actual"),
        _kpi(f"{signo}{pct_cambio:.1f}%", f"Cambio ({d.months} meses)", c_delta),
        _kpi(causa_txt,                    "Causa Principal", C_AMBER),
        _kpi(str(bajo),                    "Productos Bajo ROP", C_RED),
    ]]
    kpi_tbl = Table(kpi_data, colWidths=[4.25*cm] * 4)
    kpi_tbl.setStyle(TableStyle([
        ("BOX",         (0,0), (-1,-1), 0.5, colors.HexColor(C_LGRAY)),
        ("INNERGRID",   (0,0), (-1,-1), 0.5, colors.HexColor(C_LGRAY)),
        ("BACKGROUND",  (0,0), (-1,-1), colors.HexColor(C_BGLIGHT)),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",  (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",(0,0),(-1,-1), 10),
    ]))
    story.append(kpi_tbl)
    story.append(_sp(0.8))

    # Diagnostico resumido
    diag_txt = diag.get("diagnostico", "")
    if diag_txt:
        story.append(Paragraph(f"<b>Diagnostico:</b> {diag_txt}", est["body"]))
    story.append(_sp(0.6))
    story.append(_hr())
    story.append(_sp(0.4))

    # Indice
    story.append(Paragraph("Contenido del Informe", est["h2"]))
    for num, sec in [
        ("1.", "Por que bajo el ticket — Waterfall de causas"),
        ("2.", "Distribucion del ticket (percentiles inicio vs reciente)"),
        ("3.", "Mix de categorias — categorias que arrastran el promedio"),
        ("4.", "Patron por dia de semana + Productos ancla perdidos"),
        ("5.", "Recomendaciones ejecutivas priorizadas"),
        ("6.", "Clasificacion ABC x XYZ de inventario"),
        ("7.", "Alertas de reposicion (Bajo ROP)"),
        ("8.", "GMROI y Rotacion de Inventario"),
    ]:
        story.append(Paragraph(f"<b>{num}</b>&nbsp;&nbsp;{sec}", est["body"]))

    story.append(_sp(1.0))
    story.append(Paragraph(
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  KAWII Analytics Engine v1.0",
        est["footer"],
    ))
    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 2 — WATERFALL: POR QUE BAJO EL TICKET
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_waterfall(story, est, d: _Datos):
    story.append(Paragraph("1. Por que bajo el Ticket Promedio — Descomposicion", est["h1"]))
    story.append(_hr())

    wf   = d.wf.get("waterfall", {})
    causa = d.wf.get("causa_principal", "N/A")
    perds = d.wf.get("periodos", [])

    if not wf:
        story.append(Paragraph("Datos insuficientes para calcular el waterfall.", est["small"]))
        story.append(PageBreak())
        return

    story.append(Paragraph(
        f"<b>Causa principal:</b> "
        f"<font color='{C_RED if 'bajo' in causa.lower() else C_AMBER}'>{causa}</font>",
        est["body"],
    ))
    story.append(_sp(0.3))

    # ── Tabla de periodos ────────────────────────────────────────────────────
    if perds:
        tbl_data = [["Periodo", "N Tickets", "Ticket Prom.", "Items/Ticket", "Precio Unit."]]
        for p in perds:
            tbl_data.append([
                str(p.get("periodo", "")),
                f"{int(p.get('n_tickets', 0)):,}",
                f"${float(p.get('ticket_promedio', 0)):,.0f}",
                f"{float(p.get('items_por_ticket', 0)):.2f}",
                f"${float(p.get('precio_unit_prom', 0)):,.0f}",
            ])
        tbl = Table(tbl_data, colWidths=[3*cm, 3*cm, 3.5*cm, 3.5*cm, 4*cm])
        tbl.setStyle(TableStyle(_tbl_style_base() + [
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]))
        story.append(tbl)
        story.append(_sp(0.4))

    # ── Grafico waterfall ────────────────────────────────────────────────────
    ticket_i = float(wf.get("ticket_inicio", 0))
    ticket_r = float(wf.get("ticket_reciente", 0))
    e_precio = float(wf.get("efecto_precio_puro", 0))
    e_mix    = float(wf.get("efecto_mix", 0))
    e_items  = float(wf.get("efecto_items", 0))
    e_inter  = float(wf.get("efecto_interaccion", 0))

    labels = ["Ticket\nInicio", "Ef. Precio\nPuro", "Ef. Mix\nCat.",
              "Ef. Items", "Interacc.", "Ticket\nActual"]
    pasos  = [ticket_i, e_precio, e_mix, e_items, e_inter, ticket_r]

    # Calcular bottoms para barras flotantes
    bottoms, running = [], ticket_i
    for i, v in enumerate(pasos):
        if i == 0:
            bottoms.append(0)
        elif i == len(pasos) - 1:
            bottoms.append(0)
        else:
            bottoms.append(running + v if v < 0 else running)
            running += v

    heights = [abs(v) for v in pasos]
    bcolors = [C_PURPLE] + [C_GREEN if v >= 0 else C_RED for v in pasos[1:-1]] + [C_PURPLE]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(range(len(pasos)), heights, bottom=bottoms,
                  color=bcolors, alpha=0.87, width=0.6, zorder=3)

    # Etiquetas dentro de las barras
    for i, (bar, val, bot) in enumerate(zip(bars, pasos, bottoms)):
        if abs(val) > ticket_i * 0.01:
            y = bot + abs(val) / 2
            lbl = f"${val:,.0f}" if i in (0, len(pasos)-1) else f"{val:+,.0f}"
            ax.text(bar.get_x() + bar.get_width()/2, y,
                    lbl, ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold", zorder=4)

    # Lineas de conexion entre barras
    run2 = ticket_i
    for i in range(1, len(pasos) - 1):
        ax.plot([i - 0.3, i + 0.9], [run2, run2],
                color=C_GRAY, lw=0.8, ls="--", alpha=0.45, zorder=2)
        run2 += pasos[i]

    _ax_clean(ax, "Descomposicion del Cambio en Ticket Promedio", ylabel="Monto ($)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_clp))

    # Leyenda
    legend_els = [
        mpatches.Patch(color=C_PURPLE, label="Total"),
        mpatches.Patch(color=C_GREEN,  label="Efecto positivo"),
        mpatches.Patch(color=C_RED,    label="Efecto negativo"),
    ]
    ax.legend(handles=legend_els, fontsize=8, framealpha=0.8, loc="upper right")

    story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=8.5))
    story.append(_sp(0.3))
    story.append(Paragraph(
        "<b>Como leer el waterfall:</b> Cada barra muestra cuanto de la variacion total "
        "del ticket se explica por ese factor. Rojo = efecto negativo. "
        "Verde = efecto positivo. La suma de todas las barras del medio debe igualar "
        "la diferencia entre 'Ticket Inicio' y 'Ticket Actual'.",
        est["small"],
    ))
    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 3 — DISTRIBUCION DEL TICKET
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_distribucion(story, est, d: _Datos):
    story.append(Paragraph("2. Distribucion del Ticket — Percentiles", est["h1"]))
    story.append(_hr())

    dist   = d.dist
    interp = dist.get("interpretacion", "")
    pcts_d = dist.get("cambios_pct", {})
    datos  = dist.get("data", [])

    story.append(Paragraph(
        f"<b>Interpretacion:</b> {interp}" if interp else "Sin datos de distribucion.",
        est["body"],
    ))
    story.append(_sp(0.3))

    if not datos or len(datos) < 2:
        story.append(Paragraph("Datos insuficientes.", est["small"]))
        story.append(PageBreak())
        return

    df_dist = pd.DataFrame(datos)
    pcts = ["p10", "p25", "p50", "p75", "p90", "p95"]
    pcts_exist = [p for p in pcts if p in df_dist.columns]

    # ── Grafico: percentiles inicio vs reciente ────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.5))

    # Chart izquierdo: barras comparativas por percentil
    if pcts_exist:
        row_i = df_dist[df_dist["periodo"] == "inicio"].iloc[0] if "inicio" in df_dist["periodo"].values else None
        row_r = df_dist[df_dist["periodo"] == "reciente"].iloc[0] if "reciente" in df_dist["periodo"].values else None

        if row_i is not None and row_r is not None:
            vals_i = [float(row_i[p]) for p in pcts_exist]
            vals_r = [float(row_r[p]) for p in pcts_exist]
            x = np.arange(len(pcts_exist))
            w = 0.38
            bars_i = ax1.bar(x - w/2, vals_i, w, color=C_BLUE,   alpha=0.75, label="Inicio")
            bars_r = ax1.bar(x + w/2, vals_r, w, color=C_PURPLE, alpha=0.85, label="Reciente")

            # Flechas de cambio
            for xi, vi, vr in zip(x, vals_i, vals_r):
                if abs(vi) > 0:
                    cambio = (vr - vi) / vi * 100
                    color_arrow = C_GREEN if cambio >= 0 else C_RED
                    ax1.annotate(f"{cambio:+.0f}%",
                                 xy=(xi + w/2, vr),
                                 xytext=(xi + w/2, max(vr, vi) + max(vals_i)*0.04),
                                 fontsize=7, color=color_arrow, ha="center",
                                 fontweight="bold")

            _ax_clean(ax1, "Percentiles: Inicio vs Reciente", ylabel="Monto ($)")
            ax1.set_xticks(x)
            ax1.set_xticklabels([p.upper() for p in pcts_exist], fontsize=8.5)
            ax1.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_clp))
            ax1.legend(fontsize=8)

    # Chart derecho: tabla visual de variaciones
    if pcts_d:
        pct_labels = [p.upper() for p in pcts if p in pcts_d]
        pct_vals   = [pcts_d.get(p, 0) for p in pcts if p in pcts_d]
        bar_c = [C_GREEN if v >= 0 else C_RED for v in pct_vals]
        ax2.barh(pct_labels, pct_vals, color=bar_c, alpha=0.85)
        ax2.axvline(0, color=C_DARK, lw=0.8)
        for i, v in enumerate(pct_vals):
            ax2.text(v + (max(pct_vals, default=1)*0.02),
                     i, f"{v:+.1f}%",
                     va="center", ha="left" if v >= 0 else "right",
                     fontsize=8, color=C_DARK, fontweight="bold")
        _ax_clean(ax2, "Variacion % Inicio -> Reciente", xlabel="Cambio %")

    story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=8.0))
    story.append(_sp(0.3))

    # Tabla resumen
    if len(datos) >= 2:
        cols_tbl = ["periodo", "n_tickets", "promedio", "p25", "p50", "p75", "p90"]
        cols_tbl = [c for c in cols_tbl if c in df_dist.columns]
        tbl_data = [["Periodo" if c=="periodo" else c.upper() for c in cols_tbl]]
        for _, row in df_dist.iterrows():
            fila = []
            for c in cols_tbl:
                v = row.get(c, "")
                if c == "n_tickets":
                    fila.append(f"{int(v):,}" if v else "-")
                elif c == "periodo":
                    fila.append(str(v))
                else:
                    fila.append(f"${float(v):,.0f}" if v else "-")
            tbl_data.append(fila)
        col_ws = [3*cm] + [2.3*cm] * (len(cols_tbl) - 1)
        tbl = Table(tbl_data, colWidths=col_ws)
        tbl.setStyle(TableStyle(_tbl_style_base() + [
            ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ]))
        story.append(tbl)

    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 4 — MIX DE CATEGORIAS
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_mix_categorias(story, est, d: _Datos):
    story.append(Paragraph("3. Mix de Categorias — Categorias que Arrastran el Ticket", est["h1"]))
    story.append(_hr())

    arrastran = d.mix.get("categorias_que_arrastran", [])
    mejoran   = d.mix.get("categorias_que_mejoran",   [])
    cambios   = d.mix.get("cambios", [])

    story.append(Paragraph(
        "Las categorias tipo <b>ARRASTRA</b> ganaron participacion pero tienen precio unitario "
        "bajo, lo que tira el ticket promedio hacia abajo. "
        "Las tipo <b>MEJORA</b> tienen el efecto opuesto.",
        est["body"],
    ))
    story.append(_sp(0.3))

    if not cambios:
        story.append(Paragraph("Sin datos de mix.", est["small"]))
        story.append(PageBreak())
        return

    df_cambios = pd.DataFrame(cambios).dropna(subset=["delta_share"])
    df_cambios = df_cambios.sort_values("delta_share")

    # ── Grafico: delta share por categoria ───────────────────────────────────
    top_n = 18
    df_plot = pd.concat([
        df_cambios.head(top_n // 2),
        df_cambios.tail(top_n // 2),
    ]).drop_duplicates()

    fig, ax = plt.subplots(figsize=(10, max(5.0, len(df_plot) * 0.45 + 1.0)))
    cats    = [str(c)[:32] for c in df_plot["categoria"]]
    shares  = df_plot["delta_share"].astype(float) * 100   # en %
    barcols = []
    for _, row in df_plot.iterrows():
        imp = row.get("impacto", "NEUTRAL")
        barcols.append(C_RED if imp == "ARRASTRA" else
                       (C_GREEN if imp == "MEJORA" else C_GRAY))

    ax.barh(cats, shares, color=barcols, alpha=0.85)
    ax.axvline(0, color=C_DARK, lw=0.8)
    _ax_clean(ax, "Cambio en Participacion de Revenue (puntos porcentuales)",
              xlabel="Delta Share (%)")

    legend_els = [
        mpatches.Patch(color=C_RED,   label="ARRASTRA (gano share, precio bajo)"),
        mpatches.Patch(color=C_GREEN, label="MEJORA (efecto positivo)"),
        mpatches.Patch(color=C_GRAY,  label="NEUTRAL"),
    ]
    ax.legend(handles=legend_els, fontsize=8, framealpha=0.8)
    story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=min(10.0, len(df_plot) * 0.55 + 1.5)))

    story.append(_sp(0.4))

    # Tabla: top categorias que arrastran
    if arrastran:
        story.append(Paragraph("Categorias ARRASTRA (mayor impacto negativo):", est["h2"]))
        tbl_data = [["Categoria", "Share Inicio", "Share Reciente", "Delta Share", "Precio Unit."]]
        for r in arrastran[:8]:
            tbl_data.append([
                str(r.get("categoria", ""))[:28],
                f"{float(r.get('share_i', 0))*100:.1f}%",
                f"{float(r.get('share_r', 0))*100:.1f}%",
                f"{float(r.get('delta_share', 0))*100:+.1f}%",
                f"${float(r.get('precio_i', 0)):,.0f}",
            ])
        tbl = Table(tbl_data, colWidths=[5.5*cm, 3*cm, 3*cm, 3*cm, 2.5*cm])
        ts  = TableStyle(_tbl_style_base(header_bg=C_RED) + [
            ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ])
        tbl.setStyle(ts)
        story.append(tbl)

    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 5 — DIA DE SEMANA + PRODUCTOS ANCLA
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_dia_semana_anclas(story, est, d: _Datos):
    story.append(Paragraph("4. Patron por Dia de Semana + Productos Ancla", est["h1"]))
    story.append(_hr())

    # ── 4a. Dia de semana ────────────────────────────────────────────────────
    dias_data = d.dias.get("data", [])
    mejor     = d.dias.get("mejor_dia", "—")
    peor      = d.dias.get("peor_dia", "—")
    story.append(Paragraph(
        f"<b>Mejor dia:</b> {mejor} &nbsp;|&nbsp; <b>Peor dia:</b> {peor}. "
        "Los dias con ticket muy bajo respecto a la media pueden estar influenciados "
        "por tipo de clientela o menor disponibilidad de personal.",
        est["body"],
    ))
    story.append(_sp(0.25))

    if dias_data:
        df_dias = pd.DataFrame(dias_data)
        fig, ax = plt.subplots(figsize=(9, 3.8))
        dias_labels = [str(r.get("dia", r.get("dia_num", ""))) for r in dias_data]
        tickets_val = df_dias["ticket_promedio"].astype(float)
        avg_g = float(d.dias.get("avg_global", tickets_val.mean()))
        bar_c = [C_GREEN if float(r.get("vs_global_pct", 0)) >= 0 else C_RED
                 for r in dias_data]
        ax.bar(dias_labels, tickets_val, color=bar_c, alpha=0.85)
        ax.axhline(avg_g, color=C_PURPLE, lw=1.5, ls="--",
                   label=f"Media: {_fmt_clp(avg_g)}")
        for i, v in enumerate(tickets_val):
            ax.text(i, v + avg_g * 0.01, f"${v:,.0f}",
                    ha="center", va="bottom", fontsize=7.5, color=C_DARK)
        _ax_clean(ax, "Ticket Promedio por Dia de Semana", ylabel="Ticket ($)")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_clp))
        ax.legend(fontsize=8)
        story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=5.5))

    story.append(_sp(0.5))

    # ── 4b. Productos ancla ──────────────────────────────────────────────────
    story.append(Paragraph("4b. Productos Ancla con Mayor Perdida de Participacion", est["h2"]))
    story.append(Paragraph(
        "Productos de alto precio unitario (sobre la mediana) que perdieron participacion "
        "de revenue. Al reducir su share, arrastran el precio unitario promedio hacia abajo.",
        est["small"],
    ))
    story.append(_sp(0.2))

    anclas = d.anclas.get("anclas_perdidas", [])
    n_comp = d.anclas.get("n_productos_comparados", 0)
    med_p  = d.anclas.get("precio_mediana", 0)
    story.append(Paragraph(
        f"Productos comparados: <b>{n_comp}</b>  |  "
        f"Precio mediana de referencia: <b>${float(med_p):,.0f}</b>  |  "
        f"Anclas identificadas: <b>{len(anclas)}</b>",
        est["small"],
    ))
    story.append(_sp(0.2))

    if anclas:
        tbl_data = [["Producto", "Categoria", "Precio Unit.", "Share Inicio", "Share Actual", "Delta"]]
        for a in anclas[:10]:
            tbl_data.append([
                str(a.get("product_name", ""))[:30],
                str(a.get("categoria", ""))[:18],
                f"${float(a.get('precio_i', 0)):,.0f}",
                f"{float(a.get('share_i', 0))*100:.2f}%",
                f"{float(a.get('share_r', 0))*100:.2f}%",
                f"{float(a.get('delta_share', 0))*100:+.2f}%",
            ])
        tbl = Table(tbl_data,
                    colWidths=[5.5*cm, 3.2*cm, 2.5*cm, 2.5*cm, 2.5*cm, 1.8*cm])
        ts = TableStyle(_tbl_style_base(header_bg=C_AMBER) + [
            ("ALIGN",    (2,0), (-1,-1), "CENTER"),
            ("TEXTCOLOR",(5,1), (5,-1),  colors.HexColor(C_RED)),
            ("FONTNAME", (5,1), (5,-1),  "Helvetica-Bold"),
        ])
        tbl.setStyle(ts)
        story.append(tbl)
    else:
        story.append(Paragraph("No se identificaron productos ancla con perdida significativa.", est["small"]))

    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 6 — RECOMENDACIONES
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_recomendaciones(story, est, d: _Datos):
    story.append(Paragraph("5. Recomendaciones Ejecutivas Priorizadas", est["h1"]))
    story.append(_hr())

    prioridades = d.diag_avanzado.get("prioridades", [])
    causa       = d.diag_avanzado.get("causa_principal", "N/A")
    diagnostico = d.diag_avanzado.get("diagnostico", "")

    story.append(Paragraph(
        f"<b>Causa principal:</b> <font color='{C_RED}'>{causa}</font>",
        est["body"],
    ))
    if diagnostico:
        story.append(Paragraph(diagnostico, est["body"]))
    story.append(_sp(0.5))

    if prioridades:
        story.append(Paragraph("Acciones Priorizadas por Magnitud de Impacto:", est["h2"]))
        tbl_data = [["#", "Causa Identificada", "Impacto Est.", "Accion Recomendada"]]
        for p in prioridades:
            mag = p.get("magnitud_clp")
            mag_str = f"${abs(float(mag)):,.0f}" if mag else "—"
            tbl_data.append([
                str(p.get("orden", "")),
                str(p.get("causa", ""))[:38],
                mag_str,
                str(p.get("accion", ""))[:42],
            ])
        tbl = Table(tbl_data, colWidths=[1*cm, 6.5*cm, 2.5*cm, 7*cm])
        ts  = TableStyle(_tbl_style_base() + [
            ("ALIGN",    (0,0), (0,-1), "CENTER"),
            ("ALIGN",    (2,0), (2,-1), "CENTER"),
            ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
        ])
        tbl.setStyle(ts)
        story.append(tbl)

    story.append(_sp(0.6))
    story.append(Paragraph("Plan de Accion Detallado", est["h2"]))
    plan_rows = [
        ["Alta",  "Revisar precios de productos premium — buscar erosion de margen",
                  "Aumento precio unitario promedio en 5-15%"],
        ["Alta",  "Cross-selling en punto de venta — entrenamiento equipo",
                  "Aumento items/ticket en 10-20%"],
        ["Media", "Impulsar categorias de alto valor (position, display, promo)",
                  "Rebalancear mix hacia categorias MEJORA"],
        ["Media", "Reactivar los productos ancla perdidos (disponibilidad + visibilidad)",
                  "Recuperar share de productos de alto precio"],
        ["Baja",  "Revisar dias de bajo ticket — ajustar personal y oferta",
                  "Homogeneizar ticket a lo largo de la semana"],
    ]
    plan_data = [["Prioridad", "Accion", "Objetivo"]] + plan_rows
    tbl2 = Table(plan_data, colWidths=[2*cm, 8.5*cm, 6.5*cm])
    col_p = {0: C_RED, 1: C_RED, 2: C_AMBER, 3: C_AMBER, 4: C_BLUE}
    ts2 = TableStyle(_tbl_style_base() + [
        *[("TEXTCOLOR", (0, i+1), (0, i+1), colors.HexColor(c))
          for i, c in col_p.items()],
        ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
    ])
    tbl2.setStyle(ts2)
    story.append(tbl2)
    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 7 — ABC × XYZ
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_abc_xyz(story, est, d: _Datos):
    story.append(Paragraph("6. Clasificacion ABC x XYZ de Inventario", est["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "La matriz ABC x XYZ combina la importancia economica (ABC) con la "
        "predictibilidad de la demanda (XYZ) para priorizar la gestion.",
        est["body"],
    ))
    story.append(_sp(0.3))

    res_quad  = d.abcxyz.get("resumen", [])
    quad_dict = {r["abc_xyz"]: r for r in res_quad}

    abc_rows   = ["A", "B", "C"]
    xyz_cols   = ["X", "Y", "Z"]
    lab_row    = ["A (80%\nRevenue)", "B (15%\nRevenue)", "C (5%\nRevenue)"]
    lab_col    = ["X\n(Estable)", "Y\n(Variable)", "Z\n(Erratica)"]

    fig, (ax_m, ax_b) = plt.subplots(1, 2, figsize=(12, 5.0),
                                      gridspec_kw={"width_ratios": [1.1, 1]})

    for i, abc in enumerate(abc_rows):
        for j, xyz in enumerate(xyz_cols):
            quad  = abc + xyz
            info  = quad_dict.get(quad, {})
            cnt   = info.get("productos", 0)
            rev   = float(info.get("revenue_90d_total", 0))
            c_hex = _QUAD_COLORS.get(quad, C_LGRAY)
            rect  = mpatches.FancyBboxPatch(
                (j, 2-i), 1, 1,
                boxstyle="round,pad=0.04", lw=1.5,
                edgecolor="white", facecolor=c_hex,
            )
            ax_m.add_patch(rect)
            ax_m.text(j+0.5, 2-i+0.68, quad,
                      ha="center", va="center",
                      fontsize=13, fontweight="bold", color="white")
            ax_m.text(j+0.5, 2-i+0.38, f"{cnt} prod.",
                      ha="center", va="center", fontsize=8, color="white")
            rev_s = f"${rev/1e6:.1f}M" if rev >= 1e6 else f"${rev/1e3:.0f}K"
            ax_m.text(j+0.5, 2-i+0.10, rev_s,
                      ha="center", va="center", fontsize=8,
                      color="white", fontweight="bold")

    ax_m.set_xlim(0, 3); ax_m.set_ylim(0, 3)
    ax_m.set_xticks([0.5, 1.5, 2.5]); ax_m.set_xticklabels(lab_col, fontsize=8.5)
    ax_m.set_yticks([0.5, 1.5, 2.5]); ax_m.set_yticklabels(lab_row[::-1], fontsize=8.5)
    ax_m.set_facecolor("#FAFAFE"); ax_m.spines[:].set_visible(False)
    ax_m.tick_params(length=0)
    ax_m.set_title("Matriz ABC x XYZ", fontsize=10, fontweight="bold", color=C_DARK)
    ax_m.set_xlabel("Variabilidad (XYZ)", fontsize=8.5, color=C_GRAY)
    ax_m.set_ylabel("Importancia Economica (ABC)", fontsize=8.5, color=C_GRAY)

    # Bar chart revenue por cuadrante
    if res_quad:
        df_q   = pd.DataFrame(res_quad).sort_values("revenue_90d_total", ascending=False).head(9)
        quads  = df_q["abc_xyz"].tolist()
        revs   = df_q["revenue_90d_total"].astype(float).tolist()
        bcols  = [_QUAD_COLORS.get(q, C_GRAY) for q in quads]
        bars   = ax_b.bar(quads, revs, color=bcols, alpha=0.88)
        for bar, v in zip(bars, revs):
            ax_b.text(bar.get_x() + bar.get_width()/2,
                      bar.get_height() * 1.02,
                      f"${v/1e3:.0f}K", ha="center", va="bottom",
                      fontsize=8, fontweight="bold", color=C_DARK)
        _ax_clean(ax_b, "Revenue 90d por Cuadrante", ylabel="Revenue (CLP)")
        ax_b.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"${x/1e3:.0f}K"))

    story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=7.5))
    story.append(_sp(0.3))

    leyenda_data = [
        ["Cuadrante", "Descripcion",                        "Estrategia"],
        ["AX",        "Critico rentable y predecible",       "Mantener stock, SS minimo"],
        ["AY",        "Critico rentable y variable",         "Safety Stock medio-alto"],
        ["AZ",        "Critico rentable y erratico",         "Vigilar, SS alto"],
        ["BX/BY/BZ",  "Importante",                          "Tratamiento estandar"],
        ["CX/CY",     "Bajo valor predecible",               "Reducir stock"],
        ["CZ",        "Bajo valor erratico",                 "Considerar discontinuar"],
    ]
    tbl = Table(leyenda_data, colWidths=[2.5*cm, 7.5*cm, 7*cm])
    tbl.setStyle(TableStyle(_tbl_style_base(C_DARK) + [
        ("ALIGN", (0,0), (0,-1), "CENTER"),
        ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
        *[("TEXTCOLOR", (0, i+1), (0, i+1),
           colors.HexColor(_QUAD_COLORS.get(str(leyenda_data[i+1][0]).split("/")[0], C_GRAY)))
          for i in range(6)],
    ]))
    story.append(tbl)
    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 8 — ALERTAS ROP
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_rop(story, est, d: _Datos):
    story.append(Paragraph("7. Alertas de Reposicion — Bajo ROP", est["h1"]))
    story.append(_hr())

    params = d.rop.get("parametros", {})
    total  = d.rop.get("total_bajo_rop", 0)
    story.append(Paragraph(
        f"Se detectaron <font color='{C_RED}'><b>{total} productos</b></font> "
        f"con stock por debajo del Reorder Point. "
        f"Nivel de servicio: {params.get('nivel_servicio','95%')}, "
        f"lead time: {params.get('lead_time_d',7)} dias, z={params.get('z',1.65)}.",
        est["body"],
    ))
    story.append(_sp(0.3))

    df_all = pd.DataFrame(d.rop.get("data", []))
    if not df_all.empty:
        bajo  = df_all[df_all["estado_stock"] == "BAJO ROP - REORDENAR"].copy()
        bajo  = bajo.sort_values("rop", ascending=False).head(15)

        if not bajo.empty:
            fig, ax = plt.subplots(figsize=(10, max(5.0, len(bajo) * 0.52 + 0.8)))
            names   = [str(n)[:28] for n in bajo["product_name"]]
            rop_v   = bajo["rop"].astype(float)
            stk_v   = bajo["stock_total"].astype(float)
            y       = range(len(names))

            ax.barh(y, rop_v,  color=C_RED,  alpha=0.22, label="ROP requerido", zorder=2)
            ax.barh(y, stk_v, color=C_BLUE, alpha=0.85, label="Stock actual",   zorder=3)

            for i, (r, s) in enumerate(zip(rop_v, stk_v)):
                def_v = r - s
                ax.text(max(r, s) * 1.015, i,
                        f"-{def_v:.0f}", va="center", ha="left",
                        fontsize=7.5, color=C_RED, fontweight="bold")

            ax.set_yticks(list(y))
            ax.set_yticklabels(names, fontsize=8)
            _ax_clean(ax, f"Top {len(bajo)} Productos Bajo ROP — Stock Actual vs Necesario",
                      xlabel="Unidades")
            ax.legend(fontsize=8.5, loc="lower right")
            story.append(_fig_to_rl(fig, w_cm=_W_FULL,
                                    h_cm=min(11.0, len(bajo)*0.58 + 1.2)))

    story.append(_sp(0.3))
    story.append(Paragraph("Top 10 productos con reposicion mas urgente:", est["h2"]))
    alertas = d.rop.get("alertas", [])[:10]
    if alertas:
        tbl_data = [["Producto", "ABC", "Stock", "ROP", "Deficit"]]
        for a in alertas:
            stk = float(a.get("stock_total", 0))
            rop = float(a.get("rop", 0))
            tbl_data.append([
                str(a.get("product_name", ""))[:36],
                str(a.get("abc", "—")),
                f"{stk:.0f}",
                f"{rop:.0f}",
                f"{rop - stk:.0f}",
            ])
        tbl = Table(tbl_data, colWidths=[8*cm, 1.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        ts  = TableStyle(_tbl_style_base(C_RED) + [
            ("ALIGN",    (1,0), (-1,-1), "CENTER"),
            ("TEXTCOLOR",(4,1), (4,-1),  colors.HexColor(C_RED)),
            ("FONTNAME", (4,1), (4,-1),  "Helvetica-Bold"),
        ])
        tbl.setStyle(ts)
        story.append(tbl)
    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# PAGINA 9 — GMROI
# ─────────────────────────────────────────────────────────────────────────────

def _pagina_gmroi(story, est, d: _Datos):
    story.append(Paragraph("8. GMROI y Rotacion de Inventario", est["h1"]))
    story.append(_hr())

    res_g = d.gmroi.get("resumen", {})
    story.append(Paragraph(
        f"GMROI global: <b>{float(res_g.get('gmroi_global', 0)):.2f}x</b>  |  "
        f"Inventario a costo: <b>${float(res_g.get('inventario_total_costo', 0)):,.0f}</b>  |  "
        f"Revenue anual est.: <b>${float(res_g.get('revenue_anual_estimado', 0)):,.0f}</b>",
        est["body"],
    ))
    story.append(Paragraph(
        "GMROI > 1.0 significa que cada peso invertido en inventario genera mas de 1 peso "
        "de margen bruto. Turnover alto indica inventario que rota rapido (saludable).",
        est["small"],
    ))
    story.append(_sp(0.3))

    df_g = pd.DataFrame(d.gmroi.get("data", []))
    if not df_g.empty and "gmroi" in df_g.columns:
        df_g["gmroi"] = pd.to_numeric(df_g["gmroi"], errors="coerce")
        df_g = df_g.dropna(subset=["gmroi"])

        df_top = df_g.sort_values("gmroi", ascending=False).head(15)

        fig, (ax_b, ax_s) = plt.subplots(1, 2, figsize=(13, 6.5))

        # Bar chart GMROI
        abc_cmap = {"A": C_PURPLE, "B": C_BLUE, "C": C_GRAY}
        bcols    = [abc_cmap.get(str(a), C_GRAY)
                    for a in df_top.get("abc", ["C"]*len(df_top))]
        names    = [str(n)[:25] for n in df_top["product_name"]]
        ax_b.barh(range(len(df_top)), df_top["gmroi"].astype(float),
                  color=bcols, alpha=0.85)
        ax_b.axvline(1.0, color=C_RED, lw=1.5, ls="--",
                     label="GMROI = 1 (break-even)")
        ax_b.set_yticks(range(len(df_top)))
        ax_b.set_yticklabels(names, fontsize=7.5)
        _ax_clean(ax_b, "Top 15 Productos por GMROI", xlabel="GMROI (x)")
        ax_b.legend(fontsize=8)

        # Scatter GMROI vs Turnover
        if "inventory_turnover" in df_g.columns:
            df_g["inventory_turnover"] = pd.to_numeric(
                df_g["inventory_turnover"], errors="coerce")
            df_sc = df_g.dropna(subset=["gmroi", "inventory_turnover"])
            p95   = df_sc["gmroi"].quantile(0.95)
            df_sc = df_sc[df_sc["gmroi"] < p95]
            sc_c  = [abc_cmap.get(str(a), C_GRAY)
                     for a in df_sc.get("abc", pd.Series(["C"]*len(df_sc)))]
            ax_s.scatter(
                df_sc["inventory_turnover"].astype(float),
                df_sc["gmroi"].astype(float),
                c=sc_c, alpha=0.55, s=30,
                edgecolors="white", lw=0.4, zorder=3,
            )
            ax_s.axhline(1.0, color=C_RED, lw=1, ls="--", alpha=0.5)
            med_turn = float(df_sc["inventory_turnover"].median())
            ax_s.axvline(med_turn, color=C_GRAY, lw=1, ls="--", alpha=0.5,
                         label=f"Mediana turnover: {med_turn:.1f}x")
            _ax_clean(ax_s, "GMROI vs Rotacion de Inventario",
                      xlabel="Turnover (veces/ano)", ylabel="GMROI")
            leg_els = [
                mpatches.Patch(color=C_PURPLE, label="Clase A"),
                mpatches.Patch(color=C_BLUE,   label="Clase B"),
                mpatches.Patch(color=C_GRAY,   label="Clase C"),
            ]
            ax_s.legend(handles=leg_els + ax_s.lines[:1], fontsize=8)

        story.append(_fig_to_rl(fig, w_cm=_W_FULL, h_cm=9.5))

    story.append(_sp(0.3))
    story.append(Paragraph("Top 8 productos por GMROI:", est["h2"]))
    if not df_g.empty:
        df_t8 = df_g.sort_values("gmroi", ascending=False).head(8)
        tbl_data = [["Producto", "ABC", "Inv. Costo", "GMROI", "Turnover"]]
        for _, r in df_t8.iterrows():
            tbl_data.append([
                str(r.get("product_name", ""))[:36],
                str(r.get("abc", "—")),
                f"${float(r.get('inv_valor_costo', 0)):,.0f}",
                f"{float(r.get('gmroi', 0)):.2f}x",
                f"{float(r.get('inventory_turnover', 0)):.1f}x",
            ])
        tbl = Table(tbl_data, colWidths=[8*cm, 1.5*cm, 3*cm, 2.5*cm, 2*cm])
        tbl.setStyle(TableStyle(_tbl_style_base() + [
            ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ]))
        story.append(tbl)

    story.append(PageBreak())


# ─────────────────────────────────────────────────────────────────────────────
# GENERADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def generar_pdf(output_path: str = "informe_kawii.pdf", months: int = 12) -> str:
    """
    Genera el informe PDF completo y retorna la ruta absoluta del archivo.

    Args:
        output_path : nombre o ruta del archivo de salida
        months      : meses de historial para el analisis de ticket
    """
    output = Path(output_path)
    if not output.is_absolute():
        output = _PRODUCCION / output_path

    print(f"\nGenerando informe PDF: {output}")
    print("=" * 60)

    # 1) Datos
    datos = _Datos(months=months)

    # 2) Documento
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.8*cm,  bottomMargin=1.8*cm,
        title=f"KAWII — Informe de Analisis {datetime.now().strftime('%B %Y')}",
        author="KAWII Analytics Engine",
        subject="Ticket Promedio + Inventario",
    )

    # 3) Story
    est   = _estilos()
    story = []

    secs = [
        ("Portada",              _portada),
        ("Waterfall de causas",  _pagina_waterfall),
        ("Distribucion ticket",  _pagina_distribucion),
        ("Mix categorias",       _pagina_mix_categorias),
        ("Dia semana + anclas",  _pagina_dia_semana_anclas),
        ("Recomendaciones",      _pagina_recomendaciones),
        ("ABC x XYZ",            _pagina_abc_xyz),
        ("Alertas ROP",          _pagina_rop),
        ("GMROI",                _pagina_gmroi),
    ]
    for i, (nombre, fn) in enumerate(secs, 1):
        print(f"    [{i}/{len(secs)}] {nombre}...")
        fn(story, est, datos)

    # 4) Compilar
    print("  Compilando PDF...")
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

    size_kb = output.stat().st_size // 1024
    print(f"\n  PDF listo: {output}  ({size_kb} KB | ~{len(secs)} paginas)")
    print("=" * 60)
    return str(output)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="KAWII PDF Report Generator")
    parser.add_argument("--output", default="informe_kawii.pdf",
                        help="Archivo de salida (default: informe_kawii.pdf)")
    parser.add_argument("--months", type=int, default=12,
                        help="Meses de historial (default: 12)")
    args   = parser.parse_args()
    ruta   = generar_pdf(output_path=args.output, months=args.months)
    print(f"\nListo. Abre el archivo: {ruta}")


if __name__ == "__main__":
    main()
