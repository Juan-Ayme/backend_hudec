"""Fixtures compartidos por los tests de `app.analysis`.

Construyen DataFrames sintéticos con la misma forma que produce el SQL
(ventas diarias, stock, lifetime, categorías) para que cada test pueda
focusarse en una regla a la vez.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


HOY = date(2026, 6, 13)


@pytest.fixture
def hoy() -> date:
    return HOY


def _sales_row(office: int, variant: int, days_ago: int, qty: float) -> dict:
    return {
        "bsale_office_id": office,
        "bsale_variant_id": variant,
        "fecha": HOY - timedelta(days=days_ago),
        "qty_neta": qty,
    }


@pytest.fixture
def sales_tomatodo() -> pd.DataFrame:
    """El caso original: vende fuerte el mes 1 (~90-72d), tibio el mes 2,
    nada en el mes 3. 35 unds totales pero ya hace 45+ días muerto."""
    return pd.DataFrame(
        [
            _sales_row(1, 9999, 88, 8),
            _sales_row(1, 9999, 85, 10),
            _sales_row(1, 9999, 80, 7),
            _sales_row(1, 9999, 72, 5),
            _sales_row(1, 9999, 60, 2),
            _sales_row(1, 9999, 55, 2),
            _sales_row(1, 9999, 45, 1),
        ]
    )


@pytest.fixture
def sales_estable() -> pd.DataFrame:
    """Vende 1 und cada 3 días — patrón parejo, sin sesgo temporal.
    Promedio plano y ponderado deben dar lo mismo."""
    return pd.DataFrame(
        [_sales_row(1, 1000, d, 1.0) for d in range(0, 90, 3)]
    )


@pytest.fixture
def sales_vacio() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["bsale_office_id", "bsale_variant_id", "fecha", "qty_neta"]
    )


@pytest.fixture
def stock_basico() -> pd.DataFrame:
    """Stock de los SKUs sintéticos."""
    return pd.DataFrame(
        [
            {"bsale_office_id": 1, "bsale_variant_id": 9999, "stock_disponible": 20},
            {"bsale_office_id": 1, "bsale_variant_id": 1000, "stock_disponible": 30},
        ]
    )
