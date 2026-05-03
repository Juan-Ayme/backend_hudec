"""
Analisis del Ticket Promedio (Average Transaction Value - ATV).

Responde: ¿Por que esta bajando el ticket promedio?

Modulos:
  1. tendencia_mensual()      → evolucion mes a mes con variacion %
  2. analisis_sucursales()    → ticket promedio por sucursal
  3. profundidad_ticket()     → items por ticket (¿se compra menos por visita?)
  4. ticket_por_categoria()   → que categoria "arrastra" el promedio hacia abajo
  5. diagnostico_completo()   → consolida todo + emite recomendaciones

Cada funcion devuelve:
  - Un dict con la clave "data" (list[dict]) para la API
  - Un DataFrame en df_* para visualizacion en consola / Jupyter
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from analytics_scripts.config import OFFICE_IDS
from analytics_scripts.db_helper import get_df, get_scalar

# Clausula SQL reutilizable para filtrar solo las sucursales activas
_OFFICE_FILTER = f"doc.bsale_office_id IN ({', '.join(str(i) for i in OFFICE_IDS)})"

logger = logging.getLogger("kawii.analytics.ticket")


# ─── 1. Tendencia mensual ──────────────────────────────────────────────────────

def tendencia_mensual(months: int = 12) -> dict[str, Any]:
    """
    Evolucion mensual del ticket promedio.

    Columnas devueltas:
      mes, venta_total, tickets, ticket_promedio,
      var_ticket_pct (variacion % vs mes anterior),
      estado ('SUBE' | 'BAJA' | 'ESTABLE')
    """
    sql = f"""
        SELECT
            DATE_TRUNC('month', doc.emission_date)::date          AS mes,
            ROUND(SUM(doc.total_amount)::numeric, 0)              AS venta_total,
            COUNT(DISTINCT doc.bsale_document_id)                 AS tickets,
            ROUND(
                SUM(doc.total_amount)::numeric /
                NULLIF(COUNT(DISTINCT doc.bsale_document_id), 0),
            0)                                                    AS ticket_promedio
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
        return {"data": [], "resumen": {}}

    # Variacion porcentual mes a mes
    df["var_ticket_pct"] = (
        df["ticket_promedio"]
        .pct_change()
        .mul(100)
        .round(1)
    )

    # Estado
    def _estado(v):
        if pd.isna(v):
            return "BASE"
        if v > 2:
            return "SUBE"
        if v < -2:
            return "BAJA"
        return "ESTABLE"

    df["estado"] = df["var_ticket_pct"].apply(_estado)

    # Resumen estadistico
    valores = df["ticket_promedio"].dropna()
    resumen = {
        "min":        float(valores.min()),
        "max":        float(valores.max()),
        "promedio":   float(valores.mean().round(0)),
        "ultimo_mes": float(df["ticket_promedio"].iloc[-1]),
        "primer_mes": float(df["ticket_promedio"].iloc[0]),
        "cambio_total_pct": float(
            ((df["ticket_promedio"].iloc[-1] / df["ticket_promedio"].iloc[0]) - 1) * 100
        ),
        "meses_a_la_baja": int((df["estado"] == "BAJA").sum()),
        "meses_al_alza":   int((df["estado"] == "SUBE").sum()),
    }

    return {
        "data": df.replace({np.nan: None}).to_dict("records"),
        "resumen": resumen,
    }


# ─── 2. Analisis por sucursal ──────────────────────────────────────────────────

def analisis_sucursales(days: int = 180) -> dict[str, Any]:
    """
    Ticket promedio por sucursal en los ultimos N dias.
    Identifica si el problema es puntual (1 tienda) o generalizado.
    """
    sql = f"""
        SELECT
            COALESCE(o.name, 'Sin sucursal')              AS sucursal,
            COUNT(DISTINCT doc.bsale_document_id)          AS tickets,
            ROUND(SUM(doc.total_amount)::numeric, 0)       AS venta_total,
            ROUND(AVG(doc.total_amount)::numeric, 0)       AS ticket_promedio,
            ROUND(
                100.0 * ROUND(AVG(doc.total_amount)::numeric, 0) /
                NULLIF(SUM(ROUND(AVG(doc.total_amount)::numeric, 0))
                       OVER (), 0),
            1)                                             AS pct_del_total
        FROM documents doc
        LEFT JOIN offices o ON o.bsale_office_id = doc.bsale_office_id
        WHERE doc.emission_date >= NOW() - INTERVAL '{days} days'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
        GROUP BY o.name
        ORDER BY ticket_promedio DESC
    """
    df = get_df(sql)
    if df.empty:
        return {"data": []}

    avg_global = float(
        (df["venta_total"].sum() / df["tickets"].sum()).round(0)
    )
    df["vs_global_pct"] = (
        (df["ticket_promedio"] / avg_global - 1) * 100
    ).round(1)
    df["alerta"] = df["vs_global_pct"].apply(
        lambda x: "POR DEBAJO" if x < -10 else ("SOBRE MEDIA" if x > 10 else "NORMAL")
    )

    return {
        "data":        df.replace({np.nan: None}).to_dict("records"),
        "avg_global":  avg_global,
        "dias":        days,
    }


# ─── 3. Profundidad del ticket ─────────────────────────────────────────────────

def profundidad_ticket(months: int = 12) -> dict[str, Any]:
    """
    Evolucion de:
      - Ticket promedio (monto)
      - Items por ticket (unidades / venta)
      - Precio unitario promedio (ticket / items)

    Si items_por_ticket baja → el cliente compra menos articulos.
    Si precio_unitario baja → se venden productos mas baratos.
    Ambos pueden ocurrir a la vez.
    """
    sql = f"""
        SELECT
            DATE_TRUNC('month', doc.emission_date)::date    AS mes,
            ROUND(AVG(doc.total_amount)::numeric, 0)        AS ticket_promedio,
            ROUND(AVG(items.total_items), 2)                AS items_por_ticket,
            ROUND(
                AVG(doc.total_amount)::numeric /
                NULLIF(AVG(items.total_items), 0),
            0)                                             AS precio_unitario_prom
        FROM documents doc
        JOIN (
            SELECT bsale_document_id, SUM(quantity) AS total_items
            FROM document_details
            GROUP BY bsale_document_id
        ) items ON items.bsale_document_id = doc.bsale_document_id
        WHERE doc.emission_date >= NOW() - INTERVAL '{months} months'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
        GROUP BY 1
        ORDER BY 1
    """
    df = get_df(sql)
    if df.empty:
        return {"data": [], "diagnostico": "Sin datos"}

    # Calcular cambio total de cada metrica
    def _pct_change_total(col: str) -> float:
        first = df[col].iloc[0]
        last  = df[col].iloc[-1]
        if first == 0:
            return 0.0
        return float(((last / first) - 1) * 100)

    cambio_ticket = _pct_change_total("ticket_promedio")
    cambio_items  = _pct_change_total("items_por_ticket")
    cambio_precio = _pct_change_total("precio_unitario_prom")

    # Diagnostico automatico de causa raiz
    if cambio_items < -5 and cambio_precio < -5:
        diagnostico = (
            "DOBLE PROBLEMA: el cliente compra MENOS articulos (%.1f%%) "
            "Y los articulos son mas BARATOS (%.1f%%). "
            "Revisar mix de productos y politica de precios."
            % (cambio_items, cambio_precio)
        )
    elif cambio_items < -5:
        diagnostico = (
            "PROFUNDIDAD: el cliente compra MENOS articulos por visita (%.1f%%). "
            "Trabajar en cross-selling / upselling en tienda."
            % cambio_items
        )
    elif cambio_precio < -5:
        diagnostico = (
            "PRECIO: se venden productos mas BARATOS (%.1f%%). "
            "El mix de categorias se mueve hacia articulos de menor valor."
            % cambio_precio
        )
    else:
        diagnostico = "Ticket promedio ESTABLE. No hay caida significativa detectada."

    df["var_items_pct"]  = df["items_por_ticket"].pct_change().mul(100).round(1)
    df["var_precio_pct"] = df["precio_unitario_prom"].pct_change().mul(100).round(1)
    df["var_ticket_pct"] = df["ticket_promedio"].pct_change().mul(100).round(1)

    return {
        "data":          df.replace({np.nan: None}).to_dict("records"),
        "cambios": {
            "ticket_pct":       round(cambio_ticket, 1),
            "items_pct":        round(cambio_items,  1),
            "precio_prom_pct":  round(cambio_precio, 1),
        },
        "diagnostico": diagnostico,
    }


# ─── 4. Ticket por categoria ───────────────────────────────────────────────────

def ticket_por_categoria(days: int = 180) -> dict[str, Any]:
    """
    Ticket promedio de linea (monto por linea de venta) por categoria.
    Usa v_products_full para respetar overrides individuales.

    Revela: ¿que categoria "arrastra" el promedio global hacia abajo?
    """
    sql = f"""
        SELECT
            vpf.department                                         AS departamento,
            vpf.category                                           AS categoria,
            COUNT(DISTINCT doc.bsale_document_id)                  AS tickets,
            ROUND(SUM(dd.total_amount)::numeric, 0)                AS venta_total,
            ROUND(AVG(dd.total_amount)::numeric, 0)                AS ticket_prom_linea,
            ROUND(AVG(dd.quantity), 2)                             AS unidades_por_linea,
            ROUND(
                SUM(dd.total_amount)::numeric /
                NULLIF(SUM(dd.quantity), 0),
            0)                                                     AS precio_unitario_prom
        FROM document_details dd
        JOIN documents    doc ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants     v   ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN v_products_full vpf ON vpf.bsale_product_id = v.bsale_product_id
        WHERE doc.emission_date >= NOW() - INTERVAL '{days} days'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
          AND vpf.department IS NOT NULL
        GROUP BY vpf.department, vpf.category
        ORDER BY venta_total DESC
    """
    df = get_df(sql)
    if df.empty:
        return {"data": []}

    avg_global = float(df["ticket_prom_linea"].mean().round(0))
    df["vs_global_pct"] = (
        (df["ticket_prom_linea"] / avg_global - 1) * 100
    ).round(1)
    df["peso_en_ventas_pct"] = (
        df["venta_total"] / df["venta_total"].sum() * 100
    ).round(1)
    df["alerta"] = df["vs_global_pct"].apply(
        lambda x: "ARRASTRA" if x < -20 else ("IMPULSA" if x > 20 else "NORMAL")
    )

    # Top 5 que arrastran
    arrastran = (
        df[df["alerta"] == "ARRASTRA"]
        .nsmallest(5, "ticket_prom_linea")[["categoria", "ticket_prom_linea", "peso_en_ventas_pct"]]
        .to_dict("records")
    )

    return {
        "data":         df.replace({np.nan: None}).to_dict("records"),
        "avg_global":   avg_global,
        "top_arrastran": arrastran,
        "dias":          days,
    }


# ─── 5. Diagnostico completo ───────────────────────────────────────────────────

def diagnostico_completo(months: int = 12) -> dict[str, Any]:
    """
    Consolida todas las analisis y emite un diagnostico ejecutivo.
    """
    tm   = tendencia_mensual(months)
    suc  = analisis_sucursales(months * 30)
    prof = profundidad_ticket(months)
    cat  = ticket_por_categoria(months * 30)

    res  = tm.get("resumen", {})
    cambios = prof.get("cambios", {})

    # Construir recomendaciones
    recomendaciones = []

    if res.get("cambio_total_pct", 0) < -5:
        recomendaciones.append(
            f"El ticket promedio bajo {abs(res['cambio_total_pct']):.1f}% en {months} meses. Requiere atencion."
        )

    if res.get("meses_a_la_baja", 0) >= 3:
        recomendaciones.append(
            f"Tendencia negativa consistente: {res['meses_a_la_baja']} meses consecutivos a la baja."
        )

    if cambios.get("items_pct", 0) < -5:
        recomendaciones.append(
            "Cross-selling debil: el cliente compra menos items por visita. "
            "Implementar sugerencias en punto de venta."
        )

    if cambios.get("precio_prom_pct", 0) < -5:
        recomendaciones.append(
            "Mix de precios a la baja: se venden mas productos economicos. "
            "Revisar visibilidad de productos de mayor valor."
        )

    # Sucursales con ticket bajo
    sucursales_bajas = [
        s for s in suc.get("data", [])
        if s.get("alerta") == "POR DEBAJO"
    ]
    if sucursales_bajas:
        nombres = ", ".join(s["sucursal"] for s in sucursales_bajas)
        recomendaciones.append(
            f"Sucursales con ticket bajo respecto a la media: {nombres}."
        )

    if cat.get("top_arrastran"):
        nombres_cat = ", ".join(c["categoria"] for c in cat["top_arrastran"])
        recomendaciones.append(
            f"Categorias que arrastran el promedio hacia abajo: {nombres_cat}."
        )

    if not recomendaciones:
        recomendaciones.append("No se detectaron problemas significativos en el ticket promedio.")

    return {
        "tendencia_mensual":      tm,
        "por_sucursal":           suc,
        "profundidad_ticket":     prof,
        "por_categoria":          cat,
        "recomendaciones":        recomendaciones,
        "resumen_ejecutivo": {
            "ticket_inicio":  res.get("primer_mes"),
            "ticket_actual":  res.get("ultimo_mes"),
            "cambio_total":   res.get("cambio_total_pct"),
            "diagnostico_causa": prof.get("diagnostico"),
        },
    }
