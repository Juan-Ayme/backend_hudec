"""Probe: cuenta filas de CTEs intermedias en 04 vs 05 para hallar dónde divergen."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

CTES = ["stock_sucursal", "ventas_90d", "recep_90d", "base", "radiografia", "metricas_reciente"]


def cut_sql(path: Path, cte: str) -> str:
    sql = path.read_text(encoding="utf-8")
    # El SELECT final empieza tras el cierre de la última CTE: "\n)\nSELECT"
    idx = sql.rindex("\n)\nSELECT")
    return sql[: idx + 2] + f"\nSELECT COUNT(*) AS n FROM {cte};"


async def main() -> None:
    from sqlalchemy import text
    from app.database import async_session_maker, engine
    from app.kawii_matrix.service import _get_query_params
    from app.routers.config_admin import get_exclusions, get_seasonal

    files = {
        "04": ROOT / "app/kawii_matrix/sql/04_matriz_90d.sql",
        "05": ROOT / "app/kawii_matrix/sql/05_matriz_operativa.sql",
    }
    async with async_session_maker() as db:
        params = _get_query_params()
        excl = await get_exclusions(db)
        params["excluded_departments"] = excl["departments"]
        params["excluded_categories"] = excl["categories"]
        params["seasonal_departments"] = await get_seasonal(db)
        params.pop("timezone", None)

        for cte in CTES:
            counts = {}
            for mod, path in files.items():
                await db.execute(text("SET LOCAL enable_nestloop = off"))
                await db.execute(text("SET LOCAL timezone = 'UTC'"))
                sql = cut_sql(path, cte)
                # quitar binds no usados por el fragmento
                used = set(re.findall(r":(\w+)", sql))
                p = {k: v for k, v in params.items() if k in used}
                n = await db.scalar(text(sql), p)
                counts[mod] = n
            flag = "  <-- DIVERGE" if counts["04"] != counts["05"] else ""
            print(f"{cte:20s} 04={counts['04']:6d}  05={counts['05']:6d}{flag}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
