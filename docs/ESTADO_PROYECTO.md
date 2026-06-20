         # KAWII - Estado del Proyecto

> Última actualización: **2026-06-08**
> BD: `database_kawii_pluss` en `localhost:5432` (postgres/postgres)
>
> **Para detalles ver:** `SISTEMA.md` (visión general), `RESUMEN_EJECUTIVO_CLASIFICACION.md` (matrices), `CASOS_ANOMALOS_Y_PATRONES.md` (P1-P17), `ARQUITECTURA.md` (técnico).

---

## 1. Resumen Ejecutivo del Estado Actual (junio 2026)

El sistema está en producción operativa con:
- **Backend FastAPI** completo (`localhost:8000`) con ~25 endpoints REST agrupados en analytics, productos, taxonomía, audits, sync, kawii_matrix (módulo 04b), matrix_simulator.
- **Frontend Next.js** (`localhost:3000`) con dashboard, productos, reporte-diario, tablero-semanal, simulador-cascada, configuración.
- **1 matriz de clasificación viva** (04b — la jerárquica con totales en S/) con cascada de 36 cajas (+1 catch-all; última caja: ⚡ ROTACIÓN ACTIVA AL BORDE, P23 2026-06-12). Las matrices 04/05/06/07/08 se eliminaron en el cleanup en cascada (junio 2026); su contenido era duplicado o ya no se consumía.
- **0 huérfanos** (caja catch-all "CASO ATÍPICO" = 0).
- **17 patrones de casos raros documentados** (P1-P17) con SQL para detectarlos.
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
| 2026-06-10 | **Auditoría P20** — réplica independiente de la cascada en Python (`_beta/audit_clasificaciones.py`): 3,491/3,491 filas coinciden, 0 errores de matemática, 0 violaciones semánticas. Excel del usuario verificado fiel (export con filtro MAGDALENA). Detectado fix "punto ciego" base 180d (+520 OPORTUNIDAD PERDIDA en MAG, verificadas contra documentos crudos: caso MAQ09 vendía 300/mes y llevaba 5 meses agotado invisible). |
| 2026-06-11 | **P22** — (a) tope de sanidad `qty≤50,000` en recepciones+consumos (códigos de barras tipeados como cantidad: G7782DF +6.97 billones, L9172 +100 mil millones; **L9172 decía "PÉRDIDA DE STOCK—revisar robos" siendo BESTSELLER ACTIVO**); (b) columna "Cobertura" ahora muestra la reciente (la que clasifica, P17) y stock=0 siempre 'Agotado' — incoherencias display: 258→0 y 214→0; (c) columna nueva **"Stock Almacén"** en matriz + Excel (38 SKUs / 8,717 unds en Almacén Central eran invisibles — distingue "comprar" de "trasladar"). Whitelist NO tocada (Pilar/Liz hacen ajustes, no mercadería — confirmado por el usuario). Snapshot pre/post: 10,445/10,448 idénticas (las 3 = L9172 corregido). Auditoría: 0 errores totales. Pendiente manual BSale: recep Nº1644/Nº10254 + consumos gemelos. |
| 2026-06-11 | **Limpieza CTE muerto `ventas_35d_post_recep`** — vestigio de la "cascada 35d" eliminada el 2026-06-06; se seguía calculando (scan completo de documents) sin que ninguna regla lo consumiera. Removido de 04/04b/05 + regenerado 08. Verificado con snapshot pre/post: **10,448/10,448 clasificaciones idénticas, 0 diferencias**. Tiempo de las 4 matrices: 26.6s → 18.7s (-30%). |
| 2026-06-10 | **P21** — (a) guard `dsv≥8` en LENTO CRÓNICO (caso Drive Ultra: consumible de reposición continua decía NO REPONER con 1 und y venta de ayer); (b) "⏸️ BESTSELLER EN PAUSA — EVALUAR" renombrado a "⏸️ BESTSELLER AGOTADO 1-2 MESES — REPONER" (caso GALLETAS: "la demanda se enfrió" era falso — vendía 37/mes y nadie repuso). classify_action y frontend actualizados. Pendiente cosmético: columna "Cobertura" muestra lifetime pero clasifica la reciente (258 filas en banda distinta) + "s/d" con stock=0 (220 filas). |
