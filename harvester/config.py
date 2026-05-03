"""
Configuracion centralizada del Harvester.

Este archivo es el UNICO lugar donde se definen las credenciales y constantes
de conexion. Todo el resto del codigo las importa desde aqui.

Fuente de datos: archivo .env en la raiz del proyecto (produccion/.env).
NO editar credenciales directamente aqui; editarlas en .env.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar el archivo .env que esta en produccion/ (un nivel arriba de este archivo)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


# =============================================================================
# CONFIGURACION DE LA API DE BSALE
# =============================================================================

# Token de autenticacion de BSale (requerido). Se define en .env como BSALE_TOKEN.
BSALE_TOKEN: str = os.environ["BSALE_TOKEN"]

# URL base de la API v1 de BSale (no cambia)
BSALE_BASE_URL: str = "https://api.bsale.io/v1"

# Headers que se envian en cada request a BSale
BSALE_HEADERS: dict = {"access_token": BSALE_TOKEN, "Accept": "application/json"}

# --- Limites y comportamiento del cliente HTTP ---
BSALE_MAX_RPS: int = 9      # Max requests por segundo (limite oficial de BSale)
BSALE_PAGE_SIZE: int = 50   # Registros por pagina (maximo que acepta BSale)
BSALE_TIMEOUT: int = 25     # Segundos antes de considerar un request como fallido
BSALE_MAX_RETRIES: int = 3  # Reintentos automaticos ante errores de red o 5xx
BSALE_MAX_WORKERS: int = 6  # Hilos paralelos para llamadas que se pueden paralelizar
                             # (ej: costos de variantes, atributos de categorias)


# =============================================================================
# CONFIGURACION DE POSTGRESQL
# =============================================================================

# Todas las variables vienen del .env. Si no existen, os.environ lanza KeyError.
DB_NAME = str = os.environ["DB_NAME"]       # Nombre de la base de datos
DB_HOST = str = os.environ["DB_HOST"]       # Host del servidor Postgres (ej: localhost)
DB_PORT = str = os.environ["DB_PORT"]       # Puerto (normalmente 5432)
DB_USER = str = os.environ["DB_USER"]       # Usuario de Postgres
DB_PASSWORD = str = os.environ["DB_PASSWORD"]  # Contrasena de Postgres

# Diccionario listo para pasar a psycopg2.connect(**DB_CONFIG)
DB_CONFIG: dict = {
    "host": os.getenv("DB_HOST", DB_HOST),
    "port": int(os.getenv("DB_PORT", DB_PORT)),
    "dbname": os.getenv("DB_NAME", DB_NAME),
    "user": os.getenv("DB_USER", DB_USER),
    "password": os.getenv("DB_PASSWORD", DB_PASSWORD),
}


# =============================================================================
# SUCURSALES CONOCIDAS
# =============================================================================

# IDs de BSale para las sucursales de tienda (donde se hacen ventas al publico).
# Se usan en los reportes de ventas para EXCLUIR el almacen.
# Magdalena = 1 | Asamblea = 3
OFFICES_TIENDA: list[int] = [1, 3]

# ID del Almacen Central. Solo recibe recepciones, no hace ventas directas.
OFFICE_ALMACEN: int = 4
