"""Test directo: ¿el param sellthrough_exito_ratio realmente cambia el SQL?"""
import asyncio, os, sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv; load_dotenv()
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.kawii_matrix.service import _load_sql, _get_query_params

DB_URL = (
    f"postgresql+asyncpg://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
)


async def main():
    engine = create_async_engine(DB_URL, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sql = _load_sql("04")

    async with Session() as s:
        await s.execute(text("SET LOCAL enable_nestloop = off"))
        await s.execute(text("SET LOCAL timezone = 'UTC'"))

        for ratio in (0.80, 0.50, 0.01):
            params = _get_query_params()
            params["sellthrough_exito_ratio"] = ratio
            r = await s.execute(text(sql), params)
            rows = r.mappings().all()
            labels = Counter(r["Clasificación"] for r in rows)
            section_b = sum(v for k, v in labels.items() if any(t in k for t in ("BESTSELLER", "OPORTUNIDAD PERDIDA", "DEMANDA EXTINTA", "LENTO PERO CONSTANTE", "PASADO")))
            section_c = sum(v for k, v in labels.items() if any(t in k for t in ("AGOTADO POTENCIAL", "EX-BESTSELLER", "AGOTADO CON DEMANDA", "BAJO VOLUMEN AGOTADO", "AGOTADO NO PRIORITARIO")))
            print(f"ratio={ratio:.2f}  SecB(vendió todo)={section_b:4d}  SecC(stk0 sin vender todo)={section_c:4d}")

    await engine.dispose()


asyncio.run(main())
