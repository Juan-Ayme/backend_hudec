# Resumen ejecutivo — Sistema de clasificación KAWII Matrix

*Última actualización: 2026-06-08*

> Documento para retomar el trabajo sin tener que revivir todo el contexto.
> Si entrás en frío, leé esto primero.

---

## En 3 líneas

- Sistema clasifica **~2,160 SKUs × sucursal** en **6 secciones / 33 etiquetas** (tras renombrado P19 + cajas nuevas P15/P18).
- **Toda la lógica vive en SQL** (3 archivos: `04`, `04b`, `05` en `app/kawii_matrix/sql/` — más `08_transferencias.sql` generado desde 04b). Python (`service.py`) solo filtra/ordena el resultado. Frontend NO clasifica nada.
- **Estado: estable, sin huérfanos** (catch-all `EN ANÁLISIS` = 0 en las 3 matrices) — verificado 2026-06-08.

---

## El árbol de decisión actual (mapa de 1 vistazo) · post-rename 2026-06-06

```
A. CASOS ESPECIALES (5 cajas)
   → PRODUCTO NUEVO, TEMPORADA CERRADA OK, SALDO DE TEMPORADA, PÉRDIDA DE STOCK, VENDIÓ Y SE PERDIÓ

B. STOCK=0 + VENDIÓ BIEN (5 cajas)
   → BESTSELLER ACTIVO, BESTSELLER AGOTADO 1-2 MESES ★ (P21, antes EN PAUSA), OPORTUNIDAD PERDIDA, LENTO PERO CONSTANTE, DEMANDA EXTINTA

C. STOCK=0 + VENDIÓ POCO (8 cajas)
   → QUIEBRE DE BESTSELLER, AGOTADO CON DEMANDA, EX-BESTSELLER ENFRIADO, PRODUCTO EMERGENTE,
     PRODUCTO MUERTO, RECIBIDO Y NO VENDIDO, BAJO VOLUMEN AGOTADO, AGOTADO NO PRIORITARIO

D. STOCK>0 + SIN VENTAS (2 cajas)
   → STOCK RECIÉN LLEGADO, STOCK PARADO 90 DÍAS

E. STOCK>0 + CON VENTAS (16 cajas)
   → STOCK BAJO QUIETO, LOTE NUEVO VENDIENDO BIEN, RECIÉN REABASTECIDO, RITMO PERDIDO,
     LOTE FRENADO ★ (era SALDO QUEMADO), ROTACIÓN BAJANDO, ALTA ROTACIÓN,
     ⚡ ROTACIÓN ACTIVA AL BORDE ★★ (P23, 2026-06-12 — lote llegó hace ≤30d, vol 10-29/mes, cob ≤15d → REPONER YA),
     ROTACIÓN ACTIVA,
     INVENTARIO SANO, EXCESO+DEMANDA CAYENDO, STOCK EXCESIVO,
     🪦 LENTO CRÓNICO ★★ (P18, 2026-06-08 — captura GFQQ-240437),
     POCO STOCK CON DEMANDA, VENDIENDO MÁS QUE ANTES, BAJA ROTACIÓN

F. CATCH-ALL (1) → CASO ATÍPICO — REVISAR MANUAL (debería ser 0 siempre)
```

### Dimensiones clave (usadas en las reglas)

| Variable | Significado | De dónde |
|---|---|---|
| `proy_mes` | velocidad **lifetime** del lote actual en unds/mes | CTE `metricas` |
| `proy_30d_reciente` | velocidad **últimos 30 días** (reales) | CTE `metricas_reciente` |
| `dsv` (`dias_sin_venta_90d`) | días desde última venta | CTE `calc` |
| `sell-through neto` | (vendido + consumido + trasladado) / recibido **lifetime** | CTE `radiografia` |
| `dias_cobertura` | días que dura el stock — con vel **lifetime** | CTE `metricas` |
| `dias_cobertura_reciente` ★ | días que dura el stock — con vel **reciente** (P17) | CTE `metricas_reciente` |
| `tendencia` (v_recent_45d vs v_old_45d) | acelerando o frenando | CTE `ventas_tendencia` |
| `edad_dias` | días desde la 1ª recepción del SKU (lifetime) | CTE `calc` |
| `dias_desde_ultima_recep` | días desde la última recepción (lote actual) | CTE `calc` |
| `umbral_proy_adaptativo` | `GREATEST(3, LEAST(10, avg_cat × 0.5))` | CTE `cat_baseline` |

**La cascada de clasificación usa `dias_cobertura_reciente` (post-P17)**, no la lifetime. La lifetime se mantiene para el módulo 08 (transferencias, donde detectar excedente sostenido es lo correcto).

---

## Cambios aplicados en esta sesión (orden cronológico)

| # | Cambio | Estado |
|---|---|---|
| 1 | Endpoint `/matrix/{id}/excel` que genera .xlsx maquetado real (Portada, Índice, Resumen, 1 hoja/depto, outline colapsable) | ✅ |
| 2 | Botón "Descargar Excel" en `ventas-jerarquicas` ahora usa endpoint backend (antes era `.xls` fake client-side) | ✅ |
| 3 | Excel: columna "Ingreso" ahora es **última recepción** (no primera) | ✅ |
| 4 | Refactor del CASE clasificador: 44 → 31 reglas, 6 secciones jerárquicas con headers | ✅ |
| 5 | Cascada 35d eliminada (causaba más bugs que valor) | ✅ |
| 6 | Nuevas cajas: 🐢 ROTACIÓN LENTA SANA, 💤 DEMANDA EXTINTA | ✅ |
| 7 | Regla EXITOSO ACTIVO/PASADO con `proy_mes ≥ 10` (antes solo sell-through) | ✅ |
| 8 | Caja nueva 💎 EXITOSO OLVIDADO (vendió rápido + agotado >60d sin reponer) | ✅ |
| 9 | Umbral adaptativo de velocidad por categoría: `MAX(3, MIN(10, avg_cat × 0.5))` | ✅ |
| 10 | Filtro de mini-recepciones (qty <5) en CTEs base — rescata bestsellers mal clasificados | ✅ |
| 11 | **Whitelist almaceneros** `bsale_user_id IN (2,4,5,14,16)` reemplaza `qty>=5` en las 3 CTEs (recep_90d, primera_recep_total, ult_recep_info) | ✅ |
| 12 | EXCESO LIQUIDAR / EXCESO INVENTARIO ahora exigen `dias_desde_ultima_recep > 7` (no etiquetar como exceso si recién llegó stock) | ✅ |
| 13 | Nueva caja 🆕 RECIÉN REABASTECIDO (stock>0, recep≤7d, vL≥1, cob>45) — rescata el caso Taper 1000-1 MAGDALENA | ✅ |
| 14 | Excel jerárquico: columna "Tickets/Unds" renombrada a "Vend Lote" y muestra `Vend Lote Total` (no `Unds Vend (90d)`) — para SKUs con lote antiguo el 90d miente, el lote es la cifra real (caso F5003 SET TOALLAS LIMPIEZA: pasó de mostrar 9 a 274) | ✅ |
| 15 | **Endpoint nuevo `/analytics/ticket-anatomy`** con descomposición log de Δventas en (tickets × unds/ticket × $/und). Útil para diagnosticar caídas: "¿tráfico, canasta o precio?" | ✅ |
| 16 | **Componente `AnatomyCard`** en `/reportes/diario` — visualización del Widget A con barras divergentes, alerta de margen y selectors 7/14/30d × periodo/sem/año | ✅ |
| 17 | **Hallazgo P14 — data quality del margen**: 80% del catálogo tiene `cost_source='NONE'` → margen aparente -14pp era falso. Margen real: -2.4pp. Excel `costos_pendientes_priorizados.xlsx` generado con 955 SKUs a cargar | ⚠️ esperando carga manual de costos por el usuario |
| 18 | **Nueva caja 💀 SALDO QUEMADO** (P15): captura productos estacionales/campaña cuyo `proy_mes` lifetime es alto pero `proy_30d_reciente < 5`. Antes caían en ALTA ROT DECAYENDO con recomendación errónea de "reducir reposición — usar Vel 30d"; ahora dicen "liquidar saldo (no comprar más)". 11 SKUs capturados. Caso testigo: ESMALTE-J01 MAGDALENA. Aplicado a los 3 SQL. | ✅ |
| 19 | **Renombrado masivo de las 31 cajas + descripciones más claras**: nombres con verbo imperativo al final (REPONER YA, LIQUIDAR, VIGILAR, DESCATALOGAR). Reemplazos clave: EXITOSO→BESTSELLER, OLVIDADO→OPORTUNIDAD PERDIDA, SALDO QUEMADO→LOTE FRENADO, BAJO VOLUMEN EN ALZA→VENDIENDO MÁS QUE ANTES, ALERTA VISUAL→STOCK BAJO QUIETO, MUERTO 90D→STOCK PARADO 90 DÍAS, etc. Aplicado vía `_beta/rename_clasif.py` (34 reemplazos × 3 SQL). Sincronizado `matrix-classify.ts` (FILTERS + regex de getClasif) y `service.py` (`classify_action` reescrito con orden por especificidad, ahora usa los verbos COMPRAR YA / REPONER YA / LIQUIDAR / etc como keywords distintivas). Compat con nombres viejos mantenida en todos los matches. Action groups MUCHO más balanceados: `urgente_comprar` bajó de 822 → 1 (solo QUIEBRE real); resto distribuido en reponer/saludable/evaluar. 0 huérfanos en las 3 matrices. | ✅ |
| 20 | **Módulo 08 — TRANSFERENCIAS INTER-SUCURSAL**: nuevo SQL `08_transferencias.sql` (auto-generado por `_beta/generar_08_transferencias.py` desde 04b). Genera pares (donante × receptor × SKU): donante con exceso/lote frenado/muerto/baja rotación con stock alto, receptor con quiebre/alta rot cob baja/agotado con demanda. Devuelve unds sugeridas, stock post-transfer, impacto S/ estimado, prioridad 1-5. Expuesto vía `/matrix/08`, `/matrix/08/excel`, `/matrix/08/distribution`. 32 sugerencias actuales. Top casos: LONCHERA (transferir 129 unds de Magdalena con cob 2968d), HOJA BOND COLORES (transferir 26 de Magdalena, Asamblea con quiebre). | ✅ |
| 21 | **P16 — `📈 VENDIENDO MÁS QUE ANTES` no chequeaba cobertura**: SKUs con tendencia positiva pero cob 60+d caían acá con instrucción engañosa "vigilar, no liquidar" cuando ya tenían stock para meses. Caso testigo TRAPEADOR GF-3602 MAGDALENA (cob 80d). Agregado guard `dias_cobertura ≤ 45d` en los 3 SQL. 43 SKUs migraron a 🐢 BAJA ROTACIÓN — PEDIR MENOS. La tendencia sigue en columna `Tendencia`, no se pierde info. | ✅ |
| 22 | **P17 — Cobertura ahora usa velocidad RECIENTE (30d) en lugar de la lifetime del lote**: agregada columna `dias_cobertura_reciente` en `metricas_reciente`, calculada con `unds_vendidas_30d / dias_con_stock_30d`. Fallback a `dias_cobertura` lifetime si no hay datos recientes. Reemplazado en la cascada de clasificación de los 3 SQL (12 ocurrencias por archivo, vía `_beta/fix_p17_cobertura_reciente.py`). Hace que SKUs acelerando se detecten antes como urgentes (cobertura cae) y SKUs desacelerando muestren la realidad operativa. 0 huérfanos · TRAPEADOR y ESMALTE-J01 sin regresión. | ✅ |
| 23 | **P7 RESUELTO — Tendencia "💤 Agotado" cuando stock=0**: la columna `Tendencia` en los 3 SQL ahora chequea `stock_disponible = 0` ANTES de la fórmula v_recent vs v_old. Evita que SKUs agotados aparezcan como "📉 Decayendo" (la "caída" era por falta de stock, no por bajada de demanda). Detectado al analizar el Excel del usuario donde 27 SKUs en `🔥 BESTSELLER ACTIVO — REPONER YA` mostraban tendencia decayendo. Caso testigo: MS-3346 Tomatodo Play Hard. 995 SKUs con stock=0 ahora se ven coherentes. | ✅ |
| 24 | **P18 — Caja nueva 🪦 LENTO CRÓNICO + columnas "Llegó hace" + "Sell-through Lote %"**. Captura SKUs con edad lifetime alta pero vel lifetime baja (caso GFQQ-240437 REL DE PARED MAG: 26 unds en 10 meses, vel reciente fingía "demanda activa" por 1 venta de mayo). Condiciones: `stock>0 AND edad_dias≥180 AND dias_desde_ultima_recep≥30 AND unds_vendidas_lifetime<60 AND vel_lifetime<5/mes`. 23 SKUs detectados. Renombrada "Días desde Últ. Recep" → "Llegó hace (días)" y agregada "Sell-through Lote %" (`unds_lote_total / (unds_lote_total + stock_disponible) × 100`). Aplicado vía `_beta/fix_p18_lento_cronico.py`. | ✅ |
| 26 | **P21 — Guard dsv≥8 en LENTO CRÓNICO + rename "BESTSELLER EN PAUSA" → "⏸️ BESTSELLER AGOTADO 1-2 MESES — REPONER"**. (a) Consumibles lentos pero de reposición continua que vendieron esta semana (caso Drive Ultra: 2.7/mes, lotes chicos de 8, vendió ayer, queda 1) ya no caen en "NO REPONER" — pasan a las reglas de stock crítico. (b) Para agotados con sell-through ≥80%, el dsv mide "días sin reponer", NO enfriamiento de demanda (caso GALLETAS: vendía 37/mes, agotado 34d). Los estacionales ya se filtran antes (TEMPORADA CERRADA) → acción REPONER. classify_action: bucket evaluar→reponer. Auditoría re-verificada: 3,491/3,491. | ✅ |
| 25 | **P19 — Columna informativa "Vida lote (días)"** = `dias_desde_ultima_recep + dias_cobertura_reciente`. NO clasifica diferente, solo informa. Surge de la preocupación del usuario "¿88 días no es mucho?". Análisis: 78% del catálogo tiene vida >90d (modelo nicho), aplicar regla "vida ≤45d = sano" marcaría 92% como no-sano (inútil). Solución: dar la métrica visible para que el usuario tome decisión operativa de pedir lotes más chicos para SKUs con vida >60d. | ✅ |

---

## Pendientes priorizados (ranqueados por impacto)

### 🔴 Alta prioridad (afectan a muchos productos)

| ID | Pendiente | Por qué importa |
|---|---|---|
| **P14** | **Data quality del margen — 80% del catálogo sin costo cargado** (`variant_costs.cost_source='NONE'`). Margen aparente sesgado, `stock_valorizado` sub-valuado masivamente. | Usuario cargando costos manualmente en BSale (top 100 = 47.5% del impacto). Mientras tanto el dashboard miente. Fix técnico pendiente hasta que se cargue. |
| **P13** | **Lotes estacionales sesgan velocidad** (cuadernos compra grande en feb-marzo, después chico). El sistema mezcla picos de campaña con rotación normal. | Productos de papelería/temporada se mal-clasifican post-campaña |
| **Decisión** | **¿Aplicar la propuesta híbrida** (MAX qty en 180d, qty ≥3) **o mantener mi qty ≥5?** | Decisión pendiente del usuario. La híbrida es más adaptativa pero P13 sigue sin resolver. |
| **P1** | Data corrupta: códigos de barras escaneados en campo cantidad (L9172, G7782DF). El sistema dice ⛔ PÉRDIDA TOTAL en SKUs sanos. | Solo 2 hoy, pero el patrón se va a repetir. Fix: validar `quantity > 10⁴` en el harvester. |

### 🟡 Media

| ID | Pendiente | Por qué |
|---|---|---|
| **P8** | SKUs exclusivos de UNA sucursal sin clasificación especial (75633368128373, ESPK-001, etc.). | Operativo — el módulo 08 ya sugiere transferencias para algunos, pero falta una caja específica para "exclusivo de sucursal". |
| **P9** | Ventas mayoristas (1 ticket = >50% de ventas 90d) inflando `proy_mes`. | Productos como DT-2425TI quedan como "alta rotación" sin serlo. |

### ✅ Resueltos en esta sesión (referencia)

- **P7** — Tendencia "💤 Agotado" cuando stock=0 (era "📉 Decayendo" engañoso). Resuelto 2026-06-08.
- **P14** — Detectado: 80% del catálogo con `cost_source='NONE'`. Excel `costos_pendientes_priorizados.xlsx` entregado. Fix técnico esperando carga manual.
- **P15** — Caja nueva 💀 LOTE FRENADO (antes SALDO QUEMADO) — captura lotes viejos sin movimiento reciente. Resuelto 2026-06-06.
- **P16** — Guard `cob ≤45d` en "VENDIENDO MÁS QUE ANTES" — evita "vigilar" cuando hay 80+ días de cobertura. Resuelto 2026-06-06.
- **P17** — Cobertura ahora usa velocidad reciente 30d (con fallback lifetime). Más sensible a aceleración/desaceleración. Resuelto 2026-06-06.

### 🟢 Baja / exploratorias

| ID | Pendiente |
|---|---|
| D4-D12 | Análisis sistemáticos pendientes: cross-sell, devoluciones, estacionalidad descubierta, día-de-semana, gratuidades, drift de precio, SKUs sin recepción con ventas, etc. |
| Stock_history | Hoy solo tiene 1 día de snapshot. Si se quiere serie temporal, hay que correr el snapshot diariamente. |

---

## Para retomar mañana

### Estructura del proyecto correcto
```
C:/Users/juana/Documents/kawii_analisis/
├── backend_hudec/                ← donde está TODO
│   ├── app/kawii_matrix/sql/    ← los 3 SQL principales (04, 04b, 05)
│   │   ├── 04_matriz_90d.sql        ← snapshot 90d (más simple)
│   │   ├── 04b_matriz_90d_jerarquico.sql ← matriz jerárquica (la que usa el Excel)
│   │   ├── 05_matriz_operativa.sql  ← 04b + contexto lifetime
│   │   ├── 06_historico_productos.sql ← autopsia lifetime
│   │   ├── 07_informe_consolidado.sql ← ABC Pareto
│   │   └── 08_transferencias.sql    ★ ← AUTO-GENERADO desde 04b (P20)
│   ├── app/kawii_matrix/service.py  ← orquestador (no clasifica)
│   ├── app/kawii_matrix/router.py   ← endpoints /matrix/{id}/*
│   ├── app/routers/analytics.py     ← /analytics/ticket-anatomy (Widget A)
│   ├── analytics/excel_builder.py   ← generador del .xlsx maquetado
│   ├── analytics/excel_executive.py ← Excel jerárquico (ventas-jerarquicas)
│   ├── docs/
│   │   ├── SISTEMA.md                       ← visión general del proyecto
│   │   ├── CASOS_ANOMALOS_Y_PATRONES.md     ← P1-P17 documentados con SQL para detectar
│   │   ├── RESUMEN_EJECUTIVO_CLASIFICACION.md ← (este archivo)
│   │   ├── ARQUITECTURA.md, ESTADO_PROYECTO.md, etc.
│   ├── _beta/                       ← scripts de mantenimiento (idempotentes)
│   │   ├── rename_clasif.py             ← renombrado masivo de cajas (P19)
│   │   ├── generar_08_transferencias.py ← regenera 08 desde 04b
│   │   ├── fix_p17_cobertura_reciente.py ← fix de cobertura reciente
│   │   ├── simular_umbral_adaptativo.py ← simulador de cambios sin tocar SQL
│   │   ├── clasificador_tiempo.py       ← propuesta Python alternativa (descartada)
│   │   └── comparar.py                  ← compara SQL vs Python
│   ├── costos_pendientes_priorizados.xlsx  ← P14: 955 SKUs sin costo
│   └── top_reponer_ya.xlsx                  ← orden de compra priorizada (581 SKUs)
└── frontend_hudec/               ← Next.js
    ├── src/app/ventas-jerarquicas/page.tsx  ← página que descarga el Excel
    ├── src/app/reportes/diario/page.tsx     ← Reporte Diario con AnatomyCard
    ├── src/components/reportes/anatomy-card.tsx ← Widget A (descomposición Δventas)
    ├── src/lib/api.ts                       ← `matrixExcelUrl()`, `getTicketAnatomy()`
    ├── src/lib/matrix-classify.ts           ← FILTERS por tono (sync con nombres nuevos)
    └── src/lib/matrix-export.ts             ← .xls fake legacy (ya no se usa)
```

### Para verificar que todo sigue funcionando

```bash
cd C:/Users/juana/Documents/kawii_analisis/backend_hudec
# Reiniciar backend
./.venv/Scripts/uvicorn.exe app.main:app --reload --port 8000

# Auditoría rápida (en otra terminal)
./.venv/Scripts/python.exe -c "
import asyncio
from app.database import async_session_maker
from app.kawii_matrix import service
async def main():
    async with async_session_maker() as db:
        for mod in ['04','04b','05']:
            res = await service.run_matrix(db, mod, limit=None)
            print(f'{mod}: {len(res[\"rows\"])} filas OK')
asyncio.run(main())
"
```

### Para reabrir el tema mañana

1. **Leé este archivo primero** (te ahorra revivir contexto).
2. Si vas a atacar **P13 (estacionalidad)**, opciones:
   - Tabla `seasonal_products` manual (vos marcás qué SKUs son estacionales)
   - Detección automática (analizar ventas mes a mes por SKU, requiere D6 del backlog)
3. Si vas a **decidir sobre la propuesta híbrida** (qty ≥3 vs ≥5): los datos de la simulación están en `_beta/` y los reproducís con `./.venv/Scripts/python.exe -m _beta.simular_umbral_adaptativo`.

### Comando de emergencia: revertir un cambio

Todos los cambios al SQL fueron guardados con backups antes de aplicar. Si algo se rompe, en `/tmp/` hay snapshots:
```bash
# Listar backups
ls /tmp/04*.sql /tmp/04b*.sql /tmp/05*.sql
# Restaurar (ejemplo)
cp /tmp/04_pre_adapt.sql app/kawii_matrix/sql/04_matriz_90d.sql
```

---

## Frase de cierre

> "La clasificación que tenemos hoy es 'suficientemente buena para el 95% de los SKUs'. El 5% restante son edge cases (estacionalidad, ajustes manuales raros, ventas mayoristas) que se atacan **uno por uno cuando aparecen**, no agregando reglas universales que sirven a unos y rompen a otros."

Cuando aparezca un caso raro nuevo: ir a `CASOS_ANOMALOS_Y_PATRONES.md`, ver si encaja en un patrón existente, sumar al patrón o crear uno nuevo. Eso es el flujo. Tranqui. 🌿
