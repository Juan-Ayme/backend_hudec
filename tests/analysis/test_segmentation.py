"""Tests de la segmentación ABC-XYZ."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis import _segmentation

HOY = date(2026, 6, 13)


# --- ABC ------------------------------------------------------------------

def test_abc_pareto_basico():
    """Catálogo con varios A: SKUs que acumulan hasta 80% son A."""
    # 5 SKUs: 400,300,150,100,50 (total 1000). cum_prev: 0, .40, .70, .85, .95
    df = pd.DataFrame(
        {"monto_vendido": [400.0, 300.0, 150.0, 100.0, 50.0]},
        index=[1, 2, 3, 4, 5],
    )
    abc = _segmentation.compute_abc(df)
    assert abc.loc[1] == "A"   # cum_prev 0    < 0.80
    assert abc.loc[2] == "A"   # cum_prev 0.40 < 0.80
    assert abc.loc[3] == "A"   # cum_prev 0.70 < 0.80
    assert abc.loc[4] == "B"   # cum_prev 0.85 -> B
    assert abc.loc[5] == "C"   # cum_prev 0.95 -> C


def test_abc_sku_dominante_cruza_umbral_es_A():
    """Un SKU que solo él supera 80% acumulado igual es A (lo lleva al 80%)."""
    df = pd.DataFrame({"monto_vendido": [900.0, 100.0]}, index=[1, 2])
    abc = _segmentation.compute_abc(df)
    assert abc.loc[1] == "A"  # cum_prev 0 < 0.80
    assert abc.loc[2] == "B"  # cum_prev 0.90 -> B


def test_abc_sku_sin_facturacion_es_C():
    df = pd.DataFrame({"monto_vendido": [1000.0, 0.0]}, index=[1, 2])
    abc = _segmentation.compute_abc(df)
    assert abc.loc[2] == "C"


def test_abc_todo_cero_es_C():
    df = pd.DataFrame({"monto_vendido": [0.0, 0.0]}, index=[1, 2])
    abc = _segmentation.compute_abc(df)
    assert (abc == "C").all()


# --- XYZ ------------------------------------------------------------------

def _sales(office, variant, monthly_qty):
    """Genera ventas: una por mes hacia atrás desde HOY."""
    rows = []
    for i, q in enumerate(monthly_qty):
        rows.append({
            "bsale_office_id": office,
            "bsale_variant_id": variant,
            "fecha": HOY - timedelta(days=30 * i + 5),
            "qty_neta": q,
        })
    return rows


def test_xyz_demanda_estable_es_X():
    """Ventas parejas cada mes -> CV bajo -> X."""
    df = pd.DataFrame(_sales(1, 1, [10, 10, 10]))
    out = _segmentation.compute_xyz(
        df, pd.Index([1]), reference_date=HOY, window_days=90,
    )
    assert out.loc[(1, 1), "xyz"] == "X"


def test_xyz_demanda_erratica_es_Z():
    """Vendió fuerte un mes y nada los demás -> CV alto -> Z."""
    df = pd.DataFrame(_sales(1, 1, [30]))  # 1 mes de 3
    out = _segmentation.compute_xyz(
        df, pd.Index([1]), reference_date=HOY, window_days=90,
    )
    assert out.loc[(1, 1), "xyz"] == "Z"


def test_xyz_vacio_no_explota():
    empty = pd.DataFrame(
        columns=["bsale_office_id", "bsale_variant_id", "fecha", "qty_neta"]
    )
    out = _segmentation.compute_xyz(
        empty, pd.Index([]), reference_date=HOY, window_days=90,
    )
    assert out.empty


# --- enrich (integración) -------------------------------------------------

def test_enrich_agrega_columnas():
    classified = pd.DataFrame(
        {
            "bsale_office_id": [1, 1],
            "bsale_variant_id": [100, 200],
            "monto_vendido": [900.0, 100.0],
        }
    ).set_index(["bsale_office_id", "bsale_variant_id"])

    sales = pd.DataFrame(
        _sales(1, 100, [10, 10, 10]) + _sales(1, 200, [5]),
    )
    out = _segmentation.enrich(
        classified, sales, reference_date=HOY, window_days=90,
    )
    for col in ("abc", "xyz", "cv", "abc_xyz"):
        assert col in out.columns
    # variant 100 factura 90% (dominante) -> A; demanda estable -> X
    row100 = out.reset_index().set_index("bsale_variant_id").loc[100]
    assert row100["abc"] == "A"
    assert row100["abc_xyz"] == "A" + row100["xyz"]
