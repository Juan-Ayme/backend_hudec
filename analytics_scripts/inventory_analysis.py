"""
Analisis avanzado de inventario.

Metricas calculadas por producto:
  ─ Demanda diaria efectiva = max(WMA_diaria, rot_30d, rot_90d)
  ─ Clasificacion XYZ (Coeficiente de Variacion semanal)
  ─ Clasificacion ABC (% acumulado de ingresos)
  ─ Matriz ABC × XYZ (9 cuadrantes)
  ─ Safety Stock  = z × σ_diaria × √LeadTime
  ─ Reorder Point = demand_diaria × LT + SS
  ─ Estado: "BAJO ROP - REORDENAR" si stock_actual <= ROP
  ─ EOQ (Economic Order Quantity) = √(2 × D_anual × S / H)
  ─ GMROI y Turnover de inventario (anualizado)
  ─ Tendencia lineal 13 semanas: SUBIENDO / ESTABLE / BAJANDO
  ─ Crecimiento 30d vs 90d en %

Uso standalone:
    python -c "
    from analytics_scripts.inventory_analysis import analisis_completo
    r = analisis_completo()
    "

Uso desde la API:
    from analytics_scripts.inventory_analysis import (
        calcular_abc_xyz, calcular_safety_stock_rop,
        calcular_eoq, calcular_gmroi
    )
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from analytics_scripts.config import (
    SERVICE_LEVEL_Z,
    LEAD_TIME_DAYS,
    ORDERING_COST_CLP,
    HOLDING_RATE,
    ABC_A_THRESHOLD,
    ABC_B_THRESHOLD,
    XYZ_X_MAX_CV,
    XYZ_Y_MAX_CV,
    WEEKS_WMA,
    WEEKS_TREND,
    DAYS_SHORT,
    DAYS_LONG,
    TREND_SLOPE_THRESHOLD,
    OFFICE_IDS,
)
from analytics_scripts.db_helper import get_df

# Clausula SQL reutilizable para filtrar solo las sucursales activas
_OFFICE_FILTER = f"doc.bsale_office_id IN ({', '.join(str(i) for i in OFFICE_IDS)})"

logger = logging.getLogger("kawii.analytics.inventory")

# Semanas de historial que necesitamos como minimo para WMA + tendencia
_MIN_WEEKS_NEEDED = max(WEEKS_WMA, WEEKS_TREND) + 4


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS (queries base)
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_demanda_semanal(weeks: int = _MIN_WEEKS_NEEDED) -> pd.DataFrame:
    """
    Descarga demanda semanal por producto desde los documentos.
    Devuelve: [bsale_product_id, name, semana, demand_semanal]
    """
    sql = f"""
        SELECT
            p.bsale_product_id,
            p.name                                              AS product_name,
            DATE_TRUNC('week', doc.emission_date)::date         AS semana,
            SUM(dd.quantity)                                    AS demand_semanal
        FROM document_details dd
        JOIN documents    doc ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants     v   ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN products     p   ON p.bsale_product_id    = v.bsale_product_id
        WHERE doc.emission_date >= NOW() - INTERVAL '{weeks} weeks'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
        GROUP BY p.bsale_product_id, p.name,
                 DATE_TRUNC('week', doc.emission_date)
        ORDER BY p.bsale_product_id, semana
    """
    return get_df(sql)


def _cargar_ventas_por_periodo() -> pd.DataFrame:
    """
    Ventas totales (unidades + monto) por producto en los ultimos 30 y 90 dias.
    Devuelve: [bsale_product_id, units_30d, revenue_30d, units_90d, revenue_90d]
    """
    sql = f"""
        SELECT
            p.bsale_product_id,
            SUM(CASE WHEN doc.emission_date >= NOW() - INTERVAL '30 days'
                     THEN dd.quantity    ELSE 0 END)           AS units_30d,
            SUM(CASE WHEN doc.emission_date >= NOW() - INTERVAL '30 days'
                     THEN dd.total_amount ELSE 0 END)          AS revenue_30d,
            SUM(CASE WHEN doc.emission_date >= NOW() - INTERVAL '90 days'
                     THEN dd.quantity    ELSE 0 END)           AS units_90d,
            SUM(CASE WHEN doc.emission_date >= NOW() - INTERVAL '90 days'
                     THEN dd.total_amount ELSE 0 END)          AS revenue_90d
        FROM document_details dd
        JOIN documents    doc ON doc.bsale_document_id = dd.bsale_document_id
        JOIN variants     v   ON v.bsale_variant_id    = dd.bsale_variant_id
        JOIN products     p   ON p.bsale_product_id    = v.bsale_product_id
        WHERE doc.emission_date >= NOW() - INTERVAL '90 days'
          AND COALESCE(doc.is_credit_note, FALSE) = FALSE
          AND COALESCE(doc.is_active,      TRUE)  = TRUE
          AND {_OFFICE_FILTER}
        GROUP BY p.bsale_product_id
    """
    return get_df(sql)


def _cargar_stock_y_costos() -> pd.DataFrame:
    """
    Stock disponible total (suma de sucursales) y costo efectivo por producto.
    Devuelve: [bsale_product_id, stock_total, costo_unitario]
    """
    sql = """
        SELECT
            v.bsale_product_id,
            SUM(sl.quantity_available)                             AS stock_total,
            AVG(COALESCE(vc.effective_cost, 0))                    AS costo_unitario
        FROM stock_levels sl
        JOIN variants v ON v.bsale_variant_id = sl.bsale_variant_id
        LEFT JOIN variant_costs vc ON vc.bsale_variant_id = sl.bsale_variant_id
        GROUP BY v.bsale_product_id
    """
    return get_df(sql)


def _cargar_taxonomia_producto() -> pd.DataFrame:
    """
    Nombre + clasificacion taxonomica por producto (via v_products_full).
    """
    sql = """
        SELECT DISTINCT
            bsale_product_id,
            product_name,
            department,
            category,
            subcategory
        FROM v_products_full
    """
    return get_df(sql)


# ─────────────────────────────────────────────────────────────────────────────
# CALCULOS ESTADISTICOS
# ─────────────────────────────────────────────────────────────────────────────

def _wma_diaria(series: pd.Series, n_weeks: int = WEEKS_WMA) -> float:
    """
    Calcula la Weighted Moving Average diaria sobre las ultimas n_weeks.
    Pesos crecientes: semana mas reciente tiene peso = n_weeks.
    Retorna unidades/dia.
    """
    if series.empty:
        return 0.0
    vals = series.values[-n_weeks:]           # tomar ultimas n semanas
    n    = len(vals)
    w    = np.arange(1, n + 1, dtype=float)  # pesos 1, 2, ..., n
    wma_semanal = float(np.dot(vals, w) / w.sum())
    return wma_semanal / 7.0                  # convertir a diario


def _cv_semanal(series: pd.Series) -> float:
    """Coeficiente de Variacion sobre la demanda semanal. CV = std/mean."""
    if len(series) < 2:
        return 0.0
    mean = series.mean()
    if mean == 0:
        return 0.0
    return float(series.std(ddof=1) / mean)


def _clasificar_xyz(cv: float) -> str:
    if cv < XYZ_X_MAX_CV:
        return "X"
    if cv < XYZ_Y_MAX_CV:
        return "Y"
    return "Z"


def _pendiente_lineal(series: pd.Series) -> float:
    """
    Regresion lineal simple: retorna la pendiente (unidades/semana).
    Implementacion manual con numpy para no depender de scipy.
    """
    n = len(series)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    y = series.values.astype(float)
    m = float(np.polyfit(x, y, 1)[0])   # polyfit[0] = pendiente
    return m


def _clasificar_tendencia(slope: float) -> str:
    if slope > TREND_SLOPE_THRESHOLD:
        return "SUBIENDO"
    if slope < -TREND_SLOPE_THRESHOLD:
        return "BAJANDO"
    return "ESTABLE"


# ─────────────────────────────────────────────────────────────────────────────
# FUNCION PRINCIPAL: construir tabla maestra
# ─────────────────────────────────────────────────────────────────────────────

def _construir_tabla_maestra() -> pd.DataFrame:
    """
    Une todas las fuentes y calcula todas las metricas por producto.
    Es la funcion core que llaman las demas.
    """
    # ── Cargar datos crudos ────────────────────────────────────────────────────
    logger.info("Cargando demanda semanal (ultimas %d semanas)...", _MIN_WEEKS_NEEDED)
    df_sem   = _cargar_demanda_semanal(_MIN_WEEKS_NEEDED)
    df_per   = _cargar_ventas_por_periodo()
    df_stock = _cargar_stock_y_costos()
    df_tax   = _cargar_taxonomia_producto()

    if df_sem.empty:
        logger.warning("Sin datos de ventas. Verifica el rango de fechas.")
        return pd.DataFrame()

    # ── Pivot semanal: filas = producto, columnas = semanas ───────────────────
    df_piv = (
        df_sem
        .pivot_table(
            index="bsale_product_id",
            columns="semana",
            values="demand_semanal",
            aggfunc="sum",
        )
        .fillna(0)
    )
    # Ordenar columnas cronologicamente
    df_piv = df_piv.reindex(sorted(df_piv.columns), axis=1)

    semanas_disponibles = list(df_piv.columns)
    logger.info("Semanas en el pivote: %d", len(semanas_disponibles))

    # ── Calcular metricas por producto ────────────────────────────────────────
    records = []
    for pid in df_piv.index:
        row = df_piv.loc[pid]
        series_all  = row                                # todas las semanas
        series_wma  = row.iloc[-(WEEKS_WMA):]            # ultimas n para WMA
        series_trend = row.iloc[-(WEEKS_TREND):]         # ultimas n para tendencia

        # --- Demanda diaria efectiva ---
        wma_d   = _wma_diaria(series_wma, WEEKS_WMA)

        # Obtenemos rot_30d / rot_90d desde df_per
        perf = df_per[df_per["bsale_product_id"] == pid]
        if not perf.empty:
            units_30 = float(perf["units_30d"].iloc[0])
            units_90 = float(perf["units_90d"].iloc[0])
            rev_30   = float(perf["revenue_30d"].iloc[0])
            rev_90   = float(perf["revenue_90d"].iloc[0])
        else:
            units_30 = units_90 = rev_30 = rev_90 = 0.0

        rot_30d = units_30 / DAYS_SHORT
        rot_90d = units_90 / DAYS_LONG
        demand_efectiva = max(wma_d, rot_30d, rot_90d)

        # --- CV y XYZ ---
        cv  = _cv_semanal(series_all)
        xyz = _clasificar_xyz(cv)

        # --- Pendiente y tendencia ---
        slope     = _pendiente_lineal(series_trend)
        tendencia = _clasificar_tendencia(slope)
        pct_30_vs_90 = (
            ((rot_30d - rot_90d) / rot_90d * 100)
            if rot_90d > 0 else 0.0
        )

        records.append({
            "bsale_product_id": int(pid),
            "demand_diaria_efectiva": round(demand_efectiva, 4),
            "wma_diaria":     round(wma_d, 4),
            "rot_30d":        round(rot_30d, 4),
            "rot_90d":        round(rot_90d, 4),
            "units_30d":      units_30,
            "units_90d":      units_90,
            "revenue_30d":    rev_30,
            "revenue_90d":    rev_90,
            "cv_semanal":     round(cv, 4),
            "xyz":            xyz,
            "slope_semanal":  round(slope, 4),
            "tendencia":      tendencia,
            "pct_30d_vs_90d": round(pct_30_vs_90, 1),
        })

    df_metrics = pd.DataFrame(records)

    # ── Unir con stock / costos / taxonomia ───────────────────────────────────
    df = (
        df_metrics
        .merge(df_stock, on="bsale_product_id", how="left")
        .merge(df_tax,   on="bsale_product_id", how="left")
    )
    df["stock_total"]    = df["stock_total"].fillna(0)
    df["costo_unitario"] = df["costo_unitario"].fillna(0)

    # ── ABC: clasificar por revenue_90d acumulado ─────────────────────────────
    df = df.sort_values("revenue_90d", ascending=False).reset_index(drop=True)
    total_rev     = df["revenue_90d"].sum()
    df["rev_cum_pct"] = df["revenue_90d"].cumsum() / (total_rev if total_rev > 0 else 1)
    df["abc"] = df["rev_cum_pct"].apply(
        lambda x: "A" if x <= ABC_A_THRESHOLD
                  else ("B" if x <= ABC_B_THRESHOLD else "C")
    )
    df["abc_xyz"] = df["abc"] + df["xyz"]

    # ── Safety Stock y ROP ────────────────────────────────────────────────────
    # σ_diaria = desviacion estandar de la demanda diaria
    # Estimamos: CV semanal / √7 * demand_semanal_media → σ_diaria
    df["demand_semanal_media"] = df["demand_diaria_efectiva"] * 7
    df["sigma_diaria"] = (
        df["cv_semanal"] * df["demand_semanal_media"] / np.sqrt(7)
    )
    df["safety_stock"] = (
        SERVICE_LEVEL_Z * df["sigma_diaria"] * np.sqrt(LEAD_TIME_DAYS)
    ).round(1)
    df["rop"] = (
        df["demand_diaria_efectiva"] * LEAD_TIME_DAYS + df["safety_stock"]
    ).round(1)
    df["estado_stock"] = df.apply(
        lambda r: "BAJO ROP - REORDENAR"
                  if r["stock_total"] <= r["rop"] and r["rop"] > 0
                  else (
                      "SIN MOVIMIENTO" if r["demand_diaria_efectiva"] == 0
                      else "OK"
                  ),
        axis=1,
    )

    # ── EOQ ───────────────────────────────────────────────────────────────────
    d_anual  = df["demand_diaria_efectiva"] * 365
    h        = df["costo_unitario"] * HOLDING_RATE                # costo/unidad/año
    h_safe   = h.replace(0, 1e-6)                                  # evitar division /0
    df["eoq"] = np.sqrt(
        2 * d_anual * ORDERING_COST_CLP / h_safe
    ).round(0)
    df.loc[df["costo_unitario"] == 0, "eoq"] = None   # sin costo → EOQ indefinido

    # ── GMROI y Inventory Turnover ────────────────────────────────────────────
    # Anualizar 90d → multiplicar por (365/90)
    factor_anual = 365.0 / 90.0
    cogs_anual   = (df["units_90d"] * df["costo_unitario"]) * factor_anual
    rev_anual    = df["revenue_90d"] * factor_anual
    gp_anual     = rev_anual - cogs_anual
    inv_valor    = df["stock_total"] * df["costo_unitario"]

    df["inv_valor_costo"]   = inv_valor.round(0)
    df["cogs_anual_est"]    = cogs_anual.round(0)
    df["rev_anual_est"]     = rev_anual.round(0)
    df["gmroi"] = (gp_anual / inv_valor.replace(0, np.nan)).round(2)
    df["inventory_turnover"] = (cogs_anual / inv_valor.replace(0, np.nan)).round(2)

    # ── Limpiar y ordenar columnas finales ────────────────────────────────────
    cols_finales = [
        "bsale_product_id", "product_name",
        "department", "category", "subcategory",
        "abc", "xyz", "abc_xyz",
        "tendencia", "pct_30d_vs_90d",
        "demand_diaria_efectiva", "wma_diaria", "rot_30d", "rot_90d",
        "cv_semanal",
        "stock_total", "costo_unitario", "inv_valor_costo",
        "safety_stock", "rop", "estado_stock",
        "eoq",
        "units_30d", "units_90d", "revenue_30d", "revenue_90d",
        "gmroi", "inventory_turnover",
        "rev_anual_est", "cogs_anual_est",
    ]
    existing = [c for c in cols_finales if c in df.columns]
    return df[existing].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES PUBLICAS (para la API y la consola)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_abc_xyz() -> dict[str, Any]:
    """
    Devuelve la matriz ABC×XYZ completa.

    Cuadrantes:
      AX = criticos rentables + predecibles  → maxima prioridad
      AY = criticos rentables + variables    → safety stock alto
      AZ = criticos rentables + erraticos    → vigilar de cerca
      BX/BY/BZ = importantes                 → tratamiento estandar
      CX/CY/CZ = de bajo valor               → reducir stock
    """
    df = _construir_tabla_maestra()
    if df.empty:
        return {"data": [], "resumen": {}}

    # Resumen por cuadrante
    resumen = (
        df.groupby("abc_xyz")
        .agg(
            productos=("bsale_product_id", "count"),
            revenue_90d_total=("revenue_90d", "sum"),
            stock_valor_total=("inv_valor_costo", "sum"),
        )
        .reset_index()
        .sort_values("revenue_90d_total", ascending=False)
        .to_dict("records")
    )

    return {
        "data":    df.replace({np.nan: None}).to_dict("records"),
        "resumen": resumen,
        "leyenda": {
            "AX": "Critico rentable y predecible: mantener stock, minimo SS",
            "AY": "Critico rentable y variable: safety stock medio-alto",
            "AZ": "Critico rentable y erratico: vigilar de cerca, SS alto",
            "BX": "Importante predecible: tratamiento estandar",
            "BY": "Importante variable: buffer moderado",
            "BZ": "Importante erratico: revisar",
            "CX": "Bajo valor predecible: reducir stock",
            "CY": "Bajo valor variable: reducir stock",
            "CZ": "Bajo valor erratico: considerar discontinuar",
        },
    }


def calcular_safety_stock_rop() -> dict[str, Any]:
    """
    Retorna productos ordenados por urgencia de reposicion.
    Destaca los que estan 'BAJO ROP - REORDENAR'.
    """
    df = _construir_tabla_maestra()
    if df.empty:
        return {"data": [], "alertas": []}

    cols = [
        "bsale_product_id", "product_name", "department", "category",
        "abc", "xyz",
        "demand_diaria_efectiva",
        "stock_total", "safety_stock", "rop", "estado_stock",
        "tendencia",
    ]
    existing = [c for c in cols if c in df.columns]
    df_out = df[existing].sort_values(
        ["estado_stock", "abc"],
        ascending=[True, True],   # "BAJO ROP" primero, luego "A" antes que "C"
    )

    alertas = (
        df_out[df_out["estado_stock"] == "BAJO ROP - REORDENAR"]
        [["bsale_product_id", "product_name", "abc", "stock_total", "rop"]]
        .to_dict("records")
    )

    return {
        "data":    df_out.replace({np.nan: None}).to_dict("records"),
        "alertas": alertas,
        "total_bajo_rop": len(alertas),
        "parametros": {
            "z":            SERVICE_LEVEL_Z,
            "lead_time_d":  LEAD_TIME_DAYS,
            "nivel_servicio": "95%",
        },
    }


def calcular_eoq() -> dict[str, Any]:
    """
    EOQ = √(2 × D_anual × S / H)
    Retorna la cantidad optima de pedido por producto.
    Solo aplica a productos con costo conocido.
    """
    df = _construir_tabla_maestra()
    if df.empty:
        return {"data": []}

    cols = [
        "bsale_product_id", "product_name", "abc",
        "demand_diaria_efectiva",
        "costo_unitario", "eoq",
        "rev_anual_est", "cogs_anual_est",
    ]
    existing = [c for c in cols if c in df.columns]
    df_out = (
        df[existing]
        .dropna(subset=["eoq"])
        .sort_values("rev_anual_est", ascending=False)
    )

    return {
        "data": df_out.replace({np.nan: None}).to_dict("records"),
        "parametros": {
            "costo_pedido_clp": ORDERING_COST_CLP,
            "tasa_holding_pct": HOLDING_RATE * 100,
        },
    }


def calcular_gmroi(top_n: int = 50) -> dict[str, Any]:
    """
    GMROI y Inventory Turnover anualizado por producto.

    GMROI > 100% = por cada CLP invertido en inventario,
                   se generan mas de 1 CLP de margen bruto.
    Turnover alto = el inventario "rota" frecuentemente (saludable).
    """
    df = _construir_tabla_maestra()
    if df.empty:
        return {"data": [], "resumen": {}}

    cols = [
        "bsale_product_id", "product_name", "department", "category",
        "abc", "xyz",
        "stock_total", "inv_valor_costo",
        "gmroi", "inventory_turnover",
        "rev_anual_est", "cogs_anual_est",
    ]
    existing = [c for c in cols if c in df.columns]
    df_out = (
        df[existing]
        .dropna(subset=["gmroi"])
        .sort_values("gmroi", ascending=False)
        .head(top_n)
    )

    total_inv    = float(df["inv_valor_costo"].sum())
    total_rev    = float(df["rev_anual_est"].sum())
    total_cogs   = float(df["cogs_anual_est"].sum())
    global_gmroi = round((total_rev - total_cogs) / total_inv * 100, 2) if total_inv > 0 else None

    return {
        "data": df_out.replace({np.nan: None}).to_dict("records"),
        "resumen": {
            "inventario_total_costo":   round(total_inv, 0),
            "revenue_anual_estimado":   round(total_rev, 0),
            "gmroi_global":             global_gmroi,
        },
    }


def analisis_completo() -> dict[str, Any]:
    """
    Ejecuta todos los modulos y retorna el resultado consolidado.
    Usado principalmente por el CLI (run_all.py).
    """
    logger.info("Iniciando analisis completo de inventario...")
    df = _construir_tabla_maestra()

    if df.empty:
        return {"error": "Sin datos suficientes para el analisis."}

    n_total       = len(df)
    bajo_rop      = int((df["estado_stock"] == "BAJO ROP - REORDENAR").sum())
    sin_mov       = int((df["estado_stock"] == "SIN MOVIMIENTO").sum())
    ok_count      = n_total - bajo_rop - sin_mov

    abc_counts    = df["abc"].value_counts().to_dict()
    xyz_counts    = df["xyz"].value_counts().to_dict()
    quad_counts   = df["abc_xyz"].value_counts().to_dict()
    tend_counts   = df["tendencia"].value_counts().to_dict()

    return {
        "tabla_maestra": df.replace({np.nan: None}).to_dict("records"),
        "resumen": {
            "total_productos_analizados": n_total,
            "bajo_rop":                  bajo_rop,
            "sin_movimiento":             sin_mov,
            "ok":                         ok_count,
            "abc_distribucion":           abc_counts,
            "xyz_distribucion":           xyz_counts,
            "cuadrantes_abc_xyz":         quad_counts,
            "tendencia_distribucion":     tend_counts,
            "inventario_valorizado_costo": round(float(df["inv_valor_costo"].sum()), 0),
        },
    }
