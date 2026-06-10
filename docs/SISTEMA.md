# SISTEMA KAWII / HUDEC — Visión General

> Documento maestro: **qué es el sistema y todo lo que hace.** Para detalles
> específicos ver: `ARQUITECTURA.md` (diagrama técnico), `GUIA_MANTENIMIENTO.md`
> (operación), `REPORTES_GERENCIA.md` (reportería), `BSALE_API_AUDIT.md` (API BSale),
> `RESUMEN_EJECUTIVO_CLASIFICACION.md` (matrices al detalle),
> `CASOS_ANOMALOS_Y_PATRONES.md` (P1-P17, casos raros), `schema.sql` (base de datos).
>
> **Última actualización:** 2026-06-08.

---

## 1. ¿Qué es?

Sistema de **Business Intelligence e inventario** para **KAWII / Grupo Hudec** (retail, 2 tiendas en Lima). Toma los datos del ERP **BSale** (nube), los guarda en una base local, los clasifica con reglas de negocio propias, y los expone en un dashboard para tomar decisiones de **compra, reposición, liquidación y transferencia** de productos.

**Marca white-label:** "hudec" (la clasificación se rotula "Clasificación HUDEC").

**Dos partes:**
- **`backend_hudec/`** — Python (FastAPI + PostgreSQL). ETL desde BSale + API REST en `localhost:8000`.
- **`frontend_hudec/`** — Next.js (App Router, TypeScript, Tailwind, TanStack Query, Recharts). Dashboard dark en `localhost:3000`.

**Sucursales:** Magdalena (office 1) y Asamblea (office 3) son tiendas que venden. Almacén Central (office 4) solo recibe mercadería. Los reportes de venta consideran solo 1 y 3.

---

## 2. Cómo fluyen los datos

```
BSale API (nube)
   │  (pull por lote, no tiempo real)
   ▼
harvester/  ── sync_masters (productos, variantes, categorías, stock, costos)
            └─ sync_transactions (documentos de venta, recepciones, consumos)
   │
   ▼
PostgreSQL (local)  ── taxonomía propia: Departamento → Categoría → Subcategoría
   │
   ▼
app/ (FastAPI)  ── API REST: analytics, productos, stock, documentos,
   │               matrices de clasificación, taxonomía, sync, auditorías
   ▼
frontend_hudec/ (Next.js)  ── dashboard + reportes
```

**Sincronización:** NO es en tiempo real. El harvester **jala** de BSale por lote (`run_daily_sync.py`, programado ~3 AM por Task Scheduler, o manual; tiene modo incremental con `since_unix`). El día en curso es parcial hasta el siguiente sync.

---

## 3. El backend

### 3.1 Harvester (ETL) — `harvester/`
- `bsale_client.py` — cliente HTTP con rate limiting y reintentos.
- `sync_masters.py` — productos, variantes, categorías, stock, sucursales, **costos** (`variant_costs`).
- `sync_transactions.py` — documentos de venta + detalles, recepciones + detalles, consumos (mermas).
- `config.py` — lee `.env`: credenciales, IDs de sucursales/tipos de documento, exclusiones, departamentos estacionales.

### 3.2 API REST — `app/routers/`
- `analytics.py` — KPIs, ventas por día/departamento/categoría/subcategoría/sucursal, top productos. Todos aceptan `office_id` opcional (filtro por sucursal).
- `products.py` — listado/detalle de productos y variantes.
- `stock.py` — niveles por sucursal, valorización al costo, histórico, top.
- `documents.py` — documentos de venta (boletas/facturas/notas), con filtros de fecha y sucursal.
- `taxonomy.py` / `taxonomy_admin.py` — árbol Depto/Cat/Subcat y su CRUD.
- `bsale_admin.py` — product_types (escribe a BSale).
- `sync.py` — dispara sincronizaciones manuales.
- `audits.py` — calidad de datos.
- `kawii_matrix/` — las matrices de clasificación (el corazón analítico, ver §4).

### 3.3 Reglas de negocio transversales
- **Ventas = tipos 1,10,50,51,52,53; devoluciones = 9,40,43; traslado interno = 53.**
- **Fechas en UTC.** BSale codifica las fechas a medianoche UTC; la fecha real del documento se extrae en UTC (NO en Lima, que correría todo un día atrás). Aplica en analytics, documents y las matrices.
- Las ventas excluyen notas de crédito.

---

## 4. Clasificación de SKUs — las matrices

El núcleo del sistema. Para cada SKU×sucursal calcula métricas (ventas 90d, stock, velocidad, rotación, sell-through, tendencia) y le asigna una **clasificación accionable** mediante una cascada de ~25 reglas `CASE WHEN`.

### 4.1 Las matrices (`app/kawii_matrix/sql/`)
| Módulo | Qué es |
|---|---|
| `04` | Foto operativa 90d (snapshot puro) |
| `04b` | 90d jerárquica + totales en S/ por nivel (la que usa el dashboard / Excel) |
| `05` | Operativa + contexto lifetime (sell-through histórico, mejor mes, índice de contribución) |
| `06` | Histórico (autopsia lifetime) |
| `07` | Consolidado jerárquico DEPT→CAT→SUBCAT→SKU (ABC Pareto) |
| `08` ★ | **Transferencias inter-sucursal** — pares (donante, receptor, SKU). Auto-generado desde 04b por `_beta/generar_08_transferencias.py` |

`service.py` carga el SQL (cacheado), pasa parámetros desde `.env`, y aplica filtros post-query. **Las 04/04b/05 comparten la misma cascada de clasificación** (convergidas para evitar divergencias). El `08` reutiliza las CTEs base de 04b y agrega su propio SELECT para self-join entre sucursales.

### 4.2 Métricas clave por SKU
- **Velocidad lifetime (`proy_mes`)** = ventas del lote actual ÷ días efectivos del ciclo (NO lifetime calendario — no diluye con días sin stock).
- **Velocidad reciente 30d (`proy_30d_reciente`)** = unds vendidas 30d ÷ días con stock en esos 30d.
- **Cobertura (`dias_cobertura_reciente`)** ★ — usa la velocidad reciente (P17, 2026-06-06). Es lo que clasifica al SKU en la cascada. Fallback a vel lifetime si no hay datos recientes.
- **% Rotación Stock**, **% Demanda vs Reposición**, **% Frecuencia**, **XYZ** (constante/variable/ráfaga), **Sell-through lifetime**.
- **Tendencia** = ventas últimos 45d vs 45d previos (📈 creciendo / 📉 decayendo / 💤 pausado / 💤 Agotado si stock=0). El "Agotado" es del P7 (2026-06-08): cuando stock=0, la fórmula mecánica decía "Decayendo" porque recent=0 — engañoso.

### 4.3 Clasificaciones — las 33 cajas (post-rename 2026-06-06)

Todas las cajas tienen formato **`EMOJI NOMBRE — VERBO ACCIÓN: descripción`**. Cuando el frontend muestra solo el chip, corta en el `:`.

**Sección A · Casos especiales (5):**
- 🌱 PRODUCTO NUEVO — ESPERAR
- ✅ TEMPORADA CERRADA OK — RECOMPRAR PRÓXIMA CAMPAÑA
- 📦 SALDO DE TEMPORADA — GUARDAR PARA PRÓXIMA
- ⛔ PÉRDIDA DE STOCK — REVISAR CONTROL FÍSICO
- ⚠️ VENDIÓ Y SE PERDIÓ — INVESTIGAR

**Sección B · Stock=0 + vendió bien (5):**
- 🔥 BESTSELLER ACTIVO — REPONER YA (antes: EXITOSO ACTIVO)
- ⏸️ BESTSELLER EN PAUSA — EVALUAR (antes: EXITOSO PASADO)
- 💎 OPORTUNIDAD PERDIDA — REPONER YA (antes: EXITOSO OLVIDADO)
- 🐢 LENTO PERO CONSTANTE — REPONER POCO (antes: ROTACIÓN LENTA SANA)
- 💤 DEMANDA EXTINTA — NO REPONER

**Sección C · Stock=0 + vendió poco (7):**
- 🚨 QUIEBRE DE BESTSELLER — COMPRAR YA
- ✨ AGOTADO CON DEMANDA — REPONER (antes: AGOTADO POTENCIAL ACTIVO)
- 📉 EX-BESTSELLER ENFRIADO — EVALUAR
- 🌿 PRODUCTO EMERGENTE — VIGILAR
- 🪦 PRODUCTO MUERTO — DESCATALOGAR
- 🪦 BAJO VOLUMEN AGOTADO — DESCATALOGAR
- 👻 AGOTADO NO PRIORITARIO

**Sección D · Stock>0 + sin ventas (2):**
- 🔄 STOCK RECIÉN LLEGADO — ESPERAR
- 💀 STOCK PARADO 90 DÍAS — LIQUIDAR (antes: MUERTO 90D)

**Sección E · Stock>0 + con ventas (14):**
- 👀 STOCK BAJO QUIETO — VERIFICAR EN TIENDA (antes: ALERTA VISUAL)
- 🔄 LOTE NUEVO VENDIENDO BIEN
- 🆕 RECIÉN REABASTECIDO — ESPERAR 1 SEMANA
- 📉 RITMO PERDIDO — EVALUAR ANTES DE REPONER
- 💀 **LOTE FRENADO — LIQUIDAR, NO COMPRAR MÁS** (P15, antes SALDO QUEMADO)
- 🔥📉 ROTACIÓN BAJANDO — REPONER MENOS
- 🔥 ALTA ROTACIÓN — PRIORIDAD DE COMPRA
- 💫 ROTACIÓN ACTIVA — MANTENER FLUJO
- 🟢 INVENTARIO SANO — RITMO NORMAL
- 🧊📉 EXCESO + DEMANDA CAYENDO — PROMOCIONAR YA
- 🧊 STOCK EXCESIVO — PROMOCIONAR
- 🪦 **LENTO CRÓNICO — NO REPONER** ★ (P18, 2026-06-08 — SKUs con edad≥180d, vel lifetime <5/mes, lifetime <60 unds; caso GFQQ-240437 REL DE PARED)
- ⚠️ POCO STOCK CON DEMANDA — REPONER
- 📈 VENDIENDO MÁS QUE ANTES — VIGILAR (con guard `cob ≤45d` post-P16)
- 🐢 BAJA ROTACIÓN — PEDIR MENOS

**Columnas informativas del Excel (no clasifican, pero ayudan a evaluar):**
- `Llegó hace (días)` — días desde la última recepción del lote actual.
- `Sell-through Lote %` — % del lote actual ya vendido (`unds_lote_total / (unds_lote_total + stock) × 100`).
- `Vida lote (días)` ★ (P19, 2026-06-08) — proyección total: `dias_desde_ultima_recep + dias_cobertura_reciente`. Muestra cuánto tardará el lote completo en agotarse. Útil para decidir tamaños de orden de compra (si >60d, considerar lotes más chicos).
- Útiles juntas: 87% sell-through con "llegó hace 300d" indica producto lento crónico, mientras 87% con "llegó hace 30d" indica bestseller rotando rápido. **78% del catálogo KAWII tiene Vida lote >90d** (modelo nicho — esperable, no anomalía).

**Sección F · Catch-all (1):**
- ⚖️ CASO ATÍPICO — REVISAR MANUAL (debería ser 0 siempre)

Ver `CASOS_ANOMALOS_Y_PATRONES.md` para la tabla de equivalencias nombre viejo ↔ nuevo (compat de exports históricos).

### 4.4 Endpoints derivados de las matrices
- `/matrix/{id}` — la tabla completa (con filtros sucursal/depto/cat/subcat/clasificación).
- `/matrix/{id}/action-groups` — **agrupa los SKUs por acción de negocio**: `urgente_comprar` (solo QUIEBRE real), `reponer` (BESTSELLER + OPORTUNIDAD PERDIDA), `saludable`, `exceso`, `liquidar`, `descatalogar`, `evaluar`. (Base del Reporte Diario.)
- `/matrix/{id}/transfers` — sugerencias de transferencia simple (solo 04/04b/05).
- `/matrix/08` ★ — **módulo dedicado** de transferencias inter-sucursal con pares detallados (razón donante, razón receptor, unds sugeridas, stock post-transfer, impacto S/, prioridad 1-5).
- `/matrix/{id}/distribution` — distribución por clasificación.
- `/matrix/{id}/excel` — workbook .xlsx formateado (portada, índice, resumen, hoja por departamento).
- `/matrix/_/summary` — resumen ejecutivo.
- `/analytics/ticket-anatomy` ★ — descomposición log de Δventas en (tickets × unds/ticket × $/und). Útil para responder "¿la caída fue por tráfico, canasta o precio?". Render en `AnatomyCard` (`/reportes/diario`).

### 4.5 Productos estacionales
Departamentos de campaña (`SEASONAL_DEPARTMENTS=21,12` en `.env`: "Temporada y Celebraciones" + "Librería y Oficina"/escolar) NO se excluyen: se clasifican distinto. Fuera de temporada (sin venta >30d): si vendió y se agotó → ✅ TEMPORADA CERRADA (recomprar próxima campaña); si quedó stock → 📦 SOBRANTE. En plena campaña (venta reciente) caen a reglas normales.

### 4.6 Configuración (exclusiones, estacional, performance)
- **Restricciones por NOMBRE (híbrido `.env` + DB):** las exclusiones (`EXCLUDED_DEPARTMENTS`/`EXCLUDED_CATEGORIES`) y lo estacional (`SEASONAL_DEPARTMENTS`) se configuran en el `.env` por **NOMBRE** separados por `|`. Las exclusiones **siembran** la DB (`app_config`) en el primer arranque y luego se ajustan en vivo desde la pantalla **Configuración** (`GET/PUT /config/exclusions`); lo estacional se lee del `.env`. El servicio de matrices resuelve nombre→ID actual en cada consulta.
- **⚠️ Los IDs de taxonomía NO son estables:** un re-seed (`sync_taxonomy()`) reasigna los IDs de `departments`/`categories`. Por eso las restricciones se referencian por **nombre** (los IDs de BSale —sucursales, tipos de documento— sí son estables y van por ID).
- **Multi-empresa:** un despliegue por empresa (su `.env` + su DB). Ver `.env.example` y `docs/REPLICAR_EMPRESA.md`.
- **Performance:** las matrices corren con `SET LOCAL enable_nestloop = off` (las ~15 CTEs correlacionadas hacían que el planner eligiera nested loops → ~205s; forzar hash/merge joins → ~4-6s).

---

## 5. El frontend — páginas

### Sección Análisis
- **Dashboard** (`/`) — KPIs (ventas, ticket promedio, stock valorizado, productos), ventas por día, por departamento, por sucursal, top productos.
- **Productos** (`/productos`), **Stock** (`/stock`), **Ventas** (`/ventas`, documentos).
- **Ventas & Catálogo** (`/ventas-jerarquicas`) — maestro-detalle: árbol de ventas jerárquico (Depto→Cat→Subcat con % y montos) a la izquierda; al seleccionar un nivel, grid de productos clasificados a la derecha, con chips de comportamiento, búsqueda y export Excel. Unificó las antiguas "Ventas Jerárquicas" + "Catálogo".
- **Matrices KAWII** (`/matrices`) — la tabla de clasificación con filtros, distribución, grupos de acción y transferencias.

### Sección Reportes
- **Reporte Diario** (`/reportes/diario`) — 3 secciones:
  1. **Pulso del día** (ayer): ventas / tickets / ticket promedio con deltas vs día previo y semana pasada.
  2. **🔬 Anatomía del cambio** ★ — componente `AnatomyCard` (`src/components/reportes/anatomy-card.tsx`). Descompone Δventas en (tickets × unds/ticket × $/und) usando el log-decomposition. Selector 7/14/30d × período-anterior / semana-pasada / año-pasado. Alerta de margen si cambia ±1pp. Datos del endpoint `/analytics/ticket-anatomy`.
  3. **Compra urgente** + **Alertas de quiebre** (listas de SKUs accionables del módulo 04b).

  Botón Imprimir (PDF) y Descargar Excel por lista. (Reporte Semanal: pendiente.)

### Otras secciones
- **Catálogo:** Taxonomía, Product Types.
- **Operaciones:** Auditorías, Sincronización, **Configuración** (`/configuracion`) — gestionar las exclusiones de departamentos (toggles por nombre + botón "Desactivar todas las exclusiones"); cambio permanente y global, guardado por nombre en la DB.

### Transversal
- **Selector global de sucursal** (header): filtra TODAS las páginas (Todas las tiendas / Magdalena / Asamblea); persiste en localStorage.
- **Export Excel** formateado (HUDEC) y **Imprimir/PDF** (oculta el chrome vía `@media print`).
- La API devuelve decimales (`NUMERIC`) como strings JSON → el frontend los coacciona a número.

---

## 6. Estado de los datos y limitaciones

- **Costos críticamente incompletos** (P14, 2026-06-06): **80% del catálogo tiene `cost_source='NONE'`** (3,076 de 3,847 variantes). El margen calculado del endpoint `/analytics/ticket-anatomy` excluye estos SKUs en su cobertura. Excel `costos_pendientes_priorizados.xlsx` con 955 SKUs (ordenados por venta 90d) entregado para carga manual. Pareto: top 100 SKUs = 47.5% del impacto.
- **No es tiempo real** (sync por lote).
- **Historia ~13 meses** → análisis de estacionalidad/ciclo de vida automático todavía no es viable; se maneja por departamento (§4.5).
- Scripts manuales de auditoría (`tools/`) aún usan zona Lima para fechas — alinear a UTC si se usan para cuadrar contra BSale.
- **Cobertura usa velocidad reciente 30d** (P17, 2026-06-06) con fallback a lifetime. Esto cambia algunas clasificaciones vs versiones anteriores (más sensible a aceleración/desaceleración del SKU).

---

## 7. Roadmap

1. **Cargar costos** faltantes (P14, desbloquea margen/GMROI/rentabilidad de campaña).
2. **Reporte Semanal** (ventas por depto/cat + tendencia, capital parado, transferencias, descatalogar, campañas, top productos).
3. **Widget B — Venta perdida por quiebre** en `/reportes/diario` (similar a AnatomyCard pero focalizado en cuánto $ se pierde diariamente por SKUs en QUIEBRE/OPORTUNIDAD PERDIDA).
4. **Widget C — Heat-map sucursal × depto** (para saber si una caída es focal a una sucursal).
5. **Diagnóstico Alimentos Importados** profundizado (depto con 28% urgentes — posiblemente OC pendiente con proveedor asiático, lead time largo).
6. **P8** — caja específica para SKUs exclusivos de una sucursal.
7. **P9** — guard para ventas mayoristas (1 ticket > 50% de las 90d).
8. (Opcional) Refactor de las matrices a CTEs/cascada compartidos para evitar divergencias.
