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
# SUCURSALES CONOCIDAS Y PARÁMETROS OPERATIVOS
# =============================================================================

# IDs de BSale para las sucursales de tienda (donde se hacen ventas al publico).
# Se usan en los reportes de ventas para EXCLUIR el almacen.
OFFICES_TIENDA: list[int] = [
    int(x.strip()) for x in os.environ.get("OFFICES_TIENDA", "1,3").split(",") if x.strip()
]

# ID del Almacen Central. Solo recibe recepciones, no hace ventas directas.
OFFICE_ALMACEN: int = int(os.environ.get("OFFICE_ALMACEN", "4"))

# IDs de documentos de venta y devoluciones de BSale
TIPOS_VENTA: list[int] = [
    int(x.strip()) for x in os.environ.get("TIPOS_VENTA", "1,10,50,51,52,53").split(",") if x.strip()
]
TIPOS_DEVOLUCION: list[int] = [
    int(x.strip()) for x in os.environ.get("TIPOS_DEVOLUCION", "9,40,43").split(",") if x.strip()
]

# IDs de documentos de TRASLADO INTERNO entre sucursales.
# En COYA (sistema actual) el id es 53. Si en otro deployment es 37, ajustar en .env.
# Se usa en los SQL de las matrices para no contar traslados como pérdidas
# (sell-through real = ventas + consumos + traslados).
TIPOS_TRASLADO: list[int] = [
    int(x.strip()) for x in os.environ.get("TIPOS_TRASLADO", "53").split(",") if x.strip()
]

# Exclusiones de departamentos y categorías
EXCLUDED_DEPARTMENTS: list[int] = [
    int(x.strip()) for x in os.environ.get("EXCLUDED_DEPARTMENTS", "11,12").split(",") if x.strip()
]
EXCLUDED_CATEGORIES: list[int] = [
    int(x.strip()) for x in os.environ.get("EXCLUDED_CATEGORIES", "73,74,75,76").split(",") if x.strip()
]

# IDs de categorías objetivo a analizar (para el reporte de salud)
TARGET_CATEGORIES: list[int] = [
    int(x.strip()) for x in os.environ.get("TARGET_CATEGORIES", "228,221,145").split(",") if x.strip()
]


