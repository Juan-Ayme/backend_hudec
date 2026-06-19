"""Validación funcional del refactor de parametrización.

Corre cada matriz contra la DB real, mide:
  - Tiempo de ejecución (regresión de perf)
  - Total de filas
  - Distribución de clasificaciones (para detectar bucket dominante anómalo)
  - Validez básica: no es 100% NULL en columnas clave

Después hace un TEST DE BINDING: cambia WINDOW_MAIN_DAYS de 90 a 60 y verifica
que la distribución cambia (prueba que el parámetro realmente afecta el SQL).
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Forzar UTF-8 en stdout (Windows usa cp1252 por defecto y los SQL tienen ★/🌱).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_URL = (
    f"postgresql+asyncpg://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
)

from app.kawii_matrix.service import _load_sql, _get_query_params


def label_col_of(row: dict) -> str | None:
    for c in ("Clasificación", "Prioridad / Recomendación", "Diagnóstico", "Diagnóstico Ciclo Vida"):
        if c in row:
            return c
    return None


async def run_module(session: AsyncSession, mod: str, params: dict) -> tuple[int, dict, float]:
    await session.execute(text("SET LOCAL enable_nestloop = off"))
    await session.execute(text("SET LOCAL timezone = 'UTC'"))
    sql = _load_sql(mod)
    t0 = time.monotonic()
    result = await session.execute(text(sql), params)
    rows = result.mappings().all()
    elapsed = time.monotonic() - t0
    if not rows:
        return 0, {}, elapsed
    lc = label_col_of(dict(rows[0]))
    if not lc:
        return len(rows), {"(sin-label)": len(rows)}, elapsed
    counts = Counter(str(r.get(lc) or "(sin)") for r in rows)
    return len(rows), dict(counts), elapsed


async def main() -> int:
    engine = create_async_engine(DB_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    failures = []

    print("=" * 70)
    print("FASE 1 — Smoke test con defaults actuales")
    print("=" * 70)
    baselines = {}
    async with Session() as s:
        for mod in ("04", "04b", "05", "06", "07", "08"):
            try:
                params = _get_query_params()
                total, dist, ms = await run_module(s, mod, params)
                top3 = sorted(dist.items(), key=lambda x: -x[1])[:3]
                print(f"  {mod}: {total:6d} filas | {ms*1000:7.0f}ms | top: {top3}")
                if total == 0:
                    failures.append(f"{mod}: 0 filas")
                if dist and len(dist) == 1:
                    failures.append(f"{mod}: una sola clasificación ({list(dist)[0]})")
                baselines[mod] = (total, dist)
            except Exception as e:
                print(f"  {mod}: EXCEPCIÓN — {type(e).__name__}: {e}")
                failures.append(f"{mod}: {type(e).__name__}: {e}")

    print()
    print("=" * 70)
    print("FASE 2 — Test de binding (cambiar WINDOW_MAIN_DAYS 90 → 60)")
    print("=" * 70)
    print("  Cambiar la ventana operativa debe alterar el número de filas con")
    print("  actividad en la ventana y/o redistribuir clasificaciones.")
    print()
    async with Session() as s:
        for mod in ("04", "07", "08"):
            try:
                params = _get_query_params()
                params["ventana_main_dias"] = 60   # ★ override del default 90
                total60, dist60, _ = await run_module(s, mod, params)
                total90, dist90 = baselines[mod]
                cambio_total = total60 != total90
                cambio_dist = dist60 != dist90
                ok = cambio_total or cambio_dist
                marker = "✓" if ok else "✗ (sospechoso)"
                print(f"  {mod}: {marker} 90d={total90} → 60d={total60}  dist_cambia={cambio_dist}")
                if not ok:
                    failures.append(f"{mod}: ventana_main_dias no afectó el resultado")
            except Exception as e:
                print(f"  {mod}: EXCEPCIÓN — {e}")
                failures.append(f"{mod} (binding test): {e}")

    print()
    print("=" * 70)
    print("FASE 3 — Test de binding (cambiar PROY_MES_ALTA 30 → 1)")
    print("=" * 70)
    print("  Bajar el umbral de 'alta rotación' debería mover MUCHOS SKUs al")
    print("  bucket '🔥 ALTA ROTACIÓN — PRIORIDAD DE COMPRA'.")
    print()
    async with Session() as s:
        try:
            params = _get_query_params()
            params["proy_mes_alta"] = 1   # ★ default 30
            _, dist_low, _ = await run_module(s, "04", params)
            _, dist_normal = baselines["04"]
            alta_low = sum(v for k, v in dist_low.items() if "ALTA ROTACIÓN" in k)
            alta_normal = sum(v for k, v in dist_normal.items() if "ALTA ROTACIÓN" in k)
            cambio = alta_low > alta_normal
            marker = "✓" if cambio else "✗ (sospechoso)"
            print(f"  04: {marker} ALTA ROTACIÓN @ proy_alta=30 → {alta_normal} | @ proy_alta=1 → {alta_low}")
            if not cambio:
                failures.append("proy_mes_alta no afectó conteo de ALTA ROTACIÓN")
        except Exception as e:
            print(f"  EXCEPCIÓN — {e}")
            failures.append(f"proy_mes_alta test: {e}")

    print()
    print("=" * 70)
    print("FASE 4 — Test de binding (cambiar BSALE_WAREHOUSE_USER_IDS)")
    print("=" * 70)
    print("  Cambiar qué usuarios cuentan como almaceneros debe cambiar el campo")
    print("  'Últ. Recepción' / 'Llegó hace (días)' en muchos SKUs.")
    print()
    async with Session() as s:
        try:
            params = _get_query_params()
            params["warehouse_user_ids"] = [999999]  # ningún user real
            total_x, _, _ = await run_module(s, "04", params)
            total_normal, _ = baselines["04"]
            print(f"  04: warehouse_users normal → {total_normal} filas")
            print(f"      warehouse_users=[999999] → {total_x} filas")
            # Aquí el cambio debe verse en los datos, no en la cantidad — verifiquemos
            # las fechas de última recepción.
            sql = _load_sql("04")
            r1 = (await s.execute(text(sql), _get_query_params())).mappings().all()
            params2 = _get_query_params(); params2["warehouse_user_ids"] = [999999]
            r2 = (await s.execute(text(sql), params2)).mappings().all()
            with_recep_normal = sum(1 for r in r1 if r.get("Últ. Recepción"))
            with_recep_x      = sum(1 for r in r2 if r.get("Últ. Recepción"))
            print(f"      SKUs con 'Últ. Recepción' poblada:  {with_recep_normal} → {with_recep_x}")
            if with_recep_x >= with_recep_normal:
                failures.append("warehouse_user_ids no afectó 'Últ. Recepción' (debería caer)")
            else:
                print(f"      ✓ cambio detectado: {with_recep_normal - with_recep_x} SKUs perdieron 'Últ. Recepción'")
        except Exception as e:
            print(f"  EXCEPCIÓN — {e}")
            failures.append(f"warehouse_user_ids test: {e}")

    await engine.dispose()

    print()
    print("=" * 70)
    print("RESULTADO")
    print("=" * 70)
    if failures:
        print(f"  ✗ {len(failures)} fallas:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  ✓ Todas las validaciones pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
