"""Tests de `weighted_velocity`.

Validan:
  - Matemática del decay exponencial (peso = 0.5^(days/half_life))
  - Denominador correcto (window completo, no solo días con venta)
  - Casos límite (vacío, todas las ventas hoy, todas hace 90d)
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis.velocity import weighted_velocity


def test_caso_tomatodo_ponderado_es_mucho_menor_que_plano(sales_tomatodo, hoy):
    """El SKU vendió 35 unds en 90d, pero todo en los primeros 45 días.
    Promedio plano: 35/90 * 30 ≈ 11.7/mes (ROTACION_ACTIVA según SQL viejo).
    Ponderado hl=30: debe ser <5/mes (en zona de BAJA/MUERTO)."""
    res = weighted_velocity(sales_tomatodo, reference_date=hoy, half_life_days=30)
    row = res.iloc[0]

    assert row["ventas_brutas"] == 35
    proy_plana = 35 * 30 / 90
    assert 11.0 < proy_plana < 12.0
    assert row["proy_30d"] < 5.0, "decay debe colapsar la proyección"
    assert row["proy_30d"] < proy_plana / 2, "ponderado debe ser >2x menor"
    assert row["dias_desde_ultima"] == 45


def test_caso_estable_ponderado_aprox_igual_a_plano(sales_estable, hoy):
    """Cuando las ventas están distribuidas parejo, el ponderado y el plano
    no deberían diferir mucho — el decay solo redistribuye cuando hay
    concentración temporal."""
    res = weighted_velocity(sales_estable, reference_date=hoy, half_life_days=30)
    row = res.iloc[0]

    proy_plana = row["ventas_brutas"] * 30 / 90
    # No exigimos igualdad — ventas más recientes siguen pesando un poco más —
    # pero el ratio debe ser razonable.
    assert 0.7 < row["proy_30d"] / proy_plana < 2.0


def test_half_life_corto_acentua_el_decay(sales_tomatodo, hoy):
    """Half-life más corto -> proy más bajo para SKUs que ya no venden."""
    hl_15 = weighted_velocity(sales_tomatodo, reference_date=hoy, half_life_days=15)
    hl_30 = weighted_velocity(sales_tomatodo, reference_date=hoy, half_life_days=30)
    hl_60 = weighted_velocity(sales_tomatodo, reference_date=hoy, half_life_days=60)

    p15 = hl_15.iloc[0]["proy_30d"]
    p30 = hl_30.iloc[0]["proy_30d"]
    p60 = hl_60.iloc[0]["proy_30d"]
    assert p15 < p30 < p60, "menor half_life -> mayor castigo a ventas viejas"


def test_venta_de_hace_X_dias_pesa_05_a_la_X_sobre_hl():
    """Sanity de la fórmula: peso = 0.5^(days_ago / half_life)."""
    df = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "fecha": date(2026, 5, 14),
                "qty_neta": 10,
            }
        ]
    )
    ref = date(2026, 6, 13)  # 30 días después
    res = weighted_velocity(df, reference_date=ref, half_life_days=30)
    # peso = 0.5^(30/30) = 0.5; ventas ponderadas = 0.5 * 10 = 5
    assert math.isclose(res.iloc[0]["ventas_ponderadas"], 5.0, rel_tol=0.01)


def test_dataframe_vacio_no_explota(sales_vacio, hoy):
    res = weighted_velocity(sales_vacio, reference_date=hoy)
    assert res.empty
    assert "proy_30d" in res.columns


def test_qty_neta_negativa_o_cero_se_filtra(hoy):
    """Las devoluciones (qty<=0) no cuentan como ventas."""
    df = pd.DataFrame(
        [
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "fecha": hoy - timedelta(days=10),
                "qty_neta": 5,
            },
            {
                "bsale_office_id": 1,
                "bsale_variant_id": 1,
                "fecha": hoy - timedelta(days=8),
                "qty_neta": -3,  # devolución
            },
        ]
    )
    res = weighted_velocity(df, reference_date=hoy)
    assert res.iloc[0]["ventas_brutas"] == 5


def test_proy_30d_es_velocidad_diaria_por_30(sales_tomatodo, hoy):
    res = weighted_velocity(sales_tomatodo, reference_date=hoy)
    row = res.iloc[0]
    assert math.isclose(row["proy_30d"], row["velocidad_diaria"] * 30, rel_tol=1e-9)
