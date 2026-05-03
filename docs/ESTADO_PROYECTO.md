# KAWII - Estado del Proyecto (Actualizado Abril 2026)

> Última actualización: **2026-04-26**
> BD: `database_kawii_pluss` en `localhost:5432` (postgres/postgres)
> Estado de Limpieza: **260 categorías obsoletas eliminadas permanentemente de BSale y local**

---

## 1. Resumen Ejecutivo del Estado Actual

El sistema ha evolucionado de simples scripts de extracción a un **Backend FastAPI completo** de producción. La base de datos PostgreSQL se ha robustecido para soportar la taxonomía interna de Kawii (3 niveles) y ahora permite **overrides individuales** por producto (asignar un producto específico a una subcategoría distinta a la de su familia original).

Se han construido y puesto a prueba los **endpoints de analítica y auditoría**, los cuales consultan la vista maestra `v_products_full` para ofrecer reportes consistentes en tiempo real.

---

## 2. Hitos Alcanzados y Completados ✅

- [x] **Limpieza Profunda de BSale (Nuevo):** Se eliminaron con éxito 260 `product_types` de BSale que estaban inactivos, vacíos y sin mapear (basura acumulada).
- [x] **Overrides por Producto:** Se agregó la columna `subcategory_id` directamente a la tabla `products` en PostgreSQL y en `schema.sql`. Esto permite reclasificar productos "rebeldes" uno por uno sin afectar a toda su categoría de BSale.
- [x] **Vista Unificada de Catálogo:** Se creó e implementó exitosamente `v_products_full`. Esta vista resuelve en una sola consulta toda la jerarquía de un producto, decidiendo automáticamente si usar el `subcategory_id` del producto (override) o heredar el del `product_type`.
- [x] **API REST FastAPI:**
  - `app/routers/analytics.py`: KPIs, ventas por departamento.
  - `app/routers/audits.py`: Detección de huérfanos, inconsistencias.
  - `app/routers/products.py`: Búsqueda de catálogo con taxonomía.
  - `app/routers/sync.py`: Disparador manual de procesos del harvester.
- [x] **Manejo de Huérfanos Automatizado:** `map_orphans.py` ya es funcional y sirve para asignar subcategorías masivamente.
- [x] **Orquestador Central:** `update_all.py` consolida las sincronizaciones y correcciones en un solo comando robusto.

---

## 3. Estado de la Taxonomía y Catálogo

Tras la ejecución de la limpieza (`clean_bsale_categories.py`), el catálogo de categorías que viene de BSale está sumamente limpio. 
Casi el **100% de los productos activos** están ya mapeados a la taxonomía (Departamentos > Categorías > Subcategorías). 

Las diferencias o "huérfanos" (categorías BSale con productos que el cliente no asignó en su JSON) ahora se pueden resolver directamente en la base de datos de 2 formas:
1. **Asignando la categoría completa** (`product_types.subcategory_id`)
2. **Haciendo overrides producto por producto** (`products.subcategory_id` a través de `map_orphans.py`)

---

## 4. Comandos Incorporados Recientemente

### `python clean_bsale_categories.py`
Examina la base de datos local y BSale en busca de `product_types` que no estén mapeados y no tengan productos. 
- `--execute`: Los elimina vía API de BSale y hace un DELETE en PostgreSQL. Ya se usó exitosamente para limpiar 260 registros.

### `python map_orphans.py`
Mapeo rápido de productos que perdieron su jerarquía. Útil para mantener la salud de los reportes.

### `python update_all.py`
El macro-script. Se recomienda correrlo a diario (puede reemplazar o acompañar a `run_daily_sync.py`). Sincroniza desde cero y asegura que las vistas estén compiladas.

### `python fix_db.py`
Script de emergencia (ya ejecutado y plasmado en `schema.sql`) para forzar la creación de `v_products_full` y agregar las columnas de override.

---

## 5. Próximos Pasos Pendientes 🚀

1. **Configuración de Tareas Programadas (Cron/Task Scheduler):**
   Actualmente la sincronización se dispara manualmente o desde scripts locales. Falta dejar `update_all.py` programado a nivel de sistema operativo para que se ejecute de madrugada (ej. 06:00 AM).
2. **Conexión con el Frontend:**
   La API (en `localhost:8000`) ya responde a los KPIs (`/analytics/kpis`, `/analytics/sales-by-department`), pero falta verificar que el Dashboard (Frontend) la esté consumiendo adecuadamente.
3. **Mantenimiento Mensual:**
   Revisar esporádicamente los endpoints de `/audits` en la API para asegurar que los nuevos productos creados por los vendedores en BSale sean correctamente absorbidos por la jerarquía.
