"""
Pool de conexiones Postgres para la API (FastAPI).

Este modulo es INDEPENDIENTE del harvester/db.py.
Ambos apuntan a la misma base de datos pero mantienen sus propios pools
para que la API y el ETL no compitan por conexiones.

Ciclo de vida del pool:
  - Se inicializa en el startup de FastAPI (lifespan en main.py)
  - Se cierra en el shutdown de FastAPI
  - Las conexiones se obtienen con get_conn() como context manager

Uso tipico:
    from app.database import fetch_all, fetch_one, fetch_scalar

    rows = fetch_all("SELECT * FROM products WHERE is_active = TRUE")
    row  = fetch_one("SELECT * FROM products WHERE bsale_product_id = %s", (id,))
    val  = fetch_scalar("SELECT COUNT(*) FROM products")
"""

import logging
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
import psycopg2.pool

from app.config import get_db_config, get_settings

logger = logging.getLogger(__name__)

# Pool global; se inicializa en init_db_pool() y se cierra en close_db_pool()
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_db_pool() -> None:
    """
    Crea el pool de conexiones Postgres.

    - Solo se llama UNA VEZ en el startup de la API (main.py lifespan).
    - Si el pool ya existe, la funcion retorna sin hacer nada (idempotente).
    - ThreadedConnectionPool es seguro para entornos multi-hilo (uvicorn usa hilos).
    """
    global _pool
    if _pool is not None:
        return  # Ya inicializado, no duplicar
    cfg = get_db_config()
    settings = get_settings()
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=settings.DB_POOL_MIN,
        maxconn=settings.DB_POOL_MAX,
        **cfg,
    )
    logger.info(
        "DB pool inicializado %s:%s/%s (min=%d max=%d)",
        cfg["host"], cfg["port"], cfg["dbname"],
        settings.DB_POOL_MIN, settings.DB_POOL_MAX,
    )


def close_db_pool() -> None:
    """Cierra todas las conexiones del pool. Llamar en el shutdown de la API."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB pool cerrado")


@contextmanager
def get_conn() -> Iterator[psycopg2.extensions.connection]:
    """
    Context manager que entrega una conexion del pool.

    - Hace commit automatico al salir del bloque `with`.
    - Hace rollback automatico si ocurre una excepcion.
    - Devuelve la conexion al pool siempre (bloque finally).

    Uso:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE ...")
    """
    if _pool is None:
        raise RuntimeError("DB pool no inicializado. Llama a init_db_pool() primero.")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()   # Exito: confirmar cambios
    except Exception:
        conn.rollback() # Error: deshacer cambios
        raise
    finally:
        _pool.putconn(conn)  # Devolver conexion al pool (siempre)


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    """
    Ejecuta un SELECT y devuelve TODOS los resultados como lista de dicts.

    Cada fila es un dict donde las claves son los nombres de las columnas.
    Retorna lista vacia si no hay resultados.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def fetch_one(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    """Ejecuta un SELECT y devuelve la PRIMERA fila como dict, o None si no hay resultados."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_scalar(sql: str, params: tuple | dict = ()) -> Any:
    """
    Ejecuta un SELECT y devuelve un UNICO valor escalar (primera columna, primera fila).

    Ideal para COUNT(*), SUM(), MAX(), etc.
    Retorna None si no hay resultado.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
