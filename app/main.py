"""
KAWII Backend API - entrypoint FastAPI.

Levantar en dev:
    cd produccion
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Docs interactivas:
    http://localhost:8000/docs       (Swagger UI)
    http://localhost:8000/redoc      (ReDoc)

Nota: el frontend/dashboard es un proyecto separado que consume esta API.
Esta API NO sirve archivos estaticos.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import engine
from sqlalchemy import text
from app.routers import (
    analytics,
    audits,
    bsale_admin,
    config_admin,
    matrix_simulator,
    products,
    sync,
    taxonomy,
    taxonomy_admin,
)
from app.kawii_matrix.router import router as matrix_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("kawii.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: crea/siembra la tabla de configuración runtime. Shutdown: cierra."""
    logger.info("Iniciando KAWII API...")
    # Tabla key/value para configuración mutable en runtime: exclusiones de
    # departamentos/categorías editables desde la UI (pantalla Configuración).
    # La DB es la fuente de verdad; se guardan por NOMBRE (JSON) para sobrevivir a
    # los re-seeds de la taxonomía (los IDs se reasignan). Se siembra VACÍO; el
    # usuario define las exclusiones desde la UI.
    try:
        import json as _json
        from harvester.config import (
            EXCLUDED_DEPARTMENT_NAMES,
            EXCLUDED_CATEGORY_NAMES,
            SEASONAL_DEPARTMENT_NAMES,
        )
        # Siembra inicial desde .env (POR NOMBRE). Solo aplica al PRIMER arranque de
        # cada empresa (ON CONFLICT DO NOTHING): replicar una empresa = poner sus
        # nombres en el .env y arrancar. Luego la UI (Configuración) puede ajustar.
        seed = {
            "excluded_departments": _json.dumps(EXCLUDED_DEPARTMENT_NAMES, ensure_ascii=False),
            "excluded_categories": _json.dumps(EXCLUDED_CATEGORY_NAMES, ensure_ascii=False),
            "seasonal_departments": _json.dumps(SEASONAL_DEPARTMENT_NAMES, ensure_ascii=False),
        }
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS app_config ("
                " key TEXT PRIMARY KEY,"
                " value TEXT NOT NULL DEFAULT '',"
                " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            ))
            for key, val in seed.items():
                await conn.execute(
                    text("INSERT INTO app_config (key, value) VALUES (:k, :v)"
                         " ON CONFLICT (key) DO NOTHING"),
                    {"k": key, "v": val},
                )
        logger.info("app_config lista (exclusiones por nombre; sembradas de .env si vacío).")
    except Exception as exc:
        logger.exception("No se pudo inicializar app_config: %s", exc)
    yield
    logger.info("Apagando KAWII API...")
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "API REST sobre la base de datos KAWII (PostgreSQL + ETL BSale). "
        "Expone taxonomia, productos, analytics y matriz de clasificación, "
        "y permite disparar sincronizaciones."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Routers ----
app.include_router(taxonomy.router)
app.include_router(taxonomy_admin.router)   # CRUD interno (departments/categories/subcategories)
app.include_router(bsale_admin.router)      # CRUD que escribe a BSale (product_types)
app.include_router(products.router)
app.include_router(analytics.router)
app.include_router(sync.router)
app.include_router(audits.router)
app.include_router(config_admin.router)     # /config/* — configuración runtime (exclusiones)
app.include_router(matrix_router)  # /matrix/* — matrices de clasificación inteligente
app.include_router(matrix_simulator.router)  # /matrix-sim/* — debugger por SKU del simulador de cascada


# ---- Root / health ----

@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

@app.get("/health", tags=["meta"])
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Healthcheck con ping a la BD."""
    try:
        db_version = await db.scalar(text("SELECT version()"))
        db_ok = "ok"
        productos = await db.scalar(text("SELECT COUNT(*) FROM products"))
    except Exception as exc:
        logger.exception("Health check DB fallo: %s", exc)
        db_ok = f"error: {exc}"
        db_version = None
        productos = None

    return {
        "status": "ok" if db_ok == "ok" else "degraded",
        "db": db_ok,
        "db_version": db_version.split(",")[0] if db_version else None,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "productos_en_bd": productos,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---- Error handler global ----

@app.exception_handler(Exception)
async def unhandled_exception(request, exc):
    """
    Captura cualquier excepcion no manejada y devuelve 500 JSON.

    Importante: los exception handlers de FastAPI NO pasan por el CORSMiddleware,
    asi que tenemos que agregar los headers CORS a mano. Sin esto el browser
    bloquea la respuesta con CORS error y el frontend ve un generico
    'Failed to fetch' en vez del 500 con detalle.
    """
    logger.exception("Error no manejado en %s %s: %s", request.method, request.url, exc)

    # Echo del Origin del request (o '*') en Access-Control-Allow-Origin para
    # respetar la lista CORS_ORIGINS configurada.
    origin = request.headers.get("origin", "*")
    settings = get_settings()
    allowed = settings.CORS_ORIGINS
    if "*" in allowed or origin in allowed:
        allow_origin = origin
    else:
        allow_origin = allowed[0] if allowed else "*"

    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
        headers={
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        },
    )


