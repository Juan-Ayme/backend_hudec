"""Tests del clasificador.

Cada test arma un mini-DataFrame que ejercita UNA regla específica y
verifica la etiqueta resultante. Los inputs sintéticos imitan la forma
real de los datos (mismas columnas que produce el service).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis.classifier import Umbrales, classify
from app.analysis.velocity import weighted_velocity


HOY = date(2026, 6, 13)


def _vel_row(office: int, variant: int, vel_diaria: float, dsv: int) -> dict:
    """Inventa una fila del DataFrame que devuelve weighted_velocity."""
    return {
        "bsale_office_id": office,
        "bsale_variant_id": variant,
        "velocidad_diaria": vel_diaria,
        "proy_30d": vel_diaria * 30,
        "peso_observado": 30.0,
        "ventas_ponderadas": vel_diaria * 30.0,
        "ventas_brutas": vel_diaria * 90,
        "ultima_venta": HOY - timedelta(days=dsv),
        "dias_desde_ultima": dsv,
    }


def _vel_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).set_index(["bsale_office_id", "bsale_variant_id"])
    return df


def _stock_df(rows: list[tuple[int, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"bsale_office_id": o, "bsale_variant_id": v, "stock_disponible": s}
            for o, v, s in rows
        ]
    )


def test_quiebre_stock_cero_venta_reciente():
    vel = _vel_df([_vel_row(1, 1, vel_diaria=1.0, dsv=5)])
    out = classify(vel, _stock_df([(1, 1, 0)]))
    assert out.iloc[0]["clasificacion"] == "QUIEBRE"


def test_agotado_frio_stock_cero_sin_venta_reciente():
    vel = _vel_df([_vel_row(1, 1, vel_diaria=0.05, dsv=80)])
    out = classify(vel, _stock_df([(1, 1, 0)]))
    assert out.iloc[0]["clasificacion"] == "AGOTADO_FRIO"


def test_stock_parado_con_stock_sin_ventas():
    vel = _vel_df(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "velocidad_diaria": 0.0,
                "proy_30d": 0.0,
                "peso_observado": 0.0,
                "ventas_ponderadas": 0.0,
                "ventas_brutas": 0.0,
                "ultima_venta": None,
                "dias_desde_ultima": 9999,
            }
        ]
    )
    out = classify(vel, _stock_df([(1, 1, 50)]))
    assert out.iloc[0]["clasificacion"] == "STOCK_PARADO"


def test_ritmo_perdido_vendio_pero_45d_sin_venta():
    """SKU que vendió en el window pero hace 45-59d que no vende.
    El SQL viejo lo marca como '📉 RITMO PERDIDO — evaluar antes de reponer'
    porque la velocidad histórica del lote engaña."""
    # proy=15/mes pero dsv=50 → debe ir a RITMO_PERDIDO, NO a ROTACION_ACTIVA
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=50)])
    out = classify(vel, _stock_df([(1, 1, 10)]))
    assert out.iloc[0]["clasificacion"] == "RITMO_PERDIDO"


def test_muerto_lento_proy_baja_y_dias_sin_venta_altos():
    """El "promedio mentiroso" en su variante extrema: hay stock,
    proy ya colapsó por decay, y sin venta hace meses."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=0.05, dsv=75)])
    out = classify(vel, _stock_df([(1, 1, 10)]))
    assert out.iloc[0]["clasificacion"] == "MUERTO_LENTO"


def test_alta_rotacion_proy_alta_y_cobertura_corta():
    # 40/mes con stock 30 -> cob = 30/(40/30) = 22.5d < 30
    vel = _vel_df([_vel_row(1, 1, vel_diaria=40 / 30, dsv=2)])
    out = classify(vel, _stock_df([(1, 1, 30)]))
    assert out.iloc[0]["clasificacion"] == "ALTA_ROTACION"


def test_exceso_proy_buena_pero_cobertura_larga():
    # 15/mes con stock 100 -> cob = 100/(15/30) = 200d > 45
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=2)])
    out = classify(vel, _stock_df([(1, 1, 100)]))
    assert out.iloc[0]["clasificacion"] == "EXCESO"


def test_baja_rotacion_proy_debajo_del_umbral():
    vel = _vel_df([_vel_row(1, 1, vel_diaria=5 / 30, dsv=10)])  # 5/mes
    out = classify(vel, _stock_df([(1, 1, 30)]))
    assert out.iloc[0]["clasificacion"] == "BAJA_ROTACION"


def test_umbral_relativo_por_categoria_cambia_etiqueta():
    """SKU con proy=5/mes en categoría LENTA (avg 4/mes) cae como ACTIVA;
    el mismo SKU en categoría RAPIDA (avg 30/mes) cae como BAJA."""
    # Categoría LENTA: 1 SKU "estrella" + 1 SKU "promedio"
    # Categoría RAPIDA: 1 SKU "estrella" + 1 SKU "promedio"
    vel_lenta = _vel_df(
        [
            _vel_row(1, 10, vel_diaria=4 / 30, dsv=2),   # nuestro foco
            _vel_row(1, 11, vel_diaria=4 / 30, dsv=2),   # vecino de categoría
        ]
    )
    stock = _stock_df([(1, 10, 5), (1, 11, 5)])
    cats = pd.DataFrame(
        [
            {"bsale_variant_id": 10, "categoria": "Lenta"},
            {"bsale_variant_id": 11, "categoria": "Lenta"},
        ]
    )
    out_lenta = classify(vel_lenta, stock, categories=cats)
    # avg_proy_cat = 4 -> umbral = clip(4*0.5, 3, 10) = 3 -> SKU pasa
    assert out_lenta.set_index("bsale_variant_id").loc[10, "clasificacion"] in (
        "ROTACION_ACTIVA",
        "ALTA_ROTACION",
    )

    vel_rapida = _vel_df(
        [
            _vel_row(1, 20, vel_diaria=4 / 30, dsv=2),   # mismo SKU "lento"
            _vel_row(1, 21, vel_diaria=50 / 30, dsv=2),  # vecinos vendedores
            _vel_row(1, 22, vel_diaria=50 / 30, dsv=2),
        ]
    )
    stock_r = _stock_df([(1, 20, 5), (1, 21, 5), (1, 22, 5)])
    cats_r = pd.DataFrame(
        [
            {"bsale_variant_id": 20, "categoria": "Rapida"},
            {"bsale_variant_id": 21, "categoria": "Rapida"},
            {"bsale_variant_id": 22, "categoria": "Rapida"},
        ]
    )
    out_rapida = classify(vel_rapida, stock_r, categories=cats_r)
    # avg_proy_cat ≈ 35 -> umbral = clip(35*0.5, 3, 10) = 10 -> 4 < 10 -> BAJA
    assert out_rapida.set_index("bsale_variant_id").loc[20, "clasificacion"] == "BAJA_ROTACION"


def test_lote_frenado_proy_lote_alta_pero_reciente_baja():
    """SKU maduro, lote viejo: proy del lote dice 'alta rotación' pero
    la velocidad de los últimos 10d es casi cero."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=20)])
    vel["proy_recent_30d"] = 1.0  # casi muerto en los últimos días
    stock = _stock_df([(1, 1, 20)])  # >= 5 unidades de saldo
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 100,
                "unds_recibidas_lifetime": 120,
                "primera_recepcion": HOY - timedelta(days=180),
                "ultima_recepcion": HOY - timedelta(days=120),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "LOTE_FRENADO"


def test_bestseller_activo_stock_cero_venta_reciente():
    """Vendió ~todo Y todavía vende — caliente."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=20)])
    stock = _stock_df([(1, 1, 0)])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 95,
                "unds_recibidas_lifetime": 100,
                "primera_recepcion": HOY - timedelta(days=200),
                "ultima_recepcion": HOY - timedelta(days=60),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "BESTSELLER_ACTIVO"


def test_bestseller_agotado_31_60_dias_sin_venta():
    """Vendió ~todo, enfrió hace 31-60d — reponer pronto."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=45)])
    stock = _stock_df([(1, 1, 0)])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 95,
                "unds_recibidas_lifetime": 100,
                "primera_recepcion": HOY - timedelta(days=200),
                "ultima_recepcion": HOY - timedelta(days=70),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "BESTSELLER_AGOTADO"


def test_oportunidad_perdida_stock_cero_sell_through_alto():
    """Vendió ~todo, +60d sin venta — oportunidad perdida real."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=75)])
    stock = _stock_df([(1, 1, 0)])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 95,
                "unds_recibidas_lifetime": 100,
                "primera_recepcion": HOY - timedelta(days=200),
                "ultima_recepcion": HOY - timedelta(days=120),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "OPORTUNIDAD_PERDIDA"


def test_agotado_historico_lifetime_alto_sin_demanda_actual():
    """Ex-bestseller (lifetime ≥50) sin venta hace 15+d, sell-through bajo
    (no entra a BESTSELLER_*)."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=0.02, dsv=60)])
    stock = _stock_df([(1, 1, 0)])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 200,
                "unds_recibidas_lifetime": 500,  # sell-through 40% — no bestseller
                "primera_recepcion": HOY - timedelta(days=400),
                "ultima_recepcion": HOY - timedelta(days=180),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "AGOTADO_HISTORICO"


def test_lento_cronico_sku_viejo_lifetime_bajo():
    """≥180 días en catálogo, lifetime <60 unds, lote no fresco."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=4 / 30, dsv=10)])
    stock = _stock_df([(1, 1, 5)])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 40,
                "unds_recibidas_lifetime": 50,
                "primera_recepcion": HOY - timedelta(days=300),
                "ultima_recepcion": HOY - timedelta(days=60),
            }
        ]
    )
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "LENTO_CRONICO"


def test_columnas_de_diagnostico_presentes_en_output():
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15 / 30, dsv=2)])
    out = classify(vel, _stock_df([(1, 1, 20)]))
    for col in [
        "clasificacion",
        "razon",
        "dias_cobertura",
        "stock_disponible",
        "proy_30d",
    ]:
        assert col in out.columns


def test_lote_chico_no_cae_en_baja_rotacion():
    """Mueble caro con lote=4 unds, vende 2/mes (50% sell-through mensual).
    Sin el piso dinámico cae en BAJA_ROTACION (proy 2 < piso 3).
    Con el fix, el piso para lote ≤5 es 1 -> entra en ROTACION_ACTIVA."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=2 / 30, dsv=10)])  # 2/mes
    stock = _stock_df([(1, 1, 2)])
    cats = pd.DataFrame([{"bsale_variant_id": 1, "categoria": "Muebles"}])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 2,
                "unds_recibidas_lifetime": 4,  # lote micro
                "primera_recepcion": HOY - timedelta(days=45),
                "ultima_recepcion": HOY - timedelta(days=45),
            }
        ]
    )
    out = classify(vel, stock, categories=cats, lifetime=life, reference_date=HOY)
    row = out.iloc[0]
    assert row["clasificacion"] == "ROTACION_ACTIVA"
    assert row["umbral_activa"] == pytest.approx(1.0)


def test_lote_normal_mantiene_piso_historico():
    """Lote >15 unds conserva el piso histórico de 3 — sin regresiones.
    Sell-through 80% (30+50_stock = 80 de 100 → balance limpio, no mermas)."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=2 / 30, dsv=10)])
    stock = _stock_df([(1, 1, 70)])  # 30 vendidas + 70 stock = 100 recibidas
    cats = pd.DataFrame([{"bsale_variant_id": 1, "categoria": "Consumo"}])
    life = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "unds_vendidas_lifetime": 30,
                "unds_recibidas_lifetime": 100,
                "unds_consumidas_lifetime": 0,
                "unds_trasladadas_lifetime": 0,
                "primera_recepcion": HOY - timedelta(days=60),
                "ultima_recepcion": HOY - timedelta(days=30),
            }
        ]
    )
    out = classify(vel, stock, categories=cats, lifetime=life, reference_date=HOY)
    row = out.iloc[0]
    assert row["clasificacion"] == "BAJA_ROTACION"
    assert row["umbral_activa"] == pytest.approx(3.0)


def test_stock_recien_llegado_no_es_stock_parado():
    """Lote ≤14d sin ventas todavía — esperar, no liquidar."""
    vel = _vel_df([
        {
            "bsale_office_id": 1, "bsale_variant_id": 1,
            "velocidad_diaria": 0.0, "proy_30d": 0.0, "peso_observado": 0.0,
            "ventas_ponderadas": 0.0, "ventas_brutas": 0.0,
            "ultima_venta": None, "dias_desde_ultima": 9999,
        }
    ])
    stock = _stock_df([(1, 1, 30)])
    life = pd.DataFrame([{
        "bsale_office_id": 1, "bsale_variant_id": 1,
        "unds_vendidas_lifetime": 0, "unds_recibidas_lifetime": 30,
        "primera_recepcion": HOY - timedelta(days=7),
        "ultima_recepcion": HOY - timedelta(days=7),  # llegó hace 7d
    }])
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "STOCK_RECIEN_LLEGADO"


def test_perdida_stock_mermas_significativas():
    """Recibió 100, vendió 10, consumió 5, stock=20 → 65 perdidas (65%)."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=10/90, dsv=20)])
    stock = _stock_df([(1, 1, 20)])
    life = pd.DataFrame([{
        "bsale_office_id": 1, "bsale_variant_id": 1,
        "unds_vendidas_lifetime": 10,
        "unds_recibidas_lifetime": 100,
        "unds_consumidas_lifetime": 5,
        "unds_trasladadas_lifetime": 0,
        "primera_recepcion": HOY - timedelta(days=120),
        "ultima_recepcion": HOY - timedelta(days=60),
    }])
    out = classify(vel, stock, lifetime=life, reference_date=HOY)
    assert out.iloc[0]["clasificacion"] == "PERDIDA_STOCK"


def test_rotacion_bajando_alta_rotacion_con_tendencia_caida():
    """Vende mucho pero el ritmo cae → ROTACION_BAJANDO, no ALTA_ROTACION."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=40/30, dsv=2)])
    vel["v_recent_45d"] = 30.0
    vel["v_old_45d"] = 100.0  # 30/100 = 0.3 < 0.7 → cae
    stock = _stock_df([(1, 1, 30)])
    out = classify(vel, stock)
    assert out.iloc[0]["clasificacion"] == "ROTACION_BAJANDO"


def test_exceso_liquidar_cobertura_larga_y_demanda_cae():
    """cob>45d + tendencia cae → EXCESO_LIQUIDAR."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=15/30, dsv=10)])
    vel["v_recent_45d"] = 5.0
    vel["v_old_45d"] = 30.0  # 0.17 < 0.7
    stock = _stock_df([(1, 1, 100)])
    out = classify(vel, stock)
    assert out.iloc[0]["clasificacion"] == "EXCESO_LIQUIDAR"


def test_vendiendo_mas_proy_bajo_pero_tendencia_sube():
    """proy<umbral pero v_recent > v_old*1.5 → VENDIENDO_MAS.
    Requiere cobertura razonable (≤45d), sino va a EXCESO o BAJA_ROTACION."""
    vel = _vel_df([_vel_row(1, 1, vel_diaria=4/30, dsv=10)])
    vel["v_recent_45d"] = 30.0
    vel["v_old_45d"] = 5.0
    stock = _stock_df([(1, 1, 4)])  # cob = 4/0.13 ≈ 30d → razonable
    out = classify(vel, stock)
    assert out.iloc[0]["clasificacion"] == "VENDIENDO_MAS"


def test_velocity_y_classifier_juntos_caso_tomatodo(sales_tomatodo, hoy):
    """Smoke test del pipeline completo: velocity -> classifier."""
    vel = weighted_velocity(sales_tomatodo, reference_date=hoy, half_life_days=30)
    stock = pd.DataFrame(
        [{"bsale_office_id": 1, "bsale_variant_id": 9999, "stock_disponible": 20}]
    )
    out = classify(vel, stock)
    # SKU con stock=20, vendió fuerte hace meses, dsv=45.
    # proy_30d ~ 4.6/mes (ver test_velocity). Con stock=20, cob = 130d -> EXCESO.
    # Si pulen los umbrales podría caer en BAJA_ROTACION. Verificamos que NO
    # caiga en ALTA_ROTACION ni ATIPICO — el bug original.
    label = out.iloc[0]["clasificacion"]
    assert label not in ("ALTA_ROTACION", "ROTACION_ACTIVA", "ATIPICO")
