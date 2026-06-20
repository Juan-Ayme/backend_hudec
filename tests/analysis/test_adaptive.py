"""Tests de la derivación de umbrales adaptativos."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis import _adaptive
from app.analysis.classifier import Umbrales


def _vel_df(proy_values, stock=10):
    """DataFrame con N SKUs y la velocidad dada."""
    return pd.DataFrame({
        "proy_30d": proy_values,
        "stock_disponible": [stock] * len(proy_values),
        "unds_vendidas_lifetime": [v * 3 for v in proy_values],
    })


def test_adaptive_off_devuelve_base():
    base = Umbrales(adaptive=False)
    vel = _vel_df([10, 20, 30] * 20)
    out, diag = _adaptive.derive(vel, base)
    assert out is base
    assert diag["adaptive"] is False


def test_muestra_chica_no_aplica():
    base = Umbrales(adaptive=True)
    vel = _vel_df([10, 20])  # solo 2 SKUs
    out, diag = _adaptive.derive(vel, base)
    assert diag["aplicado"] is False
    assert out.proy_alta_min == base.proy_alta_min  # sin cambios


def test_tienda_rapida_sube_umbrales():
    """Catálogo de alta rotación -> proy_alta_min derivado debe ser alto."""
    base = Umbrales(adaptive=True)
    # 100 SKUs vendiendo entre 40 y 140/mes
    rng = np.random.default_rng(42)
    vel = _vel_df(list(rng.uniform(40, 140, 100)))
    out, diag = _adaptive.derive(vel, base)
    assert diag["aplicado"] is True
    # P85 de [40,140] está bien por encima del fijo 30
    assert out.proy_alta_min > base.proy_alta_min
    assert out.proy_alta_min > 80


def test_monotonicidad_garantizada():
    """muerto ≤ baja ≤ cat_max ≤ alta siempre."""
    base = Umbrales(adaptive=True)
    rng = np.random.default_rng(7)
    vel = _vel_df(list(rng.uniform(1, 100, 200)))
    out, _ = _adaptive.derive(vel, base)
    assert out.proy_muerto_max <= out.proy_baja_max
    assert out.proy_baja_max <= out.cat_umbral_max
    assert out.cat_umbral_max < out.proy_alta_min


def test_cota_inferior_de_sanidad():
    """Una tienda MUY lenta no debe poner 'alta rotación' por debajo del fijo."""
    base = Umbrales(adaptive=True)
    # Todos venden poquísimo (0.5-3/mes)
    vel = _vel_df(list(np.linspace(0.5, 3, 100)))
    out, _ = _adaptive.derive(vel, base)
    # proy_alta_min nunca baja del fijo (30)
    assert out.proy_alta_min >= base.proy_alta_min


def test_diagnostico_reporta_percentiles():
    base = Umbrales(adaptive=True)
    rng = np.random.default_rng(1)
    vel = _vel_df(list(rng.uniform(5, 50, 100)))
    _, diag = _adaptive.derive(vel, base)
    assert "derivados" in diag
    assert "proy_alta_min" in diag["derivados"]
    assert diag["derivados"]["proy_alta_min"]["percentil"] == base.adaptive_pct_alta
