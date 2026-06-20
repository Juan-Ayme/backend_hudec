# Plan de Reportería para Gerencia — Analista de Datos KAWII

> **Propósito:** definir qué entrega el analista de datos a la gerencia, con qué
> frecuencia, de dónde sale cada reporte, qué decisión habilita y qué tan confiable
> es hoy. Incluye el roadmap de funciones futuras (análisis de ticket/canasta) y los
> datos pendientes (costos).
>
> **Contexto del negocio:** KAWII / Grupo Hudec. Tiendas: Magdalena (office 1) y
> Asamblea (office 3). Almacén Central (4) no vende. Zona horaria de operación: Lima.
> Fuente: ERP BSale → backend FastAPI + PostgreSQL → dashboard.
>
> **Última actualización:** 2026-06-01.

---

## 0. Antes de reportar: qué tan confiables son los datos HOY

Honestidad de datos primero — para no presentarle a gerencia un número que no se sostiene.

| Tipo de dato | Estado | ¿Reportable? |
|---|---|---|
| Ventas (S/), tickets, ticket promedio | ✅ Completo y correcto | Sí |
| Rotación, quiebres, días sin venta, sell-through (en unidades) | ✅ Completo | Sí |
| Stock (unidades) y clasificación de cada SKU | ✅ Completo | Sí |
| Valorización de inventario en S/ | 🟡 Cubre 84% de las unidades (faltan costos) | Sí, con nota del 16% faltante |
| **Margen / rentabilidad / GMROI** | 🔴 Solo 47% de las ventas tienen costo | **NO aún** — esperar carga de costos |

**Limitaciones que el analista debe comunicar:**
- **No es tiempo real.** El backend sincroniza con BSale por lote (sync diario ~3 AM, o manual). El día en curso es **parcial** y se mueve con cada sync; reportar siempre sobre **días cerrados** (ayer hacia atrás).
- **Fechas:** corregidas (2026-06-01) — BSale entrega fechas a medianoche UTC; el sistema ya las lee bien. Antes el dashboard mostraba todo corrido un día.

---

## 1. Reporte DIARIO (cada mañana, sobre el día cerrado anterior)

Objetivo: que la gerencia sepa en 2 minutos cómo cerró ayer y qué acción no puede esperar.

### 1.1 Pulso del día
- Ventas de ayer vs. día anterior y vs. mismo día semana pasada (S/, nº tickets, ticket promedio).
- Por sucursal (Magdalena / Asamblea).
- **Fuente:** Dashboard → KPIs + "Ventas por día" / endpoint `/analytics/sales-by-day`.
- **Decisión:** detectar caídas anómalas a tiempo.

### 1.2 Lista de compra urgente (lo que NO puede esperar)
- SKUs en clasificación `🚨 QUIEBRE STOCK`, `🔥💎 EXITOSO ACTIVO`, `🔥💎 EXITOSO RÁPIDO`, `🐢📈 LENTO QUE DESPERTÓ`.
- Traducción para gerencia: *"esto vende y está agotado o por agotarse — comprar YA o perdemos venta."*
- **Fuente:** página Matrices KAWII (filtro por clasificación) o Ventas & Catálogo (chips "Mejores"), botón **Descargar Excel**.
- **Decisión:** orden de compra del día. **Es el reporte que más plata genera** (evita venta perdida).

### 1.3 Alertas de quiebre
- Productos que se agotaron ayer y venían vendiendo bien (`QUIEBRE STOCK Alta Rotación`).
- **Decisión:** priorizar reposición / transferencia entre tiendas.

---

## 2. Reporte SEMANAL (ej. lunes, sobre la semana cerrada)

### 2.1 Resumen ejecutivo de ventas
- Ventas por **departamento**, **categoría** y **sucursal** + **tendencia** (📈 creciendo / 📉 decayendo) de los últimos 45d vs 45d previos.
- **Fuente:** Ventas & Catálogo (árbol jerárquico) + Dashboard.
- **Decisión:** dónde está creciendo/cayendo el negocio.

### 2.2 Capital parado / a liquidar
- `🧊 EXCESO DE INVENTARIO` + `🐢 BAJA ROTACIÓN` + `📦 SOBRANTE DE CAMPAÑA`.
- Hoy en unidades; en S/ al 84% (completo tras cargar costos).
- **Decisión:** promociones / liquidación para liberar caja.

### 2.3 Transferencias entre tiendas
- SKUs con exceso en una sucursal y déficit en la otra (el sistema ya sugiere cuántas unidades mover).
- **Fuente:** matriz 04/05 columna "Sugerencia Transferencia".
- **Decisión:** mover en vez de comprar = caja gratis.

### 2.4 Descatalogar
- `💀 MUERTO 90D`, `🪦 AGOTADO MARGINAL`, `🪦 RESIDUO HISTÓRICO`.
- **Decisión:** dejar de comprar / sacar del surtido.

### 2.5 Estado de campañas estacionales
- Departamentos estacionales: Temporada y Celebraciones (21) + Librería/escolar (12).
- `✅ TEMPORADA CERRADA` (vendió su campaña → recomprar para la próxima) vs `📦 SOBRANTE` (liquidar).
- **Decisión:** plan de recompra para la próxima campaña (escolar enero, Navidad, Halloween, etc.).

### 2.6 Top productos de la semana
- Más vendidos en S/ y en unidades.
- **Fuente:** `/analytics/top-products`.

---

## 2bis. Tablero semanal de KPIs (los 5 indicadores) — endpoints

Implementa el "tablero que se revisa cada semana". Cada KPI tiene su endpoint; el
tablero consolidado los junta y se puede exportar a Excel **con una pestaña por informe**.

| KPI | Frecuencia | Endpoint | Fórmula |
|---|---|---|---|
| Ticket promedio | Diaria | `/analytics/sales-by-day` (col `ticket_promedio`) · `/analytics/kpis` | ventas ÷ tickets con monto |
| N° de transacciones | Diaria | `/analytics/sales-by-day` (col `tickets`) · `/analytics/kpis` | `COUNT(documents)` (1 doc = 1 ticket) |
| Venta por categoría | Semanal | `/analytics/sales-by-category` | `SUM(total_amount)` por categoría (+ % participación en el tablero) |
| SKUs en quiebre | Semanal | `/analytics/stockouts` | `stock_disponible ≤ 0`; marca `tenia_demanda` (vendió en 30d) |
| Venta acumulada vs meta | Diaria | `/analytics/sales-vs-goal` | acumulado del mes vs meta prorrateada |

Filtros base de todos: solo tiendas de venta (offices 1 y 3), excluye notas de crédito,
fecha del documento en UTC.

**Consolidado:** `GET /analytics/weekly-board?days=7&office_id=&month=` → los 5 KPIs en un payload.

**Excels descargables** (reemplazaron al "Excel Semanal" original, que era redundante):
- `GET /analytics/compras-catalogo/excel` — Quiebres jerárquicos por departamento
  (📊 Resumen + 1 hoja por departamento con Cat→SubCat→SKU usando la matriz 04b) +
  pestaña final *Venta por categoría* con ticket promedio.
- `GET /analytics/daily-report/excel` — Mes en curso día a día. 3 pestañas:
  *Ticket promedio* (con LineChart) · *Transacciones* (con BarChart) · *Venta vs meta*
  multi-bloque (Desglose metas · Reporte diario · Semáforo · Tabla seguimiento).

**Meta (manual):** se carga con `PUT /analytics/goals`
(body: `{"month":"2026-06","meta_global":200000,"offices":{"1":120000,"3":80000}}`, montos en S/)
y se consulta con `GET /analytics/goals`. Se persiste en `app_config` (clave `sales_goals`),
keyed por mes. Si el mes en curso no tiene meta, hereda la del último mes cargado; si no
hay ninguna, el KPI marca `no_configurada` y el resto del tablero funciona igual.
Fórmulas: `meta_prorrateada = meta × días_transcurridos / días_del_mes`,
`avance_% = acumulado / meta`, `proyección_cierre = acumulado / días_transcurridos × días_del_mes`.

**Quiebre vs inventario muerto:** `/analytics/stockouts` lista TODOS los SKUs en 0 y marca
`tenia_demanda=true` a los que vendieron en los últimos 30 días (= **venta perdida real**,
lo accionable). Ordena los con demanda primero. Mucho stock en 0 es inventario muerto: el
número accionable es `con_demanda`, no `total` (ver §4.3, quiebre ≠ caída de demanda).

> Nota: el día en curso es PARCIAL (sync por lote). Para gerencia, revisar días cerrados.

---

## 3. Reporte MENSUAL — bloque financiero (PENDIENTE de costos)

> ⚠️ **No presentar hasta tener ≥80% de las ventas con costo.** Hoy: 47%.

### 3.1 Margen por categoría / SKU
Ingreso − (unidades × costo). Qué categorías dejan plata y cuáles no.

### 3.2 GMROI (retorno sobre inventario)
Margen × rotación. **La métrica estrella del category management:** cuánto margen genera cada sol invertido en inventario. Distingue al "vende mucho pero margen bajo" del "vende poco pero muy rentable".

### 3.3 Rentabilidad de campaña
No solo cuánto vendió la campaña escolar/navideña, sino cuánto **ganó**.

### 3.4 Valorización real de capital inmovilizado (S/)
Cuánta plata está dormida en exceso/muertos — el argumento duro para liquidar.

---

## 4. FUNCIÓN FUTURA — Análisis de TICKET / Canasta

> Esto es la evolución del reporte cuando los datos estén más limpios. Hoy existe el
> **ticket promedio agregado** (ventas ÷ nº tickets ≈ S/ 16.55); falta el análisis a
> nivel de **canasta** (qué hay dentro de cada ticket). La data lo soporta: cada
> documento de venta = un ticket, con sus líneas en `document_details`.

### 4.1 Descomponer el ticket promedio (el "por qué cambia")
El ticket promedio puede subir o bajar por dos razones distintas, y hay que separarlas:
- **Unidades por ticket** (¿la gente lleva más o menos ítems?)
- **Precio promedio por unidad** (¿compran productos más caros o más baratos?)

> `Ticket promedio = unidades por ticket × precio promedio por unidad`

Si el ticket baja, este desglose dice si es por **menos ítems** (problema de venta cruzada / surtido) o por **mix más barato** (problema de categorías premium). Son acciones distintas.

### 4.2 Relación ticket ↔ productos
- **Productos ancla:** los que aparecen en los tickets más grandes / arrastran otras compras.
- **Venta cruzada:** qué se compra junto (canastas frecuentes).
- **Decisión:** ubicación en tienda, combos, qué nunca debe faltar.

### 4.3 El caso clave: quiebre de stock ≠ caída de demanda
El análisis más valioso que pediste. Cuando las ventas de un producto/categoría caen, hay que distinguir:
- **Cayó la demanda** (el cliente ya no lo quiere) → revisar surtido / descatalogar.
- **Se agotó el stock** (el cliente lo quiere pero no había) → **venta perdida**, reponer urgente.

El sistema ya marca la diferencia: si la caída coincide con clasificación `AGOTADO` / `QUIEBRE STOCK` / `TEMPORADA CERRADA`, **la caída es por falta de stock, no de demanda.** Cruzar la caída de ventas con la clasificación del SKU evita la conclusión equivocada ("este producto ya no vende") cuando en realidad **se terminó y por eso no hay ventas** — y eso impacta el ticket y el tráfico de toda su categoría.

> Ejemplo real del sistema: la JARRA (0531-18) se agotó pero su demanda venía **subiendo**
> (`🐢📈 LENTO QUE DESPERTÓ`). Sin este cruce parecería "muerto"; en realidad es "reponer ya".

### 4.4 Requisitos para activar este bloque
- Reconstruir el ticket a nivel línea (ya hay base: `documents` + `document_details`).
- Datos más limpios (costos cargados, taxonomía consistente).
- Endpoint/reporte de canasta (a desarrollar).

---

## 5. Pendientes de datos (roadmap del analista)

1. **Cargar costos faltantes** — hoy solo 20% de las variantes tienen costo (47% de las ventas). Prioridad por impacto en ventas:
   1. **Librería y Oficina** — S/ 412k en ventas 90d, solo 40% costeado.
   2. Cuidado Personal y Salud — 36%.
   3. Belleza — 45%.
   4. Abarrotes — 38%.
   - Cargar primero lo que **vende**, no la cola larga de productos muertos.
   - Esto desbloquea TODO el bloque financiero (sección 3) y el de rentabilidad de ticket.
2. **Análisis de canasta / ticket** (sección 4) — desarrollar cuando costos ≥80%.
3. **Frescura de datos** — si se necesita más que diario, programar el sync incremental cada 15-30 min.
4. **Alinear scripts de auditoría** (`tools/`) a la lectura de fecha en UTC para cuadrar cifras contra BSale.

---

## 6. Resumen: cadencia de entrega

| Frecuencia | Entregables | Estado |
|---|---|---|
| **Diario** | Pulso del día · Compra urgente · Alertas de quiebre | ✅ Listo |
| **Semanal** | Ventas por depto/cat/sucursal · Capital parado · Transferencias · Descatalogar · Campañas · Top productos | ✅ Listo |
| **Mensual** | Margen · GMROI · Rentabilidad de campaña · Valorización S/ | 🔴 Tras cargar costos |
| **Futuro** | Análisis de ticket/canasta · Quiebre vs demanda · Venta cruzada | 🟡 Requiere datos limpios |
