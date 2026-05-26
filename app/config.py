"""
Settings del backend (FastAPI).

Carga la configuracion desde el archivo .env usando pydantic-settings.
Si una variable no esta en .env, se usa el valor por defecto definido aqui.

NO importar este modulo directamente en codigo de harvester;
los settings de harvester estan en harvester/config.py.

Uso:
    from app.config import get_settings
    settings = get_settings()  # singleton con cache, seguro llamarlo multiples veces
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

# Reutilizamos la config de conexion del harvester (misma DB, diferente pool)
from harvester.config import DB_CONFIG


class Settings(BaseSettings):
    """Configuracion de la API FastAPI. Cada campo puede sobreescribirse via .env."""

    # Lee automaticamente variables desde produccion/.env
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Identificacion de la app ---
    APP_NAME: str = "HUDEC Inventory BI"   # Aparece en /docs (Swagger) y en /health
    APP_VERSION: str = "1.0.0"    # Version semantica
    DEBUG: bool = False           # True = logs mas detallados (NO usar en produccion)

    # --- Configuracion de marca (White-label) ---
    BRAND_NAME: str = "hudec"
    CLASSIFICATION_LABEL: str = "Clasificación HUDEC"
    TIMEZONE: str = "America/Lima"


    # --- CORS (Cross-Origin Resource Sharing) ---
    # Lista de origenes permitidos para hacer requests a la API desde el navegador.
    # "*" = cualquier origen (OK en desarrollo; restringir en produccion con el dominio real).
    CORS_ORIGINS: list[str] = ["*"]

    # --- Paginacion de respuestas ---
    DEFAULT_PAGE_SIZE: int = 50   # Registros por pagina si el cliente no especifica
    MAX_PAGE_SIZE: int = 500      # Maximo que el cliente puede pedir en un request

    # --- Pool de conexiones Postgres ---
    DB_POOL_MIN: int = 1   # Conexiones minimas que se mantienen abiertas
    DB_POOL_MAX: int = 10  # Maximo de conexiones simultaneas al Postgres


@lru_cache  # Se instancia una sola vez y se reutiliza (patron singleton)
def get_settings() -> Settings:
    """Retorna la instancia singleton de Settings. Cachea el resultado."""
    return Settings()


def get_db_config() -> dict:
    """Devuelve el diccionario de conexion a Postgres (mismo que usa el harvester)."""
    return DB_CONFIG
