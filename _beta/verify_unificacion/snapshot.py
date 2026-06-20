"""
Snapshot de las matrices 04/04b/05 para verificar la unificación del SQL.

Uso:
    python -m _beta.verify_unificacion.snapshot before
    python -m _beta.verify_unificacion.snapshot after
    python -m _beta.verify_unificacion.snapshot compare

Ejecuta cada módulo por el MISMO camino que producción (service.run_matrix,
incluye SET LOCAL timezone/enable_nestloop y exclusiones desde app_config) y
guarda un JSON canónico (filas ordenadas por su representación completa, para
no depender del orden no determinista de empates del ORDER BY).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

MODULES = ["04", "04b", "05"]


def canon(obj):
    """JSON canónico: Decimals/fechas a str, claves ordenadas."""
    return json.dumps(obj, default=str, sort_keys=True, ensure_ascii=False)


async def snapshot(tag: str) -> None:
    from app.database import async_session_maker, engine
    from app.kawii_matrix import service

    for mod in MODULES:
        async with async_session_maker() as db:
            t0 = time.perf_counter()
            res = await service.run_matrix(db, mod)
            elapsed = time.perf_counter() - t0
        rows_canon = sorted(canon(r) for r in res["rows"])
        out = {
            "module": mod,
            "columns": res["columns"],
            "total": res["total"],
            "rows": rows_canon,
        }
        path = HERE / f"{tag}_{mod}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{tag}] módulo {mod}: {res['total']} filas, "
              f"{len(res['columns'])} columnas, {elapsed:.1f}s -> {path.name}")
    await engine.dispose()


def compare() -> int:
    rc = 0
    for mod in MODULES:
        before = json.loads((HERE / f"before_{mod}.json").read_text(encoding="utf-8"))
        after = json.loads((HERE / f"after_{mod}.json").read_text(encoding="utf-8"))
        problems = []
        if before["columns"] != after["columns"]:
            b, a = before["columns"], after["columns"]
            extra = [c for c in a if c not in b]
            missing = [c for c in b if c not in a]
            problems.append(f"columnas distintas (faltan={missing}, sobran={extra}, "
                            f"orden_igual={[c for c in b if c in a] == [c for c in a if c in b]})")
        if before["total"] != after["total"]:
            problems.append(f"total filas: {before['total']} -> {after['total']}")
        if before["rows"] != after["rows"]:
            b_set, a_set = set(before["rows"]), set(after["rows"])
            only_b, only_a = b_set - a_set, a_set - b_set
            problems.append(f"filas distintas: {len(only_b)} solo-antes, {len(only_a)} solo-después")
            for r in list(only_b)[:2]:
                print(f"  [{mod}] solo ANTES: {r[:400]}")
            for r in list(only_a)[:2]:
                print(f"  [{mod}] solo DESPUÉS: {r[:400]}")
        if problems:
            rc = 1
            print(f"[FAIL] módulo {mod}: " + "; ".join(problems))
        else:
            print(f"[OK]   módulo {mod}: {before['total']} filas idénticas, "
                  f"{len(before['columns'])} columnas idénticas")
    return rc


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"
    if mode == "compare":
        raise SystemExit(compare())
    asyncio.run(snapshot(mode))
