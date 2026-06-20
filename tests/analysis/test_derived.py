"""Tests de los endpoints derivados (action-groups, summary, transfers).

Mockean `service._get_classified` para devolver un DataFrame sintético,
así no tocan la BD — verifican la lógica de agregación y transferencia.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.analysis import _derived, service
from app.analysis.classifier import action_for, CATEGORY_TO_ACTION


# --- Mapeo categoría -> bucket --------------------------------------------

def test_todas_las_categorias_tienen_bucket():
    from app.analysis.classifier import Categoria
    import typing
    cats = typing.get_args(Categoria)
    for c in cats:
        assert c in CATEGORY_TO_ACTION, f"{c} no tiene bucket de acción"


def test_action_for_desconocida_es_otro():
    assert action_for("NO_EXISTE") == "otro"


def test_quiebre_es_urgente():
    assert action_for("QUIEBRE") == "urgente_comprar"


def test_exceso_es_exceso():
    assert action_for("EXCESO") == "exceso"


# --- Fixtures de DataFrame sintético --------------------------------------

def _fake_classified() -> pd.DataFrame:
    """3 SKUs: uno QUIEBRE en Asamblea, uno EXCESO en Magdalena (mismo variant
    para transfer), uno BAJA_ROTACION suelto."""
    return pd.DataFrame([
        {
            "bsale_office_id": 1, "bsale_variant_id": 100,
            "sucursal": "ASAMBLEA", "display_code": "A1", "producto": "Prod A",
            "categoria": "Cat1", "clasificacion": "QUIEBRE",
            "stock_disponible": 0, "velocidad_diaria": 1.0,
            "monto_vendido": 500.0, "v_recent_45d": 20, "v_old_45d": 10,
        },
        {
            "bsale_office_id": 3, "bsale_variant_id": 100,
            "sucursal": "MAGDALENA", "display_code": "A1", "producto": "Prod A",
            "categoria": "Cat1", "clasificacion": "EXCESO",
            "stock_disponible": 100, "velocidad_diaria": 1.0,
            "monto_vendido": 200.0, "v_recent_45d": 5, "v_old_45d": 30,
        },
        {
            "bsale_office_id": 1, "bsale_variant_id": 200,
            "sucursal": "ASAMBLEA", "display_code": "B1", "producto": "Prod B",
            "categoria": "Cat2", "clasificacion": "BAJA_ROTACION",
            "stock_disponible": 50, "velocidad_diaria": 0.1,
            "monto_vendido": 50.0, "v_recent_45d": 1, "v_old_45d": 1,
        },
    ])


@pytest.fixture
def mock_classified(monkeypatch):
    async def fake_get(db, **kwargs):
        return _fake_classified(), [1, 3]
    monkeypatch.setattr(service, "_get_classified_df", fake_get)


# --- action-groups --------------------------------------------------------

@pytest.mark.asyncio
async def test_action_groups_agrupa_y_suma(mock_classified):
    r = await _derived.get_action_groups(db=None)
    g = r["groups"]
    assert g["urgente_comprar"]["n_skus"] == 1
    assert g["exceso"]["n_skus"] == 1
    assert g["liquidar"]["n_skus"] == 1  # BAJA_ROTACION
    assert g["urgente_comprar"]["monto_vendido"] == 500.0
    assert r["total_skus"] == 3


# --- summary --------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_por_sucursal_y_tendencias(mock_classified):
    r = await _derived.get_summary(db=None)
    assert r["monto_total"] == 750.0
    # QUIEBRE: v_recent 20 > v_old 10*1.2=12 -> creciendo
    # EXCESO:  v_recent 5  < v_old 30*0.8=24 -> decayendo
    assert r["creciendo"] == 1
    assert r["decayendo"] == 1
    sucs = {s["sucursal"]: s for s in r["por_sucursal"]}
    assert sucs["ASAMBLEA"]["total_skus"] == 2
    assert sucs["MAGDALENA"]["total_skus"] == 1


# --- transfers ------------------------------------------------------------

@pytest.mark.asyncio
async def test_transfers_detecta_donante_receptor(mock_classified):
    r = await _derived.get_transfers(db=None, dias_cobertura_objetivo=30)
    assert r["total"] == 1
    t = r["transfers"][0]
    assert t["bsale_variant_id"] == 100
    assert t["donante_sucursal"] == "MAGDALENA"   # EXCESO, stock 100
    assert t["receptor_sucursal"] == "ASAMBLEA"   # QUIEBRE, stock 0
    assert t["receptor_clasificacion"] == "QUIEBRE"
    # Donante: vel 1.0 * 30 = 30 mínimo -> excedente 70
    # Receptor: necesita vel 1.0 * 30 - 0 = 30 -> transfiere min(70, 30) = 30
    assert t["unidades_a_transferir"] == 30


@pytest.mark.asyncio
async def test_transfers_sin_donante_no_sugiere(monkeypatch):
    """Si el SKU está en 2 sucursales pero ninguna es donante, no hay transfer."""
    df = pd.DataFrame([
        {
            "bsale_office_id": 1, "bsale_variant_id": 100, "sucursal": "A",
            "display_code": "X", "producto": "P", "categoria": "C",
            "clasificacion": "QUIEBRE", "stock_disponible": 0,
            "velocidad_diaria": 1.0, "monto_vendido": 0,
        },
        {
            "bsale_office_id": 3, "bsale_variant_id": 100, "sucursal": "B",
            "display_code": "X", "producto": "P", "categoria": "C",
            "clasificacion": "ALTA_ROTACION", "stock_disponible": 5,
            "velocidad_diaria": 1.0, "monto_vendido": 0,
        },
    ])

    async def fake_get(db, **kwargs):
        return df, [1, 3]
    monkeypatch.setattr(service, "_get_classified_df", fake_get)

    r = await _derived.get_transfers(db=None)
    assert r["total"] == 0
