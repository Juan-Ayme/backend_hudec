"""Tests del cache TTL y la clave determinística."""

from __future__ import annotations

import time

from app.analysis._cache import TTLCache, make_key
from app.analysis.classifier import Umbrales


def test_set_get_basico():
    c = TTLCache(ttl_seconds=10)
    c.set("k", "v")
    assert c.get("k") == "v"
    assert c.hits == 1
    assert c.misses == 0


def test_miss_incrementa_contador():
    c = TTLCache(ttl_seconds=10)
    assert c.get("ausente") is None
    assert c.misses == 1


def test_expiracion_por_ttl():
    c = TTLCache(ttl_seconds=0)  # expira inmediatamente
    c.set("k", "v")
    time.sleep(0.01)
    assert c.get("k") is None  # ya expiró


def test_eviction_al_llegar_al_tope():
    c = TTLCache(ttl_seconds=100, max_entries=2)
    c.set("a", 1)
    time.sleep(0.01)
    c.set("b", 2)
    time.sleep(0.01)
    c.set("c", 3)  # debe evictar "a" (la más vieja)
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_clear():
    c = TTLCache()
    c.set("k", "v")
    c.clear()
    assert c.get("k") is None


def test_make_key_determinista():
    k1 = make_key(window_days=90, half_life_days=30, offices=[1, 3], umbrales=None)
    k2 = make_key(window_days=90, half_life_days=30, offices=[3, 1], umbrales=None)
    assert k1 == k2  # orden de offices no importa


def test_make_key_distinto_por_window():
    k1 = make_key(window_days=90, half_life_days=30, offices=[1], umbrales=None)
    k2 = make_key(window_days=60, half_life_days=30, offices=[1], umbrales=None)
    assert k1 != k2


def test_make_key_distinto_por_umbrales():
    k_default = make_key(window_days=90, half_life_days=30, offices=[1], umbrales=Umbrales())
    k_custom = make_key(
        window_days=90, half_life_days=30, offices=[1],
        umbrales=Umbrales(proy_activa_min=15.0),
    )
    assert k_default != k_custom


def test_stats_estructura():
    c = TTLCache(ttl_seconds=42)
    s = c.stats()
    assert s["ttl_seconds"] == 42
    assert s["entries"] == 0
