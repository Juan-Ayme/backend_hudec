# KAWII Backend — Guía de Mantenimiento

> **Proyecto:** Pipeline ETL + API REST para análisis de datos del ERP de Kawii / Grupo Hudec.  
> **Stack:** Python 3.11 · FastAPI · PostgreSQL · BSale API

---

## ¿De qué trata este proyecto?

Kawii tiene su operación registrada en **BSale** (ERP en la nube).  
Este backend:

1. **Descarga** (harvesta) automáticamente los datos de BSale cada día.
2. **Los guarda** en una base de datos PostgreSQL local, organizada con una taxonomía propia (Departamentos → Categorías → Subcategorías).
3. **Expone una API REST** (FastAPI) para que el frontend externo pueda consultar KPIs, ventas, stock e inventario.

---

## Estructura del proyecto

```
produccion/
│
├── .env                        ← Variables de entorno (NO subir a git)
├── requirements.txt            ← Dependencias Python
├── run_daily_sync.py           ← Script principal de sincronización diaria (ETL)
├── daily_sync.log              ← Log generado por run_daily_sync.py
│
├── harvester/                  ← Módulo ETL: extrae datos de BSale y los guarda en Postgres
│   ├── config.py               ← Credenciales BSale + Postgres (lee .env)
│   ├── bsale_client.py         ← Cliente HTTP para la API de BSale
│   ├── db.py                   ← Pool de conexiones + helpers SQL para el harvester
│   ├── sync_masters.py         ← Sincroniza entidades maestras (productos, stock, categorías)
│   └── sync_transactions.py    ← Sincroniza transacciones (documentos de venta, recepciones)
│
├── app/                        ← API REST (FastAPI)
│   ├── main.py                 ← Entrypoint: registra routers, CORS, sirve el frontend
│   ├── config.py               ← Settings de la API (lee .env vía pydantic-settings)
│   ├── database.py             ← Pool de conexiones Postgres para la API
│   ├── schemas.py              ← Modelos Pydantic (forma de los JSON de respuesta)
│   └── routers/                ← Endpoints agrupados por dominio:
│       ├── taxonomy.py         ←   Consulta árbol Departamento/Categoría/Subcategoría
│       ├── taxonomy_admin.py   ←   CRUD interno de la taxonomía propia
│       ├── bsale_admin.py      ←   CRUD que escribe directamente a BSale (product_types)
│       ├── products.py         ←   Listado y detalle de productos/variantes
│       ├── stock.py            ←   Stock por sucursal y valorización
│       ├── documents.py        ←   Documentos de venta (boletas, facturas, etc.)
│       ├── analytics.py        ←   KPIs y ventas del dashboard
│       ├── analytics_advanced.py← Análisis de ticket y métricas de inventario avanzadas
│       ├── sync.py             ←   Dispara sincronizaciones manuales desde la API
│       └── audits.py           ←   Auditoría y calidad de datos
│
├── Nueva_estructura/
│   └── Estructura_inicial.json ← Taxonomía interna (fuente de verdad de categorías)
│
├── scripts/                    ← Scripts de mantenimiento y auditoría (uso puntual)
│   ├── audit_final.py          ← Auditoría completa ventas BSale vs Postgres
│   ├── audit_deep.py           ← Auditoría profunda por día
│   ├── audit_detail.py         ← Detalle de discrepancias en documentos
│   ├── audit_ventas_7d.py      ← Auditoría ventas últimos 7 días
│   ├── clean_bsale_categories.py ← Limpia categorías BSale sin productos
│   ├── fix_db.py               ← Correcciones puntuales de datos en Postgres
│   ├── map_orphans.py          ← Mapea product_types huérfanos a la taxonomía
│   ├── simulacro_limpieza_product_types.py ← Simulacro (dry-run) de limpieza
│   ├── update_all.py           ← Actualización masiva de categorías en BSale vía API
│   ├── verify_bsale_sales.py   ← Verifica ventas contra BSale
│   └── verify_doctypes.py      ← Verifica tipos de documento
│
├── analytics_scripts/          ← Scripts de análisis pesado (generan reportes)
│   ├── config.py               ← Config compartida de analytics
│   ├── db_helper.py            ← Helpers de conexión para analytics
│   ├── inventory_analysis.py   ← Análisis de inventario (rotación, valorización)
│   ├── ticket_analysis.py      ← Análisis de ticket promedio
│   ├── ticket_diagnostico.py   ← Diagnóstico detallado de tickets
│   ├── cleanup_basale.py       ← Limpieza de datos BSale
│   ├── cleanup_empty_categories.py ← Elimina categorías vacías de la DB
│   ├── diagnostico_basale.py   ← Diagnóstico general BSale vs Postgres
│   ├── generate_report.py      ← Genera informe PDF completo
│   └── run_all.py              ← Ejecuta todos los análisis en secuencia
│
├── docs/                       ← Documentación técnica
│   ├── ARQUITECTURA.md         ← Diagrama y descripción de la arquitectura
│   ├── BSALE_API_AUDIT.md      ← Auditoría detallada de la API de BSale
│   ├── ESTADO_PROYECTO.md      ← Estado actual y decisiones técnicas
│   └── schema.sql              ← Schema SQL de la base de datos
│
├── reports/                    ← Reportes generados (PDFs, CSVs)
├── logs/                       ← Logs históricos
├── postman/                    ← Colección Postman para probar la API
└── informe_kawii.pdf           ← Último informe generado
```

---

## Cómo levantar el sistema

### 1. Requisitos previos
- Python 3.11+
- PostgreSQL 14+ corriendo localmente
- Credenciales en el archivo `.env` (ver sección abajo)

### 2. Instalar dependencias
```bash
cd produccion
pip install -r requirements.txt
```

### 3. Configurar `.env`
```env
# BSale API
BSALE_TOKEN=tu_token_de_bsale

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=kawii_db
DB_USER=postgres
DB_PASSWORD=tu_password
```

### 4. Levantar la API
```bash
cd produccion
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Swagger UI: http://localhost:8000/docs  
- Health check: http://localhost:8000/health

### 5. Ejecutar la sincronización diaria (ETL)
```bash
# Sincroniza los últimos 6 días (recomendado para uso normal)
python run_daily_sync.py

# Sincronizar solo el último día
python run_daily_sync.py --days 1

# Sincronizar los últimos 30 días (para recarga histórica)
python run_daily_sync.py --days 30
```

---

## Flujo de datos (cómo funciona todo junto)

```
BSale API (nube)
      │
      ▼
harvester/bsale_client.py    ← Hace las llamadas HTTP con rate limiting y reintentos
      │
      ▼
harvester/sync_masters.py    ← Guarda: productos, variantes, categorías, stock, sucursales
harvester/sync_transactions.py ← Guarda: documentos de venta, recepciones
      │
      ▼
PostgreSQL (local)           ← Base de datos local con la taxonomía Kawii aplicada
      │
      ▼
app/ (FastAPI)               ← API que consulta Postgres y responde JSON
      │
      ▼
frontend/ (dashboard JS)     ← Visualización en el navegador
```

---

## La taxonomía de categorías

Kawii tiene su propia jerarquía de categorías, **independiente** de BSale:

```
Departamento  →  Categoría  →  Subcategoría
   Alimentos  →  Dulces     →  Chocolates
   Alimentos  →  Bebidas    →  Jugos
   ...
```

**Fuente de verdad:** `Nueva_estructura/Estructura_inicial.json`

Cada vez que se ejecuta `run_daily_sync.py`, el paso `sync_taxonomy()` siembra esta jerarquía en la tabla `departments/categories/subcategories` de Postgres, y luego `sync_product_types()` intenta mapear cada categoría de BSale a una subcategoría de esa jerarquía.

---

## Sucursales conocidas

| ID BSale | Nombre         | Tipo      |
|----------|----------------|-----------|
| 1        | Magdalena       | Tienda    |
| 3        | Asamblea        | Tienda    |
| 4        | Almacén Central | Almacén   |

> ⚠️ Los reportes de ventas solo consideran las **sucursales 1 y 3**. El almacén (4) no tiene ventas directas al público.

---

## Scripts de mantenimiento rápido

| Script | Cuándo usarlo |
|--------|---------------|
| `scripts/audit_final.py` | Verificar que las ventas en Postgres coinciden con BSale |
| `scripts/fix_db.py` | Correcciones puntuales en la DB (leer el script antes de ejecutar) |
| `scripts/map_orphans.py` | Cuando hay product_types sin mapear en la taxonomía |
| `analytics_scripts/generate_report.py` | Generar el informe PDF mensual |
| `analytics_scripts/run_all.py` | Ejecutar todos los análisis en secuencia |

---

## Dependencias principales

| Librería | Uso |
|----------|-----|
| `fastapi` | Framework de la API REST |
| `uvicorn` | Servidor ASGI para FastAPI |
| `psycopg2-binary` | Driver de PostgreSQL |
| `pydantic` + `pydantic-settings` | Validación de datos y configuración |
| `requests` | Llamadas HTTP a BSale |
| `python-dotenv` | Leer el archivo `.env` |

---

## Automatización con Windows Task Scheduler

Para que la sincronización corra todos los días automáticamente:

1. Abrir **Task Scheduler** de Windows
2. Crear tarea → Ejecutar diariamente a las 3:00 AM
3. Acción: `python C:\ruta\al\proyecto\produccion\run_daily_sync.py`
4. El log queda en `produccion/daily_sync.log`

---

## Contacto y mantenimiento

- **Desarrollado para:** Kawii / Grupo Hudec
- **Tecnologías:** Python 3.11, FastAPI, PostgreSQL, BSale API v1
- **Última revisión:** Mayo 2026
