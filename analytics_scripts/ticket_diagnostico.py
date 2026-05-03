"""
Diagnostico avanzado de causa raiz para la caida del ticket promedio.

Logica propia con descomposicion cuantitativa tipo Laspeyres:

  1. waterfall_ticket()         -> Cuanto del cambio viene de Precio / Mix / Items
  2. distribucion_ticket()      -> Percentiles P10-P95: inicio vs reciente
  3. mix_categorias_evolucion() -> Categorias que ganaron/perdieron share en revenue
  4. ticket_por_dia_semana()    -> Patron por dia de semana
  5. productos_ancla()          -> Productos de alto valor que perdieron participacion
  6. diagnostico_avanzado()     -> Veredicto ejecutivo con causas priorizadas

Metodologia de comparacion:
  - Primeros _COMPARE_MONTHS meses = periodo "inicio"
  - Ultimos  _COMPARE_MONTHS meses = periodo "reciente"
  - La diferencia entre ambos es lo que se descompone.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from analytics_scripts.config import OFFICE_IDS
from analytics_scripts.db_helper import get_df

logger = logging.getLogger("kawii.analytics.ticket_diag")

_OFFICE_FILTER  = f"doc.bsale_office_id IN ({', '.join(str(i) for i in OFFICE_IDS)})"
_COMPARE_MONTHS = 3   # meses comparados: primeros N vs ultimos N del periodo


# ─── 1. Waterfall ─────────────────────────────────────────────────────────────

def waterfall_ticket(months: int = 12) -> dict[str, Any]:
    """
    Descomposicion cuantitativa del cambio en ticket promedio (Laspeyres).

      delta_ticket = efecto_precio_puro + efecto_mix_categorias
                   + efecto_items       + efecto_interaccion

    - efecto_precio_puro  : los mismos productos se venden mas baratos / caros
    - efecto_mix_categorias: cambio de la canasta hacia categorias de distinto precio
    - efecto_items        : el cliente compra mas / menos articulos por visita
    - efecto_interaccion  : termino de segundo orden (items x precio simultaneamente)

    Compara primeros {cm} meses vs ultimos {cm} meses del horizonte.
    """
    cm = min(_COMPARE_MONTHS, months // 3)

    # ── Metricas por ticket por periodo ───────────────────────────────────────
    sql_t = f"""
        WITH doc_agg AS (
            SELECT
                doc.bsale_document_id,
                doc.total_amount                                            AS monto,
                CASE
                    WHEN doc.emission_date >= NOW() - INTERVAL '{months} months'
                     AND doc.emission_date  < NOW() - INTERVAL '{months - cm} months'
                    THEN 'inicio'
                    WHEN doc.emission_date >= NOW() - INTERVAL '{cm} months'
                    THEN 'reciente'
                END                                                         AS periodo,
                SUM(dd.quantity)                                            AS items,
                SUM(dd.total_amount)::float / NULLIF(SUM(dd.quantity), 0)  AS precio_unit
            FROM documents doc
            JOIN document_details dd ON dd.bsale_document_id = doc.bsale_document_id
            WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND COALESCE(doc.is_active,      TRUE)  = TRUE
              AND {_OFFICE_FILTER}
            GROUP BY doc.bsale_document_id, doc.total_amount, doc.emission_date
        )
        SELECT
            periodo,
            COUNT(*)::int                                    AS n_tickets,
            ROUND(AVG(monto)::numeric,       0)              AS ticket_promedio,
            ROUND(AVG(items)::numeric,       2)              AS items_por_ticket,
            ROUND(AVG(precio_unit)::numeric, 0)              AS precio_unit_prom
        FROM doc_agg
        WHERE periodo IS NOT NULL
        GROUP BY periodo
    """

    # ── Share de unidades y precio unitario por categoria y periodo ───────────
    sql_c = f"""
        WITH cat_agg AS (
            SELECT
                CASE
                    WHEN doc.emission_date >= NOW() - INTERVAL '{months} months'
                     AND doc.emission_date  < NOW() - INTERVAL '{months - cm} months'
                    THEN 'inicio'
                    WHEN doc.emission_date >= NOW() - INTERVAL '{cm} months'
                    THEN 'reciente'
                END                                                         AS periodo,
                COALESCE(vpf.category, 'Sin categoria')                     AS categoria,
                SUM(dd.quantity)                                            AS unidades,
                SUM(dd.total_amount)::float / NULLIF(SUM(dd.quantity), 0)  AS precio_unit
            FROM document_details dd
            JOIN documents doc   ON doc.bsale_document_id = dd.bsale_document_id
            JOIN variants   v    ON v.bsale_variant_id    = dd.bsale_variant_id
            JOIN v_products_full vpf ON vpf.bsale_product_id = v.bsale_product_id
            WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND COALESCE(doc.is_active,      TRUE)  = TRUE
              AND {_OFFICE_FILTER}
            GROUP BY periodo, categoria
        ),
        totales AS (
            SELECT periodo, SUM(unidades) AS total_u
            FROM cat_agg WHERE periodo IS NOT NULL GROUP BY periodo
        )
        SELECT
            c.periodo,
            c.categoria,
            c.unidades,
            c.precio_unit,
            c.unidades::float / t.total_u AS share
        FROM cat_agg c
        JOIN totales t ON t.periodo = c.periodo
        WHERE c.periodo IS NOT NULL
        ORDER BY c.periodo, c.unidades DESC
    """

    df_t = get_df(sql_t)
    df_c = get_df(sql_c)

    if (df_t.empty
            or "inicio"   not in df_t["periodo"].values
            or "reciente" not in df_t["periodo"].values):
        return {"error": "Datos insuficientes para el waterfall",
                "waterfall": {}, "periodos": []}

    ri = df_t[df_t["periodo"] == "inicio"].iloc[0]
    rr = df_t[df_t["periodo"] == "reciente"].iloc[0]

    ticket_i = float(ri["ticket_promedio"])
    ticket_r = float(rr["ticket_promedio"])
    items_i  = float(ri["items_por_ticket"])
    items_r  = float(rr["items_por_ticket"])
    precio_i = float(ri["precio_unit_prom"])
    precio_r = float(rr["precio_unit_prom"])

    delta_total     = ticket_r - ticket_i
    efecto_items    = (items_r - items_i) * precio_i
    efecto_precio_t = (precio_r - precio_i) * items_i
    efecto_inter    = (items_r - items_i) * (precio_r - precio_i)

    # Laspeyres: separar efecto precio puro de efecto mix de categorias
    efecto_mix   = 0.0
    efecto_ppuro = efecto_precio_t

    if not df_c.empty:
        ci   = df_c[df_c["periodo"] == "inicio"].set_index("categoria")
        cr   = df_c[df_c["periodo"] == "reciente"].set_index("categoria")
        cats = ci.index.intersection(cr.index)
        if len(cats) >= 2:
            si = ci.loc[cats, "share"].values.astype(float)
            sr = cr.loc[cats, "share"].values.astype(float)
            pi = ci.loc[cats, "precio_unit"].values.astype(float)
            pr = cr.loc[cats, "precio_unit"].values.astype(float)
            si = si / si.sum() if si.sum() > 0 else si
            sr = sr / sr.sum() if sr.sum() > 0 else sr
            efecto_mix   = float(np.dot(sr - si, pi)) * items_i   # mix
            efecto_ppuro = float(np.dot(si, pr - pi)) * items_i   # precio puro

    causas = {
        "precio_puro":    efecto_ppuro,
        "mix_categorias": efecto_mix,
        "items":          efecto_items,
    }
    causa_key = min(causas, key=causas.get)
    causa_map = {
        "precio_puro":    "PRECIO — Los productos se venden mas baratos",
        "mix_categorias": "MIX — Mayor participacion de categorias de menor precio",
        "items":          "VOLUMEN — El cliente compra menos articulos por visita",
    }

    return {
        "periodos":  df_t.replace({np.nan: None}).to_dict("records"),
        "waterfall": {
            "ticket_inicio":      round(ticket_i, 0),
            "ticket_reciente":    round(ticket_r, 0),
            "delta_total":        round(delta_total, 0),
            "efecto_precio_puro": round(efecto_ppuro, 0),
            "efecto_mix":         round(efecto_mix, 0),
            "efecto_items":       round(efecto_items, 0),
            "efecto_interaccion": round(efecto_inter, 0),
        },
        "causa_principal": causa_map.get(causa_key, "COMBINADO"),
        "mix_categorias":  df_c.replace({np.nan: None}).to_dict("records"),
        "parametros":      {"meses_analisis": months, "meses_comparados": cm},
    }


# ─── 2. Distribucion del ticket ────────────────────────────────────────────────

def distribucion_ticket(months: int = 12) -> dict[str, Any]:
    """
    Compara la distribucion estadistica de los montos de ticket
    entre el periodo inicial y el reciente.

    Percentiles: P10, P25, P50 (mediana), P75, P90, P95.
    Tambien distribucion por buckets:
      micro (<25% del p50 inicial), bajo (25-75% del p50), medio, alto, premium.

    Permite detectar:
    - Si bajo la MEDIANA -> la mayoria de clientes gasta menos
    - Si bajo P90/P95   -> los clientes premium gastan menos
    - Si bajo P10       -> hay mas transacciones muy pequenas
    """
    cm = min(_COMPARE_MONTHS, months // 3)

    sql = f"""
        WITH clasificados AS (
            SELECT
                doc.total_amount,
                CASE
                    WHEN doc.emission_date >= NOW() - INTERVAL '{months} months'
                     AND doc.emission_date  < NOW() - INTERVAL '{months - cm} months'
                    THEN 'inicio'
                    WHEN doc.emission_date >= NOW() - INTERVAL '{cm} months'
                    THEN 'reciente'
                END AS periodo
            FROM documents doc
            WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND COALESCE(doc.is_active,      TRUE)  = TRUE
              AND {_OFFICE_FILTER}
        )
        SELECT
            periodo,
            COUNT(*)::int                                                                  AS n_tickets,
            ROUND(AVG(total_amount)::numeric,   0)                                        AS promedio,
            ROUND(STDDEV(total_amount)::numeric, 0)                                       AS desviacion,
            ROUND(PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p10,
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p25,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p50,
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p75,
            ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p90,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_amount)::numeric, 0) AS p95
        FROM clasificados
        WHERE periodo IS NOT NULL
        GROUP BY periodo
        ORDER BY periodo
    """
    df = get_df(sql)

    if df.empty or len(df) < 2:
        return {"data": [], "cambios_pct": {}, "interpretacion": "Datos insuficientes"}

    ri = df[df["periodo"] == "inicio"].iloc[0]
    rr = df[df["periodo"] == "reciente"].iloc[0]

    pcts = ["p10", "p25", "p50", "p75", "p90", "p95"]
    cambios = {}
    for p in pcts:
        vi = float(ri[p]) if ri[p] else 0
        vr = float(rr[p]) if rr[p] else 0
        cambios[p] = round((vr - vi) / vi * 100, 1) if vi > 0 else 0.0

    # Detectar el segmento mas afectado
    pct_peor = min(cambios, key=cambios.get)
    interp_map = {
        "p10": "Los tickets mas baratos crecieron en proporcion (mas micro-transacciones)",
        "p25": "El cuartil inferior se contrajo (mas clientes con ticket bajo)",
        "p50": "La MEDIANA bajo: la mayoria de clientes gasta menos por visita",
        "p75": "El cuartil superior se redujo (clientes de ticket medio-alto gastan menos)",
        "p90": "Los mejores clientes (top 10%) gastan menos por visita",
        "p95": "Los clientes premium (top 5%) redujeron su ticket",
    }
    interpretacion = (
        interp_map.get(pct_peor, "")
        if cambios[pct_peor] < -2
        else "La distribucion de tickets se mantuvo estable o mejoro"
    )

    return {
        "data":                    df.replace({np.nan: None}).to_dict("records"),
        "cambios_pct":             cambios,
        "percentil_mas_afectado":  pct_peor,
        "interpretacion":          interpretacion,
    }


# ─── 3. Mix de categorias por mes ─────────────────────────────────────────────

def mix_categorias_evolucion(months: int = 12) -> dict[str, Any]:
    """
    Evolucion mensual del share de revenue por categoria.
    Compara la participacion inicio vs reciente y clasifica cada categoria:

    ARRASTRA : gano participacion pero tiene precio unitario bajo (baja el promedio)
    MEJORA   : gano participacion y tiene precio unitario alto (sube el promedio)
    NEUTRAL  : cambio minimo o precio cercano a la media
    """
    cm = min(_COMPARE_MONTHS, months // 3)

    sql = f"""
        WITH mensual AS (
            SELECT
                DATE_TRUNC('month', doc.emission_date)::date                AS mes,
                COALESCE(vpf.category, 'Sin categoria')                     AS categoria,
                SUM(dd.total_amount)                                        AS revenue,
                SUM(dd.quantity)                                            AS unidades,
                SUM(dd.total_amount)::float / NULLIF(SUM(dd.quantity), 0)  AS precio_unit
            FROM document_details dd
            JOIN documents doc   ON doc.bsale_document_id = dd.bsale_document_id
            JOIN variants   v    ON v.bsale_variant_id    = dd.bsale_variant_id
            JOIN v_products_full vpf ON vpf.bsale_product_id = v.bsale_product_id
            WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND COALESCE(doc.is_active,      TRUE)  = TRUE
              AND {_OFFICE_FILTER}
            GROUP BY 1, 2
        ),
        total_mes AS (
            SELECT mes, SUM(revenue) AS total_rev
            FROM mensual GROUP BY mes
        )
        SELECT
            m.mes,
            m.categoria,
            m.revenue,
            m.unidades,
            m.precio_unit,
            m.revenue::float / t.total_rev AS share_revenue
        FROM mensual m
        JOIN total_mes t ON t.mes = m.mes
        ORDER BY m.mes, m.revenue DESC
    """
    df = get_df(sql)
    if df.empty:
        return {"data_mensual": [], "cambios": [],
                "categorias_que_arrastran": [], "categorias_que_mejoran": []}

    meses = sorted(df["mes"].unique())
    n     = len(meses)
    m_ini = meses[: min(cm, n // 2)]
    m_rec = meses[-min(cm, n // 2):]

    def _agregar(filtro_meses):
        sub = df[df["mes"].isin(filtro_meses)]
        agg = sub.groupby("categoria").agg(
            revenue=("revenue", "sum"),
            unidades=("unidades", "sum"),
        ).reset_index()
        agg["precio"] = agg["revenue"] / agg["unidades"].replace(0, np.nan)
        total = agg["revenue"].sum()
        agg["share"] = agg["revenue"] / total if total > 0 else 0.0
        return agg.set_index("categoria")

    ini_df = _agregar(m_ini)
    rec_df = _agregar(m_rec)

    todas = ini_df.index.union(rec_df.index)
    comparativo = pd.DataFrame(index=todas)
    comparativo["revenue_i"]  = ini_df.get("revenue",  pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["revenue_r"]  = rec_df.get("revenue",  pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["precio_i"]   = ini_df.get("precio",   pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["precio_r"]   = rec_df.get("precio",   pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["share_i"]    = ini_df.get("share",    pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["share_r"]    = rec_df.get("share",    pd.Series(dtype=float)).reindex(todas).fillna(0)
    comparativo["delta_share"]   = (comparativo["share_r"] - comparativo["share_i"]).round(4)
    comparativo["delta_precio"]  = (comparativo["precio_r"] - comparativo["precio_i"]).round(0)
    comparativo.index.name = "categoria"
    comparativo = comparativo.reset_index()

    avg_precio = float(comparativo["precio_i"].replace(0, np.nan).mean()) or 1.0

    def _impacto(row):
        gano  = row["delta_share"] >  0.005
        perdio = row["delta_share"] < -0.005
        barato = row["precio_i"] < avg_precio * 0.85
        caro   = row["precio_i"] > avg_precio * 1.15
        if   (gano  and barato) or (perdio and caro):  return "ARRASTRA"
        elif (gano  and caro)   or (perdio and barato): return "MEJORA"
        return "NEUTRAL"

    comparativo["impacto"] = comparativo.apply(_impacto, axis=1)
    comparativo = comparativo.sort_values("delta_share")

    return {
        "data_mensual":             df.replace({np.nan: None}).to_dict("records"),
        "cambios":                  comparativo.replace({np.nan: None}).to_dict("records"),
        "categorias_que_arrastran": comparativo[comparativo["impacto"] == "ARRASTRA"].replace({np.nan: None}).to_dict("records"),
        "categorias_que_mejoran":   comparativo[comparativo["impacto"] == "MEJORA"].replace({np.nan: None}).to_dict("records"),
    }


# ─── 4. Patron por dia de semana ──────────────────────────────────────────────

def ticket_por_dia_semana(months: int = 6) -> dict[str, Any]:
    """
    Ticket promedio y volumen de tickets por dia de la semana.
    Identifica si hay dias "problema" que arrastran el promedio semanal.
    """
    sql = f"""
        SELECT
            EXTRACT(DOW FROM doc.emission_date)::int          AS dia_num,
            COUNT(DISTINCT doc.bsale_document_id)::int         AS tickets,
            ROUND(AVG(doc.total_amount)::numeric,  0)          AS ticket_promedio,
            ROUND(SUM(doc.total_amount)::numeric,  0)          AS revenue_total,
            ROUND(STDDEV(doc.total_amount)::numeric, 0)        AS desviacion
        FROM documents doc
        WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
        GROUP BY 1
        ORDER BY 1
    """
    df = get_df(sql)
    if df.empty:
        return {"data": [], "mejor_dia": None, "peor_dia": None}

    dias_es = {0: "Domingo", 1: "Lunes", 2: "Martes", 3: "Miercoles",
               4: "Jueves", 5: "Viernes", 6: "Sabado"}
    df["dia"] = df["dia_num"].map(dias_es)

    avg = float(df["ticket_promedio"].mean())
    df["vs_global_pct"] = ((df["ticket_promedio"] / avg - 1) * 100).round(1)
    df["alerta"] = df["vs_global_pct"].apply(
        lambda x: "BAJO" if x < -10 else ("ALTO" if x > 10 else "NORMAL")
    )

    mejor = df.loc[df["ticket_promedio"].idxmax(), "dia"]
    peor  = df.loc[df["ticket_promedio"].idxmin(), "dia"]

    return {
        "data":       df.replace({np.nan: None}).to_dict("records"),
        "avg_global": round(avg, 0),
        "mejor_dia":  mejor,
        "peor_dia":   peor,
        "meses":      months,
    }


# ─── 5. Productos ancla perdidos ──────────────────────────────────────────────

def productos_ancla(months: int = 12, top_n: int = 20) -> dict[str, Any]:
    """
    Identifica los productos de alto valor que PERDIERON participacion.
    Estos "anclas" de ticket, al perder share, arrastran el promedio hacia abajo.

    Criterio: precio_unitario > mediana del periodo inicial
              Y perdieron mas del 0.5% de share de revenue.
    """
    cm = min(_COMPARE_MONTHS, months // 3)

    sql = f"""
        WITH prod_per AS (
            SELECT
                vpf.bsale_product_id,
                vpf.product_name,
                COALESCE(vpf.category, 'Sin categoria')                     AS categoria,
                CASE
                    WHEN doc.emission_date >= NOW() - INTERVAL '{months} months'
                     AND doc.emission_date  < NOW() - INTERVAL '{months - cm} months'
                    THEN 'inicio'
                    WHEN doc.emission_date >= NOW() - INTERVAL '{cm} months'
                    THEN 'reciente'
                END                                                          AS periodo,
                SUM(dd.total_amount)                                         AS revenue,
                SUM(dd.quantity)                                             AS unidades,
                SUM(dd.total_amount)::float / NULLIF(SUM(dd.quantity), 0)   AS precio_unit
            FROM document_details dd
            JOIN documents doc   ON doc.bsale_document_id = dd.bsale_document_id
            JOIN variants   v    ON v.bsale_variant_id    = dd.bsale_variant_id
            JOIN v_products_full vpf ON vpf.bsale_product_id = v.bsale_product_id
            WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
              AND COALESCE(doc.is_credit_note, FALSE) = FALSE
              AND COALESCE(doc.is_active,      TRUE)  = TRUE
              AND {_OFFICE_FILTER}
            GROUP BY vpf.bsale_product_id, vpf.product_name, vpf.category, periodo
        ),
        totales AS (
            SELECT periodo, SUM(revenue) AS total_rev
            FROM prod_per WHERE periodo IS NOT NULL GROUP BY periodo
        )
        SELECT
            pp.bsale_product_id,
            pp.product_name,
            pp.categoria,
            pp.periodo,
            pp.revenue,
            pp.unidades,
            pp.precio_unit,
            pp.revenue::float / t.total_rev AS share_revenue
        FROM prod_per pp
        JOIN totales t ON t.periodo = pp.periodo
        WHERE pp.periodo IS NOT NULL
        ORDER BY pp.periodo, pp.revenue DESC
    """
    df = get_df(sql)
    if df.empty:
        return {"anclas_perdidas": [], "top_perdieron": [],
                "top_ganaron": [], "precio_mediana": 0}

    ini = df[df["periodo"] == "inicio"].set_index("bsale_product_id")
    rec = df[df["periodo"] == "reciente"].set_index("bsale_product_id")
    comunes = ini.index.intersection(rec.index)

    if len(comunes) == 0:
        return {"anclas_perdidas": [], "top_perdieron": [],
                "top_ganaron": [], "precio_mediana": 0}

    comp = pd.DataFrame({
        "bsale_product_id": comunes,
        "product_name": ini.loc[comunes, "product_name"],
        "categoria":    ini.loc[comunes, "categoria"],
        "precio_i":     ini.loc[comunes, "precio_unit"].astype(float),
        "precio_r":     rec.loc[comunes, "precio_unit"].astype(float),
        "revenue_i":    ini.loc[comunes, "revenue"].astype(float),
        "revenue_r":    rec.loc[comunes, "revenue"].astype(float),
        "share_i":      ini.loc[comunes, "share_revenue"].astype(float),
        "share_r":      rec.loc[comunes, "share_revenue"].astype(float),
    })
    comp["delta_share"]      = (comp["share_r"]  - comp["share_i"]).round(4)
    comp["delta_revenue"]    = (comp["revenue_r"] - comp["revenue_i"]).round(0)
    comp["delta_precio_pct"] = (
        (comp["precio_r"] - comp["precio_i"]) /
        comp["precio_i"].replace(0, np.nan) * 100
    ).round(1)

    mediana_precio = float(comp["precio_i"].median())

    anclas = (
        comp[
            (comp["precio_i"] > mediana_precio) &
            (comp["delta_share"] < -0.005)
        ]
        .nlargest(top_n, "revenue_i")
        .replace({np.nan: None})
        .to_dict("records")
    )
    ganaron   = comp.nlargest(top_n // 2, "delta_revenue").replace({np.nan: None}).to_dict("records")
    perdieron = comp.nsmallest(top_n // 2, "delta_revenue").replace({np.nan: None}).to_dict("records")

    return {
        "anclas_perdidas":         anclas,
        "top_ganaron":             ganaron,
        "top_perdieron":           perdieron,
        "precio_mediana":          round(mediana_precio, 0),
        "n_productos_comparados":  len(comunes),
    }


# ─── 6. Diagnostico avanzado consolidado ─────────────────────────────────────

def diagnostico_avanzado(months: int = 12) -> dict[str, Any]:
    """
    Consolida los 5 modulos y devuelve:
    - diagnostico       : parrafo ejecutivo con la causa raiz
    - causa_principal   : etiqueta corta de la causa
    - prioridades       : lista ordenada de acciones con magnitud cuantificada
    - modulos completos : waterfall, distribucion, mix, dias_semana, anclas
    """
    logger.info("Iniciando diagnostico avanzado (ultimos %d meses)...", months)
    wf   = waterfall_ticket(months)
    dist = distribucion_ticket(months)
    mix  = mix_categorias_evolucion(months)
    dias = ticket_por_dia_semana(min(months, 6))
    anc  = productos_ancla(months)

    wf_data = wf.get("waterfall", {})
    delta   = float(wf_data.get("delta_total", 0))
    causa   = wf.get("causa_principal", "INDETERMINADO")

    lineas = []
    prioridades = []

    if delta < 0:
        ticket_i = float(wf_data.get("ticket_inicio", 1)) or 1
        pct_caida = abs(delta) / ticket_i * 100
        lineas.append(
            f"El ticket promedio bajo {abs(delta):,.0f} ({pct_caida:.1f}%) "
            f"comparando los primeros {wf.get('parametros',{}).get('meses_comparados',3)} meses "
            f"del periodo vs los mas recientes."
        )
        lineas.append(f"Causa principal identificada: {causa}.")

        epuro = float(wf_data.get("efecto_precio_puro", 0))
        emix  = float(wf_data.get("efecto_mix", 0))
        eitems = float(wf_data.get("efecto_items", 0))

        efectos = [
            ("efecto_precio_puro", epuro, "Precio unitario promedio bajo",
             "Revisar politica de precios y visibilidad de productos premium"),
            ("efecto_mix",         emix,  "Mix de categorias desplazado hacia productos baratos",
             "Impulsar categorias de alto valor (promotions, visibilidad)"),
            ("efecto_items",       eitems,"Clientes compran menos articulos por visita",
             "Implementar cross-selling y bundles en punto de venta"),
        ]
        for orden, (key, val, causa_txt, accion) in enumerate(
            sorted(efectos, key=lambda e: e[1]), start=1
        ):
            if val < -50:
                prioridades.append({
                    "orden":       orden,
                    "causa":       causa_txt,
                    "magnitud_clp": round(val, 0),
                    "accion":      accion,
                })

        dist_interp = dist.get("interpretacion", "")
        if dist_interp and "insuficientes" not in dist_interp.lower():
            lineas.append(dist_interp)

        n_anclas = len(anc.get("anclas_perdidas", []))
        if n_anclas > 0:
            prioridades.append({
                "orden":       len(prioridades) + 1,
                "causa":       f"{n_anclas} productos de alto valor perdieron participacion en ventas",
                "magnitud_clp": None,
                "accion":      "Reactivar visibilidad y disponibilidad de productos ancla",
            })

        arrastran = mix.get("categorias_que_arrastran", [])
        if arrastran:
            cats = ", ".join(c["categoria"] for c in arrastran[:3])
            prioridades.append({
                "orden":       len(prioridades) + 1,
                "causa":       f"Categorias baratas ganaron share: {cats}",
                "magnitud_clp": None,
                "accion":      "Reducir visibilidad de categorias de bajo margen o crear combos con alto valor",
            })

        peor_dia = dias.get("peor_dia", "")
        mejor_dia = dias.get("mejor_dia", "")
        if peor_dia and mejor_dia:
            lineas.append(
                f"Patron semanal: mejor ticket el {mejor_dia}, peor ticket el {peor_dia}."
            )
    else:
        lineas.append(
            f"El ticket promedio subio {delta:,.0f} en el periodo analizado. "
            "No se detecta una caida significativa."
        )
        prioridades.append({
            "orden": 1, "causa": "Tendencia positiva",
            "magnitud_clp": round(delta, 0),
            "accion": "Mantener y reforzar las practicas actuales",
        })

    return {
        "diagnostico":     " ".join(lineas),
        "causa_principal": causa,
        "prioridades":     prioridades,
        "waterfall":       wf,
        "distribucion":    dist,
        "mix":             mix,
        "dias_semana":     dias,
        "productos_ancla": anc,
    }
