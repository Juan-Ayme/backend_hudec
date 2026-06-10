         # KAWII - Estado del Proyecto

> Última actualización: **2026-06-08**
> BD: `database_kawii_pluss` en `localhost:5432` (postgres/postgres)
>
> **Para detalles ver:** `SISTEMA.md` (visión general), `RESUMEN_EJECUTIVO_CLASIFICACION.md` (matrices), `CASOS_ANOMALOS_Y_PATRONES.md` (P1-P17), `ARQUITECTURA.md` (técnico).

---

## 1. Resumen Ejecutivo del Estado Actual (junio 2026)

El sistema está en producción operativa con:
- **Backend FastAPI** completo (`localhost:8000`) con ~30 endpoints REST agrupados en analytics, productos, stock, documentos, taxonomía, audits, sync, kawii_matrix.
- **Frontend Next.js** (`localhost:3000`) con dashboard, ventas-jerarquicas, matrices, reporte-diario, configuración.
- **6 matrices de clasificación** (04, 04b, 05, 06, 07, 08-transferencias) con cascada de 33 cajas (post-rename 2026-06-06).
- **0 huérfanos** (caja catch-all "CASO ATÍPICO" = 0 en las 3 matrices principales).
- **17 patrones de casos raros documentados** (P1-P17) con SQL para detectarlos.
- **Sistema de transferencias inter-sucursal** (módulo 08) con 32+ sugerencias diarias.
- **Widget de anatomía del cambio** en `/reportes/diario` que descompone Δventas en tráfico × canasta × precio.

### Estado de calidad de datos
- ✅ Catálogo limpio (260 categorías obsoletas eliminadas en abril)
- ✅ Taxonomía 3 niveles funcionando con overrides individuales por producto
- ✅ Vista `v_products_full` resuelve toda la jerarquía en una consulta
- ⚠️ **Costos**: 80% del catálogo con `cost_source='NONE'` (P14) — usuario cargando manualmente (Pareto: top 100 SKUs = 47.5% del impacto)

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

### `python tools/maintenance/clean_bsale_categories.py`
Examina la base de datos local y BSale en busca de `product_types` que no estén mapeados y no tengan productos. 
- `--execute`: Los elimina vía API de BSale y hace un DELETE en PostgreSQL. Ya se usó exitosamente para limpiar 260 registros.

### `python tools/taxonomy/map_orphans.py`
Mapeo rápido de productos que perdieron su jerarquía. Útil para mantener la salud de los reportes.

### `python tools/maintenance/update_all.py`
El macro-script. Se recomienda correrlo a diario (puede reemplazar o acompañar a `run_daily_sync.py`). Sincroniza desde cero y asegura que las vistas estén compiladas.

### `python tools/maintenance/fix_db.py`
Script de emergencia (ya ejecutado y plasmado en `schema.sql`) para forzar la creación de `v_products_full` y agregar las columnas de override.

---

## 5. Próximos Pasos Pendientes 🚀

### 🔴 Alta prioridad
1. **P14 · Cargar costos manualmente** desde `costos_pendientes_priorizados.xlsx` (955 SKUs). Top 100 = 47.5% del impacto. Sin esto, el margen calculado y el stock_valorizado están sesgados.
2. **Reiniciar uvicorn periódicamente** después de cambios al SQL (el código tiene `--reload`, pero los fixes del 2026-06-06 requirieron reinicio manual).
3. **Diagnóstico Alimentos Importados** (depto con 28% urgentes — probablemente OC pendiente con proveedor asiático).

### 🟡 Media
4. **P8** · Caja específica para SKUs exclusivos de una sucursal.
5. **P9** · Guard contra ventas mayoristas (1 ticket > 50% de las 90d) que inflan `proy_mes`.
6. **Reporte Semanal** (ver `REPORTES_GERENCIA.md`).
7. **Tareas Programadas** (Cron/Task Scheduler) para `update_all.py` de madrugada.

### 🟢 Baja
8. Widgets B (venta perdida por quiebre) y C (heat-map sucursal × depto) en `/reportes/diario`.
9. D4-D12 — análisis exploratorios (cross-sell, devoluciones, día-de-semana, etc.).
10. Refactor de matrices a CTEs compartidos.

---

## 6. Historial de cambios mayores (cronología 2026)

| Fecha | Cambio |
|---|---|
| Abril 2026 | Limpieza de 260 categorías obsoletas en BSale. Overrides por producto. Vista `v_products_full`. |
| Mayo 2026 | Endpoint `/matrix/{id}/excel` con layout maquetado. Refactor cascada 44 → 31 reglas. |
| 2026-06-01 | Sistema rotulado "HUDEC" (white-label). Widget Anatomía + endpoint `/analytics/ticket-anatomy`. |
| 2026-06-05 | Whitelist almaceneros [2,4,5,14,16] reemplaza `qty>=5`. Caja 🆕 RECIÉN REABASTECIDO. |
| 2026-06-06 | **Bloque mayor**: P15 (caja LOTE FRENADO), P19 (rename de las 31 cajas), P16 (guard cob≤45 en VENDIENDO MÁS), P17 (cobertura con vel reciente 30d), módulo 08 (transferencias). |
| 2026-06-08 | P7 (Tendencia "💤 Agotado" cuando stock=0). Excel `top_reponer_ya.xlsx`. Diagnóstico Alimentos Importados. Documentación actualizada (este archivo + SISTEMA.md + RESUMEN_EJECUTIVO). |
| 2026-06-08 (PM) | **P18** — Caja nueva 🪦 LENTO CRÓNICO (caso GFQQ-240437 REL DE PARED, 26 unds en 10 meses). Renombrada "Días desde Últ. Recep" → "Llegó hace (días)". Agregada columna "Sell-through Lote %". 23 SKUs detectados como lentos crónicos. 0 huérfanos en las 3 matrices. |
