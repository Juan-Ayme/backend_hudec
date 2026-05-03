# KAWII - Arquitectura del Sistema BI & API Backend

## Visión General

Sistema de Business Intelligence y API Backend para **KAWII** (producción).
El sistema extrae datos de BSale (POS/ERP), los carga en una base de datos PostgreSQL local, aplica una taxonomía propia (Departamentos > Categorías > Subcategorías) y expone todo a través de una API REST rápida (FastAPI) para analítica, reportes y auditorías.

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  BSale API  │────>│  Harvester   │────>│  PostgreSQL  │<────│   FastAPI    │
│  (bsale.pe) │     │  (Python)    │     │  (local)     │     │  (REST API)  │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
     REST API         Rate limited         Esquema              Endpoints de:
     9 req/s max      TURBO paralelo       Taxonomía            - Analytics
     Catálogos        UPSERT idempt.       Maestros             - Auditoría
     Transacciones    Manejo Errores       Historial            - Productos
```

## Estructura del Proyecto

El proyecto está organizado en módulos claros, separando la recolección de datos (Harvester) de la exposición de datos (App/FastAPI):

```text
produccion/
├── app/                       # Aplicación FastAPI (API REST)
│   ├── main.py                # Punto de entrada de la API
│   ├── database.py            # Conexiones a BD para la API
│   ├── config.py              # Configuraciones de la API
│   └── routers/               # Controladores de Endpoints
│       ├── analytics.py       # KPIs comerciales e inventario
│       ├── audits.py          # Auditoría de datos, huérfanos, inconsistencias
│       ├── products.py        # Catálogo, variantes y overrides
│       ├── stock.py           # Inventario actual
│       ├── sync.py            # Endpoints para disparar sincronizaciones
│       └── taxonomy.py        # Jerarquía: Departamentos > Categorías > Subcategorías
│
├── harvester/                 # Extractor de datos BSale -> PostgreSQL
│   ├── bsale_client.py        # Cliente HTTP: rate limiter, retry, paginación
│   ├── db.py                  # Pool de conexiones para harvester, batch upsert
│   ├── sync_masters.py        # Sync: sucursales, categorías, variantes, stock, costos
│   └── sync_transactions.py   # Sync: documentos de venta y recepciones (TURBO)
│
├── docs/                      # Documentación del Proyecto
│   ├── ARQUITECTURA.md        # Este archivo
│   ├── ESTADO_PROYECTO.md     # Estado actual y tareas pendientes
│   ├── schema.sql             # DDL: Base de datos y Vistas (v_products_full)
│   └── BSALE_API_AUDIT.md     # Detalles técnicos de la API de BSale
│
├── Scripts Principales (CLI)  # Operaciones y Mantenimiento
│   ├── update_all.py                # Orquestador principal: Sincroniza TODO y actualiza taxonomía
│   ├── map_orphans.py               # Auto-asigna y mapea productos "huérfanos" a la taxonomía
│   ├── clean_bsale_categories.py    # NUEVO: Elimina categorías basura/vacías de BSale y BD local
│   ├── run_daily_sync.py            # Sincronización incremental rápida (diaria)
│   ├── run_harvest.py               # Sincronización masiva inicial
│   └── fix_db.py                    # Script de parche para estructura de BD
│
├── .env                       # Variables de entorno y credenciales
└── requirements.txt           # Dependencias (FastAPI, psycopg2, requests, etc.)
```

## Flujo de Datos y Componentes Clave

### 1. Extracción de Datos (Harvester)
Se conecta a la API de BSale manejando los límites estrictos de peticiones (9 req/s). Descarga productos, tipos de productos, variantes, stock, y documentos de ventas utilizando procesamiento paralelo para los grandes volúmenes de documentos (TURBO).

### 2. Taxonomía y Overrides
BSale solo tiene 1 nivel jerárquico (`product_types`). Kawii implementa 3 niveles:
- `departments` > `categories` > `subcategories`.
- Cada `product_type` de BSale se mapea a una `subcategory` de Kawii.
- **Overrides:** Si un producto específico de BSale no encaja en la categoría general, se le puede asignar un `subcategory_id` específico directamente en la tabla `products`.
- La vista `v_products_full` unifica esta lógica para que la API la consuma fácilmente.

### 3. API REST (FastAPI)
Expone los datos procesados en tiempo real (basados en la base de datos PostgreSQL) mediante puertos locales.
- **Puerto por defecto:** 8000
- **Documentación Swagger:** `http://localhost:8000/docs`

## Comandos y Operaciones Frecuentes

### Iniciar el Servidor API
```bash
uvicorn app.main:app --reload
```

### Sincronización Completa del Sistema
Ejecutar cuando se quiera bajar toda la data reciente de BSale y aplicar reglas de taxonomía.
```bash
python scripts/update_all.py --days 365
```

### Limpieza de Categorías Basura (Nuevo)
Este comando detecta categorías de BSale antiguas, sin productos y sin mapeo. Permite eliminarlas permanentemente de BSale y la BD local para optimizar el sistema.
```bash
# Ver lista de candidatas
python scripts/clean_bsale_categories.py

# Ejecutar eliminación permanente
python scripts/clean_bsale_categories.py --execute
```

### Mapeo de Huérfanos (Nuevo)
Asigna automáticamente subcategorías a productos que quedaron fuera del mapeo principal.
```bash
python map_orphans.py
```

## Base de Datos (PostgreSQL)
Conexión: `postgresql://postgres:postgres@localhost:5432/database_kawii_pluss`

**Tablas Principales:**
- `product_types`, `products`, `variants`: Catálogo original de BSale.
- `departments`, `categories`, `subcategories`: Taxonomía Kawii.
- `documents`, `document_details`: Historial de ventas.
- `stock_levels`, `stock_history`: Control de inventario.
- `v_products_full` (Vista): Une productos de BSale con la taxonomía Kawii respetando los overrides individuales.
