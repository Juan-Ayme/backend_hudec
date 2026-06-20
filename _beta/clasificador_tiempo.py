"""
Clasificador alternativo basado 100% en TIEMPO DE ROTACIÓN.
Propuesta del usuario — código original con ligeras anotaciones.

Idea central: en vez de discriminar por VOLUMEN ABSOLUTO (vol≥30/mes vs vol<10),
discriminamos por CUÁNTO TARDA EN ROTAR el stock (≤35d / 36-45d / >45d).
Variable unificadora: `tiempo_evaluacion` = `dias_ciclo` (si stock=0) o `cob` (si stock>0).

Para usarse necesita una columna nueva `dias_ciclo_venta` que NO existe en el SQL
actual. Acá la calculamos en Python a partir de `ult_venta_lote` y `primera_recep_total`.
"""
import pandas as pd
from typing import Any

# Departamentos estacionales (mismo concepto que :seasonal_departments del SQL)
# Estos IDs son placeholders — el script comparador los resuelve por nombre.
SEASONAL_DEPARTMENTS: list[int] = []


def clasificar_inventario_por_tiempo(row: dict) -> str:
    """
    Árbol de decisión basado 100% en el TIEMPO DE ROTACIÓN, sin importar
    si el lote fue de 2, 14 o 56 unidades.
    """

    # =========================================================================
    # 1. VARIABLES BASE
    # =========================================================================
    stock = float(row.get('stock_disponible') or 0)
    dsv = row.get('dias_sin_venta')  # puede ser None
    edad = row.get('edad_dias') or 9999
    cob = row.get('dias_cobertura')  # puede ser None

    v_life = float(row.get('unds_vendidas_lifetime') or 0)
    r_life = float(row.get('unds_recibidas_lifetime') or 0)
    c_life = float(row.get('unds_consumidas_lifetime') or 0)
    t_life = float(row.get('unds_trasladadas_lifetime') or 0)
    v_90d = float(row.get('unds_vendidas') or 0)

    # Tendencia: ¿está acelerando o frenando?
    vr45 = float(row.get('v_recent_45d') or 0)
    vo45 = float(row.get('v_old_45d') or 0)
    tendencia_cayendo = (vr45 > 0 and vo45 > 0 and vr45 < (vo45 * 0.7))

    sell_through = (v_life + c_life + t_life) / r_life if r_life > 0 else 0.0

    # =========================================================================
    # 2. VARIABLES DE TIEMPO (núcleo del clasificador)
    # =========================================================================
    # Si NO hay stock, medimos cuánto tardó en agotarse (ciclo de vida del lote).
    # Lo calculamos en Python como: ult_venta_lote - primera_recep_efectiva.
    dias_ciclo = row.get('dias_ciclo_venta')
    if dias_ciclo is None or dias_ciclo < 0:
        dias_ciclo = 9999  # sin datos / sin lote → asumir "muy lento"

    # Evaluamos velocidad PASADA (si stock=0) o FUTURA (si stock>0)
    tiempo_evaluacion = dias_ciclo if stock == 0 else (cob if cob is not None else 9999)

    es_rapido = tiempo_evaluacion <= 35
    es_sano = 35 < tiempo_evaluacion <= 45
    es_lento = tiempo_evaluacion > 45

    # =========================================================================
    # SECCIÓN A · CASOS ESPECIALES
    # =========================================================================
    if edad <= 7 and v_90d < 15:
        return '🌱 NUEVO: esperando ≥7d para evaluar rotación'

    dept_id = row.get('department_id')
    if dept_id in SEASONAL_DEPARTMENTS and (dsv or 9999) > 30:
        if stock == 0 and v_life >= 1:
            return '✅ TEMPORADA CERRADA: vendió su campaña y se agotó'
        if stock > 0:
            return '📦 SOBRANTE DE CAMPAÑA: stock de temporada pasada'

    if stock == 0 and r_life >= 5 and c_life > t_life:
        if c_life >= (r_life * 0.50) and v_life < (r_life * 0.20):
            return '⛔ PÉRDIDA TOTAL: casi sin ventas (<20%) — stock ajustado'
        if c_life > v_life and (r_life * 0.20) <= v_life < (r_life * 0.50):
            return '⚠️ VENTAS CON PÉRDIDA: vendía pero también se perdió mucho'

    # =========================================================================
    # SECCIÓN B · AGOTADOS QUE VENDIERON CASI TODO (sell-through ≥80%)
    # =========================================================================
    if stock == 0 and r_life >= 2 and sell_through >= 0.80:
        # Caminos Rápido (≤35d) y Sano (36-45d) — comportamiento exitoso
        if es_rapido or es_sano:
            if (dsv or 9999) <= 30:
                return '🔥💎 EXITOSO ACTIVO: se agotó a tiempo Y fue reciente — REPONER YA'
            elif (dsv or 9999) <= 60:
                return '💎 EXITOSO PASADO: se agotó a tiempo, pero lleva semanas sin demanda'
            else:
                return '💎 EXITOSO OLVIDADO: se agotó a tiempo, pero olvidamos reponerlo (>60d)'

        # Camino Lento (>45d) — rotó pero modesto
        if es_lento:
            if (dsv or 9999) <= 60:
                return '🐢 ROTACIÓN LENTA SANA: tardó >45d en venderse — reponer poco'
            else:
                return '💤 DEMANDA EXTINTA: tardó mucho y lleva mucho agotado — no reponer'

    # =========================================================================
    # SECCIÓN C · AGOTADOS QUE VENDIERON POCO (sell-through < 80%)
    # =========================================================================
    if stock == 0:
        # Quiebre reciente con buen ritmo
        if (es_rapido or es_sano) and (dsv or 9999) <= 14:
            return '🚨 QUIEBRE STOCK: lote agotado a buen ritmo — ¡COMPRAR YA!'

        # Históricos en el olvido (≥15d sin venta)
        if (dsv or 9999) >= 15:
            if v_life >= 50 and v_90d >= 5:
                return '👻 AGOTADO POTENCIAL ACTIVO: aún en demanda (reponer)'
            if v_life >= 50:
                return '💤 AGOTADO HISTÓRICO: demanda decayó (evaluar)'
            if v_90d >= 15:
                return '🌿 PRODUCTO EMERGENTE: corto historial (evaluar)'

        if v_90d == 0 and (row.get('unds_recibidas_90d') or 0) > 0 and v_life < 50:
            return '❓ RECIBIDO Y NO VENDIDO: revisar (mermas/transferencias)'

        if (dsv or 9999) >= 15:
            return '🪦 AGOTADO MARGINAL: bajo historial lifetime (<50 unds)'

        if es_lento:
            return '👻 FALSO AGOTADO: se agotó pero muy lento (>45d) — no priorizar'

    # =========================================================================
    # SECCIÓN D · CON STOCK + SIN VENTAS
    # =========================================================================
    if stock > 0 and v_90d == 0:
        dias_recep = row.get('dias_desde_ultima_recep')
        if dias_recep is not None and dias_recep <= 14:
            return '🔄 REABASTECIDO RECIENTE: nueva recep (≤14d) aún sin venta'
        return '💀 MUERTO 90D: stock parado sin ventas (capital estancado)'

    # =========================================================================
    # SECCIÓN E · CON STOCK + CON VENTAS
    # =========================================================================
    if stock > 0 and v_90d > 0:
        if 1 <= stock <= 2 and dsv is not None and 16 <= dsv <= 59:
            return '👀 ALERTA VISUAL: stock 1-2 unds sin movimiento 16-59d'

        dias_recep = row.get('dias_desde_ultima_recep')
        if dias_recep is not None and dias_recep <= 14 and es_lento:
            # Cob aparente alta por recep reciente — chequear si en realidad rota
            vel30 = row.get('vel_30d') or 0
            if vel30 > 0 or (r_life > 0 and (v_life / r_life) >= 0.70):
                return '🔄 REABASTECIDO ACTIVO: vende bien (cob aparente alta es por recep reciente)'

        # Evaluación pura por tiempo de cobertura
        if es_rapido:
            if tendencia_cayendo:
                return '🔥📉 ALTA ROTACIÓN DECAYENDO: ritmo ≤35d pero demanda bajando'
            return '🔥 ALTA ROTACIÓN: ritmo ≤35d — prioridad de compra'

        if es_sano:
            return '🟢 INVENTARIO SANO: ritmo 36-45d — va perfecto'

        if es_lento:
            if tendencia_cayendo:
                return '🧊📉 EXCESO / LIQUIDAR: ritmo >45d Y demanda cayendo — accionar urgente'
            return '🧊 EXCESO / LENTA ROTACIÓN: ritmo >45d — capital estancado'

    # =========================================================================
    # SECCIÓN F · CATCH-ALL
    # =========================================================================
    return '⚖️ EN ANÁLISIS: caso no cubierto por reglas'
