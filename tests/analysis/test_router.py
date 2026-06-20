"""Tests del contrato HTTP del router de análisis.

Mockean `service.run_classification` y la dependencia `get_db` para que NO
toquen la base de datos — solo verifican el contrato del endpoint:
status codes, paso de filtros, validación de params y traducción de errores.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.analysis import service
from app.database import get_db
from app.main import app


# --- Fixtures -------------------------------------------------------------

async def _fake_db():
    """Dependencia que reemplaza get_db — no abre conexión real."""
    yield object()


@pytest.fixture(autouse=True)
def _override_db():
    app.dependency_overrides[get_db] = _fake_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _fake_result(rows=None, summary=None):
    return {
        "rows": rows if rows is not None else [],
        "summary": summary if summary is not None else {"QUIEBRE": 3, "EXCESO": 2},
        "total": 5,
        "total_filtered": len(rows) if rows else 0,
        "params": {"window_days": 90, "half_life_days": 30.0, "offices": [1, 3]},
        "timings": {"total": 0.5},
    }


# --- /classification ------------------------------------------------------

def test_classification_ok(client, monkeypatch):
    captured = {}

    async def fake_run(db, **kwargs):
        captured.update(kwargs)
        return _fake_result(rows=[{"bsale_variant_id": 1, "clasificacion": "QUIEBRE"}])

    monkeypatch.setattr(service, "run_classification", fake_run)

    r = client.get("/analysis/classification?window_days=60&clasificacion=QUIEBRE&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    # Los query params llegaron al service
    assert captured["window_days"] == 60
    assert captured["clasificacion"] == ["QUIEBRE"]
    assert captured["limit"] == 10


def test_classification_valida_window_fuera_de_rango(client):
    # window_days < 30 -> 422 de FastAPI (validación de Query)
    r = client.get("/analysis/classification?window_days=10")
    assert r.status_code == 422


def test_classification_value_error_es_400(client, monkeypatch):
    async def fake_run(db, **kwargs):
        raise ValueError("módulo desconocido")

    monkeypatch.setattr(service, "run_classification", fake_run)
    r = client.get("/analysis/classification")
    assert r.status_code == 400
    assert "módulo desconocido" in r.json()["detail"]


def test_classification_db_error_es_503(client, monkeypatch):
    async def fake_run(db, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(service, "run_classification", fake_run)
    r = client.get("/analysis/classification")
    assert r.status_code == 503
    assert "base de datos" in r.json()["detail"].lower()


def test_classification_error_inesperado_es_500(client, monkeypatch):
    async def fake_run(db, **kwargs):
        raise RuntimeError("boom inesperado")

    monkeypatch.setattr(service, "run_classification", fake_run)
    r = client.get("/analysis/classification")
    assert r.status_code == 500


# --- /distribution --------------------------------------------------------

def test_distribution_arma_porcentajes(client, monkeypatch):
    async def fake_run(db, **kwargs):
        return _fake_result(summary={"QUIEBRE": 3, "EXCESO": 1})

    monkeypatch.setattr(service, "run_classification", fake_run)
    r = client.get("/analysis/distribution")
    assert r.status_code == 200
    body = r.json()
    dist = {d["clasificacion"]: d for d in body["distribution"]}
    # 3 de 5 = 60%
    assert dist["QUIEBRE"]["n"] == 3
    assert dist["QUIEBRE"]["pct"] == 60.0


# --- /umbrales ------------------------------------------------------------

def test_get_umbrales_devuelve_defaults(client, monkeypatch):
    from app.analysis import router as router_mod
    from app.analysis.classifier import Umbrales

    async def fake_get(db):
        return Umbrales()

    monkeypatch.setattr(router_mod, "get_umbrales", fake_get)
    r = client.get("/analysis/umbrales")
    assert r.status_code == 200
    assert r.json()["umbrales"]["proy_activa_min"] == 10.0


def test_put_umbrales_rechaza_campo_desconocido(client):
    r = client.put("/analysis/umbrales", json={"campo_inexistente": 5})
    assert r.status_code == 400
    assert "desconocido" in r.json()["detail"].lower()


def test_put_umbrales_ok(client, monkeypatch):
    from app.analysis import router as router_mod

    saved = {}

    async def fake_set(db, umbrales):
        saved["umbrales"] = umbrales

    monkeypatch.setattr(router_mod, "set_umbrales", fake_set)
    r = client.put("/analysis/umbrales", json={"proy_activa_min": 15.0})
    assert r.status_code == 200
    assert r.json()["umbrales"]["proy_activa_min"] == 15.0
    assert r.json()["cache_cleared"] is True
    assert saved["umbrales"].proy_activa_min == 15.0


# --- /cache ---------------------------------------------------------------

def test_cache_stats_endpoint(client):
    r = client.get("/analysis/cache/stats")
    assert r.status_code == 200
    assert "ttl_seconds" in r.json()


def test_cache_clear_endpoint(client):
    r = client.post("/analysis/cache/clear")
    assert r.status_code == 200
    assert r.json()["cleared"] is True
