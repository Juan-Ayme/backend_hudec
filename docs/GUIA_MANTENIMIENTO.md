# Guía de Mantenimiento — KAWII Backend

> **Objetivo:** Documento de referencia para la persona que da mantenimiento al sistema.  
> **Última revisión:** Mayo 2026  
> **Estado:** En producción ✅

---

## ¿Qué hace este sistema?

Este backend es el "cerebro analítico" de Kawii. En resumen:

1. Cada día baja automáticamente los datos de ventas, productos e inventario desde **BSale** (el ERP que usan las tiendas).
2. Los guarda en una base de datos **PostgreSQL** local, organizada con la taxonomía propia de Kawii (Departamentos > Categorías > Subcategorías).
3. Una **API REST** (FastAPI) expone esos datos para que el **frontend externo** pueda consumirlos (KPIs, ventas, stock, inventario).

---

## Los archivos más importantes (start here)

| Archivo | Qué hace | Con qué frecuencia se toca |
|---------|----------|---------------------------|
| `.env` | Credenciales (tokens BSale, acceso Postgres) | Solo si cambian las credenciales |
| `run_daily_sync.py` | Script ETL que corre diario | Rara vez (ya funciona solo) |
| `Nueva_estructura/Estructura_inicial.json` | Jerarquía de categorías (fuente de verdad) | Cuando se agrega/quita categorías |
| `app/main.py` | Punto de entrada de la API | Cuando se agrega un nuevo router |
| `harvester/sync_masters.py` | Sincroniza productos, stock, categorías | Si BSale cambia sus endpoints |
| `harvester/sync_transactions.py` | Sincroniza documentos de venta | Si hay cambios en documentos |

---

## Routers de la API — ¿qué endpoint está en qué archivo?

Todos los endpoints viven en `app/routers/`. Aquí está el mapa:

| Archivo | Prefijo URL | Qué hace |
|---------|-------------|----------|
| `taxonomy.py` | `/taxonomy/...` | Consulta el árbol Dpto → Cat → Sub (solo lectura) |
| `taxonomy_admin.py` | `/admin/taxonomy/...` | CRUD de la taxonomía interna (crear/editar departamentos, categorías, subcategorías) |
| `bsale_admin.py` | `/admin/bsale/...` | Escribe directamente a BSale vía su API (crea/actualiza product_types) |
| `products.py` | `/products/...` | Listado y búsqueda de productos con su taxonomía |
| `stock.py` | `/stock/...` | Stock actual por sucursal y valorización del inventario |
| `documents.py` | `/documents/...` | Documentos de venta (boletas, facturas) |
| `analytics.py` | `/analytics/...` | KPIs principales: ventas 30d, ticket promedio, etc. |
| `analytics_advanced.py` | `/analytics/...` | Análisis de ticket detallado, rotación de inventario |
| `sync.py` | `/sync/...` | Dispara sincronizaciones manuales desde la API (sin abrir terminal) |
| `audits.py` | `/audits/...` | Detecta productos huérfanos, inconsistencias de datos |


Para ver todos los endpoints con sus parámetros:  
👉 Ir a `http://localhost:8000/docs` (Swagger UI)

---

## Flujo de sincronización paso a paso

Cuando se ejecuta `python run_daily_sync.py`, ocurre esto en orden:

```
FASE 1 — Masters (entidades que cambian poco):
  1. sync_taxonomy()           → Siembra Departamentos/Categorías/Subcategorías desde Estructura_inicial.json
  2. sync_offices()            → Sucursales de BSale
  3. sync_product_types()      → Categorías de BSale + las mapea a la taxonomía interna
  4. sync_document_types()     → Tipos de documento (boleta, factura, nota de crédito...)
  5. sync_variants()           → Productos y variantes (SKUs)
  6. sync_product_type_attributes() → Atributos por categoría
  7. sync_variant_attribute_values() → Valores de atributos por variante

FASE 2 — Stock y Costos (estado actual, siempre full):
  8. sync_stock_levels()       → Stock actual en cada sucursal
  9. sync_variant_costs()      → Costo promedio por variante
  10. snapshot_stock_history() → Guarda foto del stock del día (para historial)

FASE 3 — Recepciones recientes:
  11. sync_receptions()        → Recepciones al almacén (últimos N días)

FASE 4 — Documentos recientes:
  12. sync_documents()         → Ventas / boletas / facturas (últimos N días, modo TURBO)
```

> **TURBO:** La sincronización de documentos usa múltiples hilos paralelos para acelerar la descarga. Esto respeta el rate limit de BSale (9 req/s).

---

## La taxonomía de categorías — ¿cómo funciona?

BSale tiene sus propias categorías (`product_types`), pero Kawii tiene una jerarquía más clara:

```
BSale:         "Dulces / Chocolates"   (un solo nivel flat)
                      ↓  se mapea a:
Kawii:         Alimentos → Dulces → Chocolates  (3 niveles: Dpto → Cat → Sub)
```

**El archivo que define la taxonomía de Kawii:**
```
Nueva_estructura/Estructura_inicial.json
```

Cada vez que corre el sync, `sync_taxonomy()` lee ese JSON y siembra las tablas `departments`, `categories`, `subcategories` en Postgres.

Luego `sync_product_types()` intenta hacer match del nombre de BSale con una subcategoría. Si no puede matchear, el product_type queda como `is_mapped = FALSE` y aparece en las auditorías.

**¿Cuándo editar el JSON?**
- Si Kawii decide agregar una nueva categoría de producto.
- Si se renombra un departamento o categoría.
- Después de editar el JSON, hay que correr `python run_daily_sync.py --days 1` para que se propague.

---

## Tabla de sucursales

| ID (BSale) | Nombre | Tipo | Incluida en ventas |
|------------|--------|------|--------------------|
| 1 | Magdalena | Tienda | ✅ Sí |
| 3 | Asamblea | Tienda | ✅ Sí |
| 4 | Almacén Central | Almacén | ❌ No (solo recepciones) |

---

## Scripts de mantenimiento — cuándo usar cada uno

### `scripts/` — Uso puntual (mantenimiento)

| Script | Cuándo ejecutarlo |
|--------|-------------------|
| `audit_final.py` | Cuando sospechas que las ventas en Postgres no cuadran con BSale |
| `audit_ventas_7d.py` | Verificación rápida de los últimos 7 días |
| `fix_db.py` | Si hay un problema puntual en la DB (leer el código antes de ejecutar) |
| `map_orphans.py` | Cuando hay product_types sin mapear en la taxonomía |
| `clean_bsale_categories.py` | Elimina categorías BSale vacías/inactivas (usar con `--execute` para confirmar) |
| `update_all.py` | Sincronización masiva + aplicar reglas de taxonomía (alternativa pesada a run_daily_sync) |
| `verify_bsale_sales.py` | Comparar ventas de BSale directamente contra Postgres |
| `simulacro_limpieza_product_types.py` | Dry-run para ver qué se limpiaría SIN ejecutar nada |

> ⚠️ Los scripts de `scripts/` son de mantenimiento puntual. Siempre leer el código antes de ejecutar los que modifican datos.

### `analytics_scripts/` — Análisis y reportes

| Script | Qué genera |
|--------|------------|
| `generate_report.py` | Informe PDF completo (informe_kawii.pdf) |
| `run_all.py` | Ejecuta todos los análisis en secuencia |
| `inventory_analysis.py` | Análisis de rotación y valorización de inventario |
| `ticket_analysis.py` | Análisis de ticket promedio |
| `ticket_diagnostico.py` | Diagnóstico detallado de tickets por sucursal |
| `cleanup_empty_categories.py` | Limpia categorías vacías de la DB local |

---

## Tablas de la base de datos

### Tablas principales

| Tabla | Qué guarda |
|-------|-----------|
| `departments` | Departamentos de la taxonomía Kawii (ej: Alimentos) |
| `categories` | Categorías (ej: Dulces) |
| `subcategories` | Subcategorías (ej: Chocolates) |
| `product_types` | Categorías de BSale, con FK a `subcategories` |
| `products` | Productos de BSale (familia) |
| `variants` | Variantes/SKUs de cada producto |
| `variant_costs` | Costos por variante |
| `offices` | Sucursales |
| `stock_levels` | Stock actual por variante y sucursal |
| `stock_history` | Foto diaria del stock (para tendencias) |
| `documents` | Documentos de venta (boletas, facturas) |
| `document_details` | Líneas de cada documento |
| `document_types` | Tipos de documento de BSale |
| `sync_logs` | Log de cada sincronización (éxito/error, tiempos) |
| `data_quality_issues` | Registros con problemas de calidad detectados |
| `product_type_attributes` | Atributos definidos por categoría en BSale |
| `variant_attribute_values` | Valores de atributos por variante |

### Vista importante

| Vista | Qué une |
|-------|---------|
| `v_products_full` | Une `products` + `product_types` + toda la taxonomía (Dpto/Cat/Sub). Es la base de los reportes de catálogo. Respeta overrides individuales por producto. |

---

## Problemas frecuentes y cómo resolverlos

### "Las ventas no cuadran con BSale"
1. Ejecutar `python scripts/audit_final.py`
2. Recordar: los reportes solo incluyen sucursales 1 y 3
3. Recordar: se excluyen notas de crédito (`is_credit_note = TRUE`) y notas de venta internas (`is_sales_note = TRUE`)

### "Hay productos sin categoría en el frontend"
1. Llamar a `GET http://localhost:8000/audits/unmapped-products`
2. Ejecutar `python scripts/map_orphans.py` para mapearlos automáticamente
3. Si el problema persiste, revisar `Estructura_inicial.json` y agregar la subcategoría faltante

### "La API no responde"
1. Verificar que uvicorn esté corriendo: `http://localhost:8000/health`
2. Verificar que Postgres esté activo
3. Revisar el log: `daily_sync.log` en la raíz del proyecto

### "El sync falló a mitad"
1. Revisar `daily_sync.log` para ver el error
2. Los UPSERTs son idempotentes: puedes volver a ejecutar sin riesgo de duplicar datos

---

## Automatización — Task Scheduler de Windows

Para que la sincronización corra automáticamente todos los días:

1. Abrir **Administrador de tareas programadas** (Task Scheduler)
2. Crear tarea básica
3. Configurar trigger: Diariamente a las **3:00 AM** (cuando las tiendas están cerradas)
4. Acción: Ejecutar programa
   - Programa: `python`
   - Argumentos: `run_daily_sync.py`
   - Directorio inicial: `C:\Users\juana\Documents\Kawii_analisis_datos\backend_kawii\produccion`
5. El resultado queda en `produccion/daily_sync.log`

---

## Dependencias del sistema

```txt
# ETL (harvester)
requests>=2.31.0           # Llamadas HTTP a BSale
psycopg2-binary>=2.9.9     # Driver de PostgreSQL
python-dotenv>=1.0.0       # Leer el archivo .env

# API (FastAPI)
fastapi>=0.115.0           # Framework REST
uvicorn[standard]>=0.32.0  # Servidor ASGI
pydantic>=2.9.0            # Validación de datos
pydantic-settings>=2.5.0   # Configuración desde .env
python-multipart>=0.0.12   # Para uploads de archivos
```

---

## Glosario

| Término | Significado |
|---------|-------------|
| BSale | ERP / POS usado por las tiendas (en la nube) |
| Harvester | El módulo Python que descarga datos de BSale |
| ETL | Extract, Transform, Load — el proceso de sincronización |
| UPSERT | INSERT que si ya existe el registro, hace UPDATE (no duplica) |
| Rate limiting | Limitador de velocidad para no superar 9 req/s de BSale |
| Taxonomía | Jerarquía de categorías de Kawii (Dpto → Cat → Sub) |
| product_type | Categoría en BSale (equivalente a subcategoría en Kawii) |
| Variante | Una presentación específica de un producto (tamaño, sabor, etc.) |
| Huérfano | Producto o categoría sin mapeo en la taxonomía Kawii |
| Override | Asignación manual de categoría a un producto específico (overrride individual) |
| TURBO | Modo paralelo del sync de documentos (varios hilos simultáneos) |
| Pool | Conjunto de conexiones reutilizables a Postgres (más eficiente que abrir/cerrar) |
rios hilos simultáneos) |
| Pool | Conjunto de conexiones reutilizables a Postgres (más eficiente que abrir/cerrar) |
