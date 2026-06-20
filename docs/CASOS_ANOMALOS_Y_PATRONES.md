# Casos anómalos y patrones de comportamiento de SKUs

**Propósito:** catálogo vivo de productos cuya clasificación resultó incorrecta o
engañosa, con los datos reales que llevaron al fallo. Cada caso documenta:

1. Qué decía el sistema vs qué pasaba en la realidad.
2. Por qué la regla cayó mal (la métrica que mintió).
3. El cambio que se aplicó (o se evaluó) para corregirlo.
4. Cómo detectar otros productos con el mismo patrón.

**Mantenimiento:** cuando aparezca un nuevo caso raro, agregar al final de la
sección "Casos individuales" siguiendo la misma plantilla. Si el caso pertenece
a un patrón ya identificado, sumar al patrón existente (sección "Patrones").

---

## Índice de patrones identificados

| # | Patrón | Casos conocidos | Estado |
|---|---|---|---|
| P1 | Data corrupta: códigos de barras en campo cantidad | L9172, G7782DF | ⚠️ Sin fix (pendiente opción A en harvester) |
| P2 | Mermas/consumos no descontados del denominador del sell-through | FXT-2289 | 🟡 Mitigado por sell-through neto (V+C+T)/R |
| P3 | Cascada del lote 35d usando lotes antiguos | GEL DE AFEITAR, 300050845 | ✅ Resuelto al eliminar cascada 35d |
| P4 | "EXITOSO" mintiendo en productos de rotación lenta sostenida | SKY ESPUMA, KD-2605 | ✅ Resuelto con regla velocidad ≥10/mes |
| P5 | Productos agotados hace mucho tiempo etiquetados como "evaluar" | 300050845, SKY Asamblea, EP-9534 | ✅ Resuelto con dsv≤60 en EXITOSO PASADO |
| P6 | Lotes <5 unidades saltan la lógica de sell-through del último lote | DA-180-1, 300050845 | ✅ Cubierto por sell-through lifetime |
| P7 | "Decayendo" engañoso en productos agotados (cae por falta de stock, no de demanda) | FXT-2289 Magdalena, MS-3346, CC-527, +25 SKUs en BESTSELLER ACTIVO con tendencia decayendo | ✅ **Resuelto (2026-06-08)**: la columna `Tendencia` ahora muestra "💤 Agotado" cuando `stock_disponible = 0 AND unds_vendidas > 0`. Aplicado a los 3 SQL antes de la fórmula v_recent vs v_old. |
| P8 | SKUs exclusivos de UNA sucursal pese a estar en catálogo común | 75633368128373, ESPK-001, MZR-660 | 🔍 Descubierto, sin caja especial. Mitigado parcialmente por módulo 08 (transferencias). |
| P9 | Ventas "fantasma": 1 ticket gigante distorsiona el promedio del SKU | DT-2425TI, 108-6DF, HY26-3MA | 🔍 Detección recién implementada, evaluar caja nueva |
| P10 | Vendió todo + velocidad alta + agotado >60d → "demanda extinta" mintiendo | B1045 Asamblea, 300050845 MAG, EP-9534 MAG, 254 más | ✅ Resuelto con 💎 OPORTUNIDAD PERDIDA (antes EXITOSO OLVIDADO) |
| P11 | Umbrales fijos (10/mes) injustos para categorías nicho | Productos en Decoración, Perfumes, Muebles | ✅ Resuelto con umbral adaptativo por categoría: MAX(3, MIN(10, avg_cat × 0.5)) |
| **P12** | **Mini-recepciones (<5 unds) envenenan el cálculo de velocidad del lote** | **GFXY-2819 MAG, 57996, BOLIG FAB, CUAD SCOOL, TIJERA, 1500+ SKUs afectados** | ✅ **Resuelto: whitelist de almaceneros (uid 2, 4, 5, 14, 16) — los ajustes de cajas/ADM se ignoran. Reemplaza al filtro `qty>=5` anterior** |
| **P13** | **Producto recién reabastecido (≤7d) etiquetado como "EXCESO LIQUIDAR" porque el cálculo de cobertura usa la velocidad histórica** | **Taper 1000-1 MAG (recibió 48 ayer, vendió 1, cob=70d), y otros similares** | ✅ **Resuelto: 2 cambios** — (1) excluir productos con `dias_desde_ultima_recep ≤ 7` de EXCESO LIQUIDAR/EXCESO; (2) nueva caja 🆕 RECIÉN REABASTECIDO atrapa los recién reabastecidos con historial y cob>45 |
| **P14** | **`variant_costs.effective_cost = 0` infla el margen calculado** (80% del catálogo con `cost_source='NONE'`) | 3,076 variantes sin costo · 955 SKUs vendieron sin costo cargado (S/ 457K en 90d) · top: CUAD SCOOL S/88H, CUADERNNO JUSTUS, PAPEL FOTOC MILLENIUM | ⚠️ **Detectado y documentado**: usuario cargando costos manualmente en BSale desde `costos_pendientes_priorizados.xlsx`. Top 100 SKUs = 47.5% del impacto. Fix técnico (cob de margen, exclusión de cost=0) pendiente hasta que se carguen. |
| **P15** | **Lote viejo con velocidad lifetime alta pero reciente ≈ 0** — clasificaba mal estacionales/campañas terminadas | ESMALTE JARUSA MAG (vel lifetime 48/mes, reciente 1/mes), PARAGUA, CORREA MASCOTA, PLATO TENDIDO, BIZCOCHO COSTA CANCÚN, +6 más (11 totales) | ✅ **Resuelto (2026-06-06)**: nueva caja 💀 LOTE FRENADO (antes SALDO QUEMADO). Condiciones: `stock≥5 AND proy_mes≥10 AND proy_30d_reciente<5 AND edad_dias≥90`. Va antes que ALTA ROTACIÓN DECAYENDO en la cascada. |
| **P16** | **"📈 VENDIENDO MÁS QUE ANTES" no chequeaba cobertura** — clasificaba mal SKUs con stock para 60+ días | TRAPEADOR GF-3602 MAG (stock 14, cob 80d) — Excel decía "vigilar, no liquidar" cuando ya tenía 3 meses de cob | ✅ **Resuelto (2026-06-06)**: agregado guard `COALESCE(dias_cobertura_reciente, 9999) ≤ 45` a la regla en los 3 SQL. SKUs con cob > 45d caen a 🐢 BAJA ROTACIÓN. La tendencia sigue visible en columna `Tendencia`. |
| **P17** | **Cobertura usaba velocidad lifetime del lote** — insensible a aceleración/desaceleración | Todos los SKUs (cambio global). Caso testigo: CD-135 Mantel bambú (vendía 14/30d antes, ahora 6/30d → vel reciente cayó 57% pero cob lifetime no reflejaba) | ✅ **Resuelto (2026-06-06)**: agregada columna `dias_cobertura_reciente` en `metricas_reciente` (con fallback a lifetime). Reemplazado en 12 ocurrencias × 3 archivos en la cascada de clasificación. Aplicado vía `_beta/fix_p17_cobertura_reciente.py`. La CTE `transferencias` mantiene la lifetime (correcto para detectar excedente sostenido). |
| **P18** | **SKUs con velocidad reciente "fingida" pero patrón lifetime claramente lento** — el sistema veía "demanda activa" en SKUs que llevan años con stock acumulado | GFQQ-240437 REL DE PARED MAG (26 unds en 10 meses, vel lifetime ~3/mes, pero vel reciente subió a 9/mes por una venta de mayo → entraba a ⚠ POCO STOCK CON DEMANDA "reponer"); +22 más (cosméticos JARUSA, gel de baño, licor frutado, etc.) | ✅ **Resuelto (2026-06-08)**: nueva caja **🪦 LENTO CRÓNICO — NO REPONER**. Condiciones: `stock>0 AND edad_dias≥180 AND dias_desde_ultima_recep≥30 AND unds_vendidas_lifetime<60 AND vel_lifetime<5/mes`. El guard `dias_desde_ultima_recep≥30` evita capturar SKUs con restock reciente que están rotando bien. 23 SKUs detectados. Además se renombró columna "Días desde Últ. Recep" → "Llegó hace (días)" y se agregó columna "Sell-through Lote %" para que el usuario vea ambos datos juntos. Aplicado vía `_beta/fix_p18_lento_cronico.py`. |
| **P23** | **La franja 10-29/mes no escalaba por cobertura crítica** — un SKU vendiendo a diario con 1-2 unds en góndola decía "💫 MANTENER FLUJO: reposición regular"; la urgencia por quiebre inminente solo existía para ≥30/mes (ALTA ROTACIÓN — PRIORIDAD DE COMPRA) | SARTEN 18CM 982061800 y SARTEN 16CM 980981601 MAG (6 unds en 8d exhibido = 22.5/mes, queda 1, cob 5d); CORTINA 130184 MAG (cob 3d); ESCOBILLA BAÑO (59 unds/90d, queda 1, cob 2d); MOLDE L9139 / ORGANIZADOR L9106 / BASURERO GF-2801 (cob 8-11d, ejemplos del usuario). El GEL 801104 (cob 18d) queda FUERA — correcto con margen de 15d | ✅ **Resuelto (2026-06-12, 2 iteraciones)**: nueva caja **⚡ ROTACIÓN ACTIVA AL BORDE — REPONER YA** insertada entre ALTA ROTACIÓN y ROTACIÓN ACTIVA: `stock>0 AND proy_mes ≥ umbral_adaptativo AND dias_cobertura_reciente ≤ 15 AND dias_desde_ultima_recep ≤ 30`. **Corte 15d = margen de reposición** (decisión del usuario: sus 4 casos tenían cob 3-11d y con corte 7 se escapaban 3). **Iteración 2 (mismo día)**: la 1ª versión sin guard de frescura movió 110 SKUs y el usuario detectó veteranos (57-143d exhibido, ej. PLATO MH52-323 con 143d) cuya recompra es RUTINA, no descubrimiento → guard de frescura: la caja queda para **lotes recientes que vuelan**, los 67 veteranos vuelven a MANTENER FLUJO. **Iteración 3 (mismo día)**: el guard pasó de `dias_exhibido ≤ 30` (43 SKUs — solo nuevos/relanzamientos, porque el exhibido se acumula en el ciclo y no se reinicia con cada reposición) a `dias_desde_ultima_recep ≤ 30` (53 SKUs — cubre además las **reposiciones que quedaron cortas**: papel higiénico Paracas llegó 10d/cob 4d, SH Nutribela llegó 28d/cob 3d, +8). Cambio 100% aditivo: los 43 se quedaron, 0 salieron. El nombre contiene "ROTACIÓN ACTIVA" (chip "Mejores" del frontend, tono verde del Excel y BUCKET_COMPRABLE matchean solos) y "REPONER YA" (bucket de acción `reponer`). Verificado con snapshot pre/post en cada iteración: flips exactos (110, luego 67 de vuelta), 0 cambios en otras cajas, 0 filas perdidas. Primera caja agregada post-unificación de SQLs: UNA sola edición en `_matriz_90d_base.sql`. |
| **P22** | **(a) Recepciones/consumos con códigos de barras tipeados como CANTIDAD** (recep Nº1644: G7782DF +6.97 billones; recep Nº10254: L9172 +100 mil millones; ambos con consumos "correctivos" igual de corruptos — el stock físico cuadraba y nadie lo notó); **(b) columna "Cobertura" mostraba la lifetime cuando la cascada clasifica con la reciente** (258 filas en banda distinta — caso GLOB-P "26 días" mostrado vs 45d usado) **y mostraba 's/d' con stock=0** (214 filas); **(c) stock del Almacén Central invisible** (38 SKUs / 8,717 unds — el reporte decía "REPONER=comprar" cuando correspondía trasladar) | L9172 estaba clasificado **⛔ PÉRDIDA DE STOCK — revisar robos** por el sell-through envenenado (vendió "0.000001%" de 100 mil millones); con el fix pasó a **🔥 BESTSELLER ACTIVO — REPONER YA** (su realidad). G7782DF envenenado latente (sin actividad reciente). | ✅ **Resuelto (2026-06-11)**: (a) **tope de sanidad** `quantity ≤ 50,000` en las 3 CTEs de recepciones + consumos_lifetime (máximos legítimos históricos: 10,000 recep / 2,250 consumo — solo mata las 4 filas corruptas); (b) "Cobertura" ahora muestra `dias_cobertura_reciente` (la que clasifica) y stock=0 siempre dice 'Agotado' — divergencia de banda: 258→0, s/d con stock=0: 214→0; (c) CTE `stock_almacen` (oficinas fuera de sucursales_objetivo) + columna **"Stock Almacén"** en matriz y Excel (col 18, azul si >0). Verificado con snapshot pre/post: 10,445/10,448 idénticas — las 3 diferentes son L9172 corregido. Auditoría completa: 0 errores en TODAS las categorías por primera vez. NOTA: whitelist de almaceneros NO se tocó (decisión del usuario: Pilar/Liz hacen ajustes, no recepciones de mercadería). Pendiente manual: corregir en BSale recep Nº1644/Nº10254 y sus consumos. |
| **P21** | **(a) LENTO CRÓNICO contradictorio en consumibles de reposición continua; (b) "BESTSELLER EN PAUSA — la demanda se enfrió" era una lectura falsa para agotados** | (a) Drive Ultra Care 2.5Kg MAG (23 unds/259d = 2.7/mes, pero compras chicas bien dimensionadas, vendió AYER, queda 1 und → decía "NO REPONER" hoy y al agotarse diría "REPONER POCO"); (b) GALLETAS 77204702130714 MAG (30 unds en 9d + 30 en 24d = 37/mes, agotado hace 34d → decía "la demanda se enfrió" cuando en realidad nadie repuso; sin stock la demanda no se puede medir) | ✅ **Resuelto (2026-06-10)**: (a) guard `dias_sin_venta_90d ≥ 8` en LENTO CRÓNICO — si vendió esta semana, deciden las reglas de stock crítico (12 SKUs quedan en la caja, antes 28); (b) caja renombrada **⏸️ BESTSELLER AGOTADO 1-2 MESES — REPONER** (268 filas): los estacionales ya fueron capturados antes por TEMPORADA CERRADA, así que lo que llega ahí es no-estacional y la acción correcta es reponer. Actualizado `classify_action()` (bucket reponer) y matcher del frontend. Auditoría completa re-verificada: réplica 3,491/3,491, 0 violaciones semánticas. |
| **P19** | **El usuario querría que los lotes duren ≤45d para considerarse "sanos"** — su intuición: si tarda 88d en venderse el lote completo, es demasiado | TB054-F213 AZUCARERA MAG (vida total 85d, sigue como ROTACIÓN ACTIVA); DMBT006 CUBERA HIELO MAG (96d como INVENTARIO SANO); 4 productos abril 2026 más | ✅ **Resuelto vía COLUMNA INFORMATIVA, no nueva caja (2026-06-08)**: análisis de distribución mostró que **78% del catálogo tiene vida total >90d** (modelo nicho — cosméticos, decoración, bebidas asiáticas). Aplicar la regla "vida ≤45d = sano" marcaría 92% del catálogo como "no sano", inutilizable. **Solución**: agregada columna `"Vida lote (días)"` = `dias_desde_ultima_recep + dias_cobertura_reciente` en los 3 SQL. Es INFORMATIVA — no cambia clasificaciones, pero el usuario puede ver de un vistazo cuánto tardará el lote completo en agotarse. Decisión operativa derivada: pedir lotes más chicos para SKUs con vida >60d. |

---

## Patrones (descripción + cómo detectar)

### P1 · Data corrupta: códigos de barras en campo cantidad
**Pendiente:** harvester / ingesta debería capear o rechazar.

- **Síntoma:** `unds_recibidas_lifetime`, `unds_consumidas_lifetime` o `quantity` con valores absurdos (miles de millones / billones).
- **Causa:** alguien escaneó el código de barras (EAN-13 = 13 dígitos, valores típicos de 10¹² a 10¹³) en el campo de cantidad de una recepción o consumo. Luego registró un consumo casi igual para "cancelarlo", lo que mantiene el stock neto correcto pero envenena las métricas.
- **Detección SQL:**
  ```sql
  SELECT rd.bsale_variant_id, v.display_code, rd.quantity,
         r.bsale_office_id, r.admission_date
  FROM reception_details rd
  JOIN receptions r USING(bsale_reception_id)
  JOIN variants v ON v.bsale_variant_id = rd.bsale_variant_id
  WHERE rd.quantity > 10000
  ORDER BY rd.quantity DESC;

  SELECT cd.bsale_variant_id, v.display_code, cd.quantity, c.consumption_date
  FROM consumption_details cd
  JOIN consumptions c USING(bsale_consumption_id)
  JOIN variants v ON v.bsale_variant_id = cd.bsale_variant_id
  WHERE cd.quantity > 10000
  ORDER BY cd.quantity DESC;
  ```
- **Impacto en clasificación:** producto cae en ⛔ PÉRDIDA TOTAL aunque en realidad sea sano, porque su sell-through aparece como 0% (vendido 11 / recibido 100B = 0%).
- **Fix propuesto (pendiente):** en el harvester, rechazar o capear (a 100,000?) cualquier `quantity` que parezca un código de barras (>10⁴ o longitud ≥13 dígitos).

---

### P2 · Mermas en el denominador del sell-through del lote
**Estado:** mitigado en SQL (las reglas EXITOSO ACTIVO/PASADO usan sell-through neto: ventas + consumos + traslados / recibido). La cascada 35d original tenía el bug pero se eliminó.

- **Síntoma:** producto vendió "todo lo vendible" pero el sell-through del lote da menor a 80% porque parte del lote salió por merma (consumo).
- **Ejemplo:** recibió 25, vendió 19, mermó 6 → vendió 100% de lo vendible pero `19/25 = 76%`.
- **Por qué importa:** el corte de 80% para "exitoso" deja afuera a los productos con mermas naturales (rotura, robos pequeños, regalos), aunque comercialmente fueron éxitos.
- **Detección SQL** (cuántos productos están en este caso):
  ```sql
  SELECT v.display_code, vts.unds_vendidas_lifetime, cl.unds_consumidas_lifetime,
         prt.unds_recibidas_lifetime,
         vts.unds_vendidas_lifetime::float / NULLIF(prt.unds_recibidas_lifetime,0) AS st_solo_ventas,
         (vts.unds_vendidas_lifetime + cl.unds_consumidas_lifetime)::float / NULLIF(prt.unds_recibidas_lifetime,0) AS st_neto
  FROM variants v
  JOIN /* las CTEs vts, cl, prt o tablas equivalentes */ ...
  WHERE st_solo_ventas < 0.80 AND st_neto >= 0.80;
  ```
- **Fix vigente:** reglas EXITOSO ACTIVO / EXITOSO PASADO en SQL usan `(V_life + C_life + T_life) / R_life ≥ 0.80` en vez de `V_life / R_life`.

---

### P3 · Cascada del lote 35d usando lotes antiguos
**Estado:** ✅ resuelto al eliminar la cascada 35d (la nueva lógica usa sell-through lifetime + velocidad + recencia).

- **Síntoma:** producto cuyo último lote llegó hace meses, y el sistema lo evalúa por "qué porcentaje vendió en los primeros 35 días post-recepción". Como ese ciclo es historia antigua, etiqueta "saludable, reponer normal" a un producto prácticamente muerto.
- **Por qué fallaba:** la cascada de 35d tenía sentido cuando el lote era reciente, pero se aplicaba sin filtro temporal.
- **Fix aplicado:** se eliminaron las 5 reglas de la cascada 35d (`EXITOSO RÁPIDO`, `ROTACIÓN MEDIA`, `LENTA AGOTADA`, `LENTO AGOTADO`, `LENTO QUE DESPERTÓ`). Ahora el SQL usa solo sell-through lifetime + velocidad + recencia, que sí discrimina vivos vs muertos.
- **Detección de remanentes:** ya no debería haber falsos positivos. Si vuelven, buscar productos con `dias_desde_ultima_recep > 90` etiquetados como "EXITOSO ACTIVO".

---

### P4 · "EXITOSO" mintiendo en productos de rotación lenta sostenida
**Estado:** ✅ resuelto con `proy_mes ≥ 10` como condición de EXITOSO ACTIVO/PASADO. Productos lentos caen en 🐢 ROTACIÓN LENTA SANA.

- **Síntoma:** producto vendió 100% de lo recibido lifetime + tiene venta reciente → SQL lo etiquetaba 🔥💎 EXITOSO ACTIVO "REPONER YA", pero vendía 5-7/mes (no es urgente).
- **Por qué fallaba:** EXITOSO ACTIVO miraba solo sell-through y recencia, no velocidad. Si vendió 60 en 10 meses, sigue siendo "100% vendido" pero la velocidad real es modesta.
- **Fix aplicado:** EXITOSO ACTIVO/PASADO ahora exigen `proy_mes ≥ 10`. Si `proy < 10` con buen sell-through → 🐢 ROTACIÓN LENTA SANA (reponer cantidades chicas).

---

### P5 · Agotados hace mucho etiquetados como "evaluar" cuando deberían ser "muertos"
**Estado:** ✅ resuelto con `dsv ≤ 60` en EXITOSO PASADO. Si dsv > 60 → 💤 DEMANDA EXTINTA (no reponer).

- **Síntoma:** producto con sell-through alto + dsv > 60 días caía en 💎 EXITOSO PASADO "evaluar antes de reponer", cuando en realidad la demanda murió hace tiempo.
- **Fix aplicado:** la cadena de la Sección B es ahora estricta:
  - 🔥💎 EXITOSO ACTIVO: proy≥10, dsv≤30 (vivo)
  - 💎 EXITOSO PASADO: proy≥10, dsv≤60 (pausa reciente)
  - 🐢 ROTACIÓN LENTA SANA: proy<10, dsv≤60 (modesto pero vivo)
  - 💤 DEMANDA EXTINTA: dsv>60 (catch-all sin importar velocidad)

---

### P6 · Lotes <5 unidades — caso especial
**Estado:** la cascada 35d (ahora eliminada) los saltaba. Hoy todos pasan por sell-through lifetime sin discriminación de tamaño del último lote.

- **Síntoma:** producto recibió lote chico (1, 2, 3, 4 unidades). La cascada 35d exigía `ult_recep_qty ≥ 5` y los saltaba.
- **Cómo se manejaba antes:** caían a EXITOSO ACTIVO/PASADO por sell-through lifetime.
- **Estado actual:** ya no hay cascada 35d. Los lotes chicos pasan por la misma lógica que el resto.

---

### P7 · "Decayendo" en productos agotados (matemáticamente correcto pero confuso)
**Estado:** ⚪ sin fix. La regla no es incorrecta — es matemática — pero la lectura confunde.

- **Síntoma:** producto agotado (stock=0) muestra Tendencia "📉 Decayendo".
- **Causa real:** la regla de Tendencia compara `v_recent_45d` vs `v_old_45d`. Si el producto se agotó hace 30-40 días, las últimas 45 días tienen menos ventas que las 45 anteriores (porque ya no hay stock que vender) → "Decayendo".
- **Lectura correcta:** "vendió poco últimamente PORQUE se agotó", no "la demanda está bajando".
- **Fix posible:** en productos con `stock_disponible = 0`, mostrar "🚫 Agotado" en lugar de "Decayendo". Pendiente decisión del usuario.

---

### P12 · Mini-recepciones (<5 unds) envenenan el cálculo de velocidad del lote
**Estado:** ✅ resuelto. Filtros `qty >= 5` agregados en CTEs base (`recep_90d`, `primera_recep_total`, `ult_recep_info`).

- **Síntoma:** producto bestseller (vende cientos/mes) clasificado como 💤 DEMANDA EXTINTA o 🐢 BAJA ROTACIÓN porque su última recepción fue un ajuste de **1-4 unidades** (típicamente "Sin Documento" — encontraron una pocas, devolución física, ajuste de inventario).
- **Causa técnica:** las CTEs `recep_90d.primera_recep_90d` y `primera_recep_total.ultima_recepcion` tomaban el `MIN/MAX(admission_date)` SIN filtrar cantidad. Cuando había una mini-recepción reciente, esa fecha pasaba a ser el "inicio del lote actual", y todo el cálculo de velocidad (`unds_lote_total / dias_efectivos = proy_mes`) se basaba en las pocas ventas posteriores, NO en el lote material previo.
- **Caso típico**: GFXY-2819 MAGDALENA. Lote real de 96 unds llegó el 13/02/2026, vendió las 96 en ~40 días (velocidad ~72/mes). El 24/03 hubo una recepción de **1 unidad** sin documento → SQL pensó que el "lote actual" era esa 1 unidad → `proy_mes = 8.57/mes` → 💤 DEMANDA EXTINTA.
- **Magnitud del bug:**
  - 30.6% de TODAS las recepciones tienen qty <5
  - 24.4% de los SKUs tienen su última recepción <5 unds
  - 14.5% tienen última recep = 1 unidad
  - Productos top-vendedores afectados: CUAD SCOOL S/88H (1,945 unds/90d), Cuaderno Justus (1,090), BOLIG FAB Trilux (938), SET LAPICERO GEL X3 (785), TIJERA (571), etc.
- **Detección SQL** (encontrar más casos del mismo patrón):
  ```sql
  WITH ult AS (
    SELECT DISTINCT ON (r.bsale_office_id, rd.bsale_variant_id)
      r.bsale_office_id, rd.bsale_variant_id, r.admission_date::date d, rd.quantity ult_qty
    FROM reception_details rd JOIN receptions r USING(bsale_reception_id)
    WHERE r.bsale_office_id IN (1,3) AND rd.quantity < 1e9
    ORDER BY 1,2, r.admission_date DESC
  ), v90 AS (
    SELECT d.bsale_office_id, dd.bsale_variant_id, SUM(dd.quantity) v
    FROM documents d JOIN document_details dd USING(bsale_document_id)
    WHERE d.bsale_office_id IN (1,3) AND d.bsale_document_type_id IN (1,10,50,51,52,53)
      AND d.emission_date >= NOW() - INTERVAL '90 days'
    GROUP BY 1,2
  )
  SELECT v.display_code, p.name, ult.ult_qty, v90.v::int v90, ult.d::date
  FROM ult JOIN v90 USING(bsale_office_id, bsale_variant_id)
  JOIN variants v USING(bsale_variant_id) JOIN products p USING(bsale_product_id)
  WHERE ult.ult_qty < 5 AND v90.v >= 20
  ORDER BY v90.v DESC;
  ```
- **Fix implementado:** las 3 CTEs base ahora ignoran recepciones <5 unds para definir la fecha de "inicio del lote", PERO siguen contando todo el volumen (`unds_recibidas_lifetime`, `unds_recibidas_90d`) para no romper el sell-through. Cambio quirúrgico: 3 CTEs × 3 archivos = 9 ediciones.

---

## Casos individuales

Cada entrada es un SKU específico con datos reales que disparó el descubrimiento de un patrón o reveló un caso límite.

### Plantilla para nuevos casos
```markdown
### [Código SKU] · [Nombre del producto]
- **Sucursal:** [ASAMBLEA / MAGDALENA / ambas]
- **Patrón:** [P1, P2, P3...]
- **Datos crudos:**
  - stock = X
  - V90 / R90 = X / X
  - V_life / R_life / C_life / T_life = X / X / X / X
  - proy_mes = X
  - dsv = X
  - edad_dias = X
  - dias_desde_ult_recep = X
- **Clasificación SQL antes del fix:** [etiqueta vieja]
- **Clasificación SQL después del fix:** [etiqueta nueva]
- **Lo que pasaba en la realidad:** [descripción comercial]
- **Por qué la regla falló:** [análisis técnico]
- **Comentarios adicionales:** [opcional]
```

---

### L9172 · INFLADOR GLOBOS
- **Sucursal:** MAGDALENA
- **Patrón:** **P1** (data corrupta)
- **Datos crudos:**
  - stock = 0
  - V90 = 185, R90 = 100,000,000,629 ⚠️
  - V_life = 586, R_life = 100,000,001,031, C_life = 100,000,000,445, T_life = 0
  - sell-through = 586 / 100B ≈ **0%**
- **Clasificación SQL:** ⛔ PÉRDIDA TOTAL (falso positivo)
- **Lo que pasaba en la realidad:** el SKU sí vendía, pero alguien escaneó un código de barras (`100000000451`) en el campo cantidad de la recepción `10254` (2026-05-11). Luego registró un consumo de `100,000,000,445` para "cancelarlo". El stock queda neto correcto pero el sell-through aparece como 0%.
- **Por qué la regla falló:** las reglas PÉRDIDA TOTAL / VENTAS CON PÉRDIDA usan `unds_recibidas_lifetime` directamente, sin sanidad de magnitud.
- **Mismo producto en Asamblea (data limpia):** 💎 EXITOSO PASADO — confirma que es un problema de data, no del producto.

### G7782DF
- **Sucursal:** MAGDALENA
- **Patrón:** **P1** (data corrupta — EAN-13 idéntico al código de barras del producto)
- **Datos crudos:**
  - Recepción con qty = **6,971,108,389,568** (un EAN-13 con 13 dígitos)
  - Consumo posterior con qty = **6,971,108,389,569** para cancelar
- **Clasificación SQL:** ⛔ PÉRDIDA TOTAL (falso positivo)
- **Detección automática:** buscar `quantity > 10000` en `reception_details` o `consumption_details`.

### FXT-2289 · ALFOMBRA GRANDE
- **Sucursal:** MAGDALENA
- **Patrón:** **P2** (mermas en denominador)
- **Datos crudos:**
  - stock = 0, V90 = 19, R90 = 25, C90 = 6
  - Vendió 19 + mermó 6 = 25 (vendió 100% de lo "vendible")
  - sell-through solo ventas: `19/25 = 76%` ← cae por debajo de 80%
  - sell-through neto (V+C): `25/25 = 100%`
- **Clasificación SQL antes del fix global (cascada 35d):** 💫 ROTACIÓN MEDIA "saludable, reponer normal"
- **Clasificación SQL hoy:** 💎 EXITOSO PASADO (gracias a sell-through neto)
- **Lo que pasaba en la realidad:** vendió todo lo vendible en 14 días. Las 6 mermas fueron salidas reales pero no comerciales.
- **Por qué la regla original fallaba:** la cascada 35d usaba `vend_35d / ult_recep_qty` sin descontar consumos del denominador.

### SKY ESPUMA DE AFEITAR 200ML (74914422901242)
- **Sucursal:** MAGDALENA
- **Patrón:** **P4** (EXITOSO mintiendo por velocidad lenta sostenida)
- **Datos crudos:**
  - stock = 0, V_life = 59, R_life = 60, sell-through = 98%
  - proy_mes = **5.45**, dsv = 9
  - Período activo: 8-11 meses vendiendo 5-7 unds/mes
- **Clasificación SQL antes del fix:** 🔥💎 EXITOSO ACTIVO "REPONER YA"
- **Clasificación SQL hoy:** 🐢 ROTACIÓN LENTA SANA "reponer cantidades chicas"
- **Lo que pasaba en la realidad:** vende constante pero lento — no urgente de reponer en cantidad grande.
- **Por qué la regla original fallaba:** EXITOSO ACTIVO miraba solo sell-through (98%) + recencia (dsv=9), no velocidad. Asumía que sell-through alto = velocidad alta.

### SKY ESPUMA DE AFEITAR 200ML (74914422901242) — Asamblea
- **Sucursal:** ASAMBLEA (mismo SKU, otra sucursal)
- **Patrón:** **P5** (agotado hace mucho)
- **Datos crudos:**
  - stock = 0, sell-through alto, dsv = **85** (>60)
- **Clasificación SQL antes del fix:** 💎 EXITOSO PASADO "evaluar antes de reponer"
- **Clasificación SQL hoy:** 💤 DEMANDA EXTINTA "no reponer"

### GEL DE AFEITAR 1L (74931689020221)
- **Sucursal:** MAGDALENA
- **Patrón:** **P3** + **P5** (cascada con lote antiguo + agotado hace mucho)
- **Datos crudos:**
  - stock = 0, V_life = 11, R_life = 12, sell-through neto = 100%
  - Un solo lote, recibido hace **362 días** (jun 2025)
  - Ventas concentradas: 5 en jun-jul 2025, gap de 7 meses, 5 más en feb-abr 2026
  - dsv = 61 (>60), proy_mes = 1.10/mes
- **Clasificación SQL antes del fix:** 💫 ROTACIÓN MEDIA "saludable, reponer normal" ⚠️
- **Clasificación SQL hoy:** 💤 DEMANDA EXTINTA
- **Lo que pasaba en la realidad:** producto prácticamente muerto. Vendía 1/mes en sus mejores tiempos.
- **Por qué la regla original fallaba:** la cascada 35d evaluaba el sell-through de los primeros 35 días del lote de hace 1 año (vendió 5/12 = 41.7%) → entraba a ROTACIÓN MEDIA.

### 300050845 · PORTA HUEVO
- **Sucursal:** MAGDALENA
- **Patrón:** **P5** (agotado hace mucho con sell-through alto)
- **Datos crudos:**
  - stock = 0, V90 = 11, R90 = 12, V_life = 44, R_life = 49
  - sell-through = 100%, proy_mes = 33.75
  - dsv = **77** (>60), edad = 125
- **Clasificación SQL antes del fix:** 💎 EXITOSO PASADO
- **Clasificación SQL hoy:** 💤 DEMANDA EXTINTA "no reponer"
- **Lo que pasaba en la realidad:** vendió bien hace 2+ meses, lleva 77 días sin venta.

### EP-9534 · Espátula
- **Sucursal:** MAGDALENA
- **Patrón:** **P3** (cascada con lote antiguo)
- **Datos crudos:**
  - stock = 0, V90 = 33, lote_total = 188 (todo el lote vendido lifetime)
  - vend_35d_post_recep = 27 → sell-through 35d = 14%
  - dsv = 62, edad = 225 días
- **Clasificación SQL antes del fix:** 💀 LENTO AGOTADO "<20% del lote en 35d, no priorizar"
- **Clasificación SQL hoy:** 💎 EXITOSO PASADO (o 💤 DEMANDA EXTINTA según dsv>60)
- **Lo que pasaba en la realidad:** vendió 188/188 lifetime — comercialmente fue exitoso en escala mayor de tiempo.

### KD-2605 · RECIPIENTE VIDRIO EN CAJA
- **Sucursal:** MAGDALENA
- **Patrón:** **P4** (rotación lenta sostenida pero con tendencia)
- **Datos crudos:**
  - stock = 0, V90 = 38, V_life = 87 (sobre R_life = 88)
  - vend_35d_post_recep = 8 → sell-through 35d = 9%
  - v_recent_45d = 34 vs v_old_45d = 4 (aceleración 8.5×!)
  - dsv = 29, edad = 344
- **Clasificación SQL anterior:** 🐢📈 LENTO QUE DESPERTÓ (regla especial)
- **Clasificación SQL hoy:** 🐢 ROTACIÓN LENTA SANA
- **Comentario:** caso interesante — el lote tardó casi un año en empezar a moverse fuerte. La regla LENTO QUE DESPERTÓ era rescate especial; ahora cae en una caja más simple sin perder señal.

### MS-2697 · TOMATODO POTRETTY 1L
- **Sucursal:** ambas (caso positivo, sin bug)
- **Patrón:** N/A — referencia de "todo funciona"
- **Datos Magdalena:** stock = 0, V90 = 109, R_life = 110, sell-through = 100%, proy_mes = 71.09, dsv = 27 → 🔥💎 EXITOSO ACTIVO ✅
- **Datos Asamblea:** stock = 0, V_life = 49, sell-through = 100%, dsv = 38 → 💎 EXITOSO PASADO ✅

### DA-180-1 · TERMO
- **Sucursal:** ASAMBLEA
- **Patrón:** N/A (caso límite con lote chico de 12 unds)
- **Datos crudos:**
  - stock = 0, V_life = 12, R_life = 12, sell-through = 100%
  - vend_35d_post_recep = 10 → sell-through 35d = 83%
  - proy_mes = 7.20 (velocidad baja)
  - dsv = 7
- **Clasificación SQL antes del fix:** 🔥💎 EXITOSO RÁPIDO (cascada 35d con sell-through 83%)
- **Clasificación SQL hoy:** 🐢 ROTACIÓN LENTA SANA (proy < 10, vendió todo)
- **Comentario:** producto con muy bajo volumen total. La nueva caja LENTA SANA refleja mejor el comportamiento: vendió todo pero a ritmo modesto, reponer poco.

---

### P8 · SKUs "exclusivos" de UNA sucursal (sin estar marcados como tales)
**Estado:** 🔍 descubierto en análisis sistemático D1. Sin acción todavía.

- **Síntoma:** producto en catálogo común que en la práctica solo vende en Magdalena o solo en Asamblea, nunca en ambas.
- **Posibles causas:** decisión de surtido por sucursal (algo OK), error de transferencia inicial (el lote llegó a una sola), problema de visibilidad (no se exhibe en la otra).
- **Detección SQL:**
  ```sql
  WITH ventas AS (
    SELECT dd.bsale_variant_id, d.bsale_office_id,
           SUM(CASE WHEN d.bsale_document_type_id IN (1,10,50,51,52,53) THEN dd.quantity ELSE 0 END) -
           SUM(CASE WHEN d.bsale_document_type_id IN (9,40,43) THEN dd.quantity ELSE 0 END) AS v
    FROM documents d JOIN document_details dd USING(bsale_document_id)
    WHERE d.is_active AND d.bsale_office_id IN (1,3)
      AND d.emission_date >= NOW() - INTERVAL '90 days'
    GROUP BY 1,2
  ), pivot AS (
    SELECT bsale_variant_id,
           SUM(CASE WHEN bsale_office_id=1 THEN v ELSE 0 END) v_mag,
           SUM(CASE WHEN bsale_office_id=3 THEN v ELSE 0 END) v_asa
    FROM ventas GROUP BY 1
  )
  SELECT v.display_code, p.name, pv.v_mag, pv.v_asa
  FROM pivot pv JOIN variants v USING(bsale_variant_id) JOIN products p USING(bsale_product_id)
  WHERE pv.v_mag + pv.v_asa >= 30 AND (pv.v_mag = 0 OR pv.v_asa = 0)
  ORDER BY pv.v_mag + pv.v_asa DESC;
  ```
- **Acción posible:** flagear como 🏪 EXCLUSIVO SUCURSAL en la clasificación, o cruzar con stock para sugerir transferencia.

---

### P9 · Ventas "fantasma": un único ticket distorsiona el promedio del SKU
**Estado:** 🔍 descubierto. Evaluar si crear caja nueva o usar como flag.

- **Síntoma:** SKU que vendió 60+ unidades pero **una sola venta** representa >50% del total. El promedio 90d dispara "ALTA ROTACIÓN" pero en realidad no rota — alguien compró al por mayor una vez.
- **Por qué importa:** ese pico distorsiona `proy_mes` y `velocidad`. Si comprás siguiendo la velocidad promedio, sobrestockás. El SKU no es "alta rotación", es "compra mayorista esporádica".
- **Ejemplos detectados (90d):**
  - `DT-2425TI` CALENTADOR · MAG · total=71, 1 ticket de 63 unds (89%)
  - `108-6DF` SET LAPICERO X6 · ASA · total=83, 1 ticket de 66 unds (80%)
  - `WA0216` JGT MASTICABLE · MAG · total=83, 1 ticket de 60 unds (72%)
  - `220198` SET MANICURE X120 · MAG · total=65, 1 ticket de 53 unds (82%)
- **Detección SQL:**
  ```sql
  WITH detalles AS (
    SELECT dd.bsale_variant_id, d.bsale_office_id, dd.bsale_document_id, dd.quantity
    FROM documents d JOIN document_details dd USING(bsale_document_id)
    WHERE d.is_active AND d.bsale_office_id IN (1,3)
      AND d.bsale_document_type_id IN (1,10,50,51,52,53)
      AND d.emission_date >= NOW() - INTERVAL '90 days'
      AND dd.quantity > 0
  )
  SELECT v.display_code, p.name,
         SUM(quantity) total, MAX(quantity) max_ticket, COUNT(*) n_tickets,
         ROUND(MAX(quantity)*100.0/SUM(quantity),1) pct_max
  FROM detalles JOIN variants v USING(bsale_variant_id) JOIN products p USING(bsale_product_id)
  GROUP BY v.display_code, p.name, bsale_office_id
  HAVING SUM(quantity) >= 20 AND MAX(quantity)*1.0/SUM(quantity) > 0.50
  ORDER BY max_ticket DESC;
  ```
- **Fix posible:** agregar regla en la cascada que detecte si `max_ticket_90d / V90 > 0.50` → etiqueta 🎯 VENTA MAYORISTA (no usar `proy_mes` como base de compra). Requiere nueva CTE.

---

## Tabla de equivalencias (rename 2026-06-06)

Para leer reportes históricos generados antes del rediseño de etiquetas:

| Nombre viejo | **Nombre actual** |
|---|---|
| 🌱 NUEVO | 🌱 PRODUCTO NUEVO — ESPERAR |
| ✅ TEMPORADA CERRADA | ✅ TEMPORADA CERRADA OK — RECOMPRAR PRÓXIMA CAMPAÑA |
| 📦 SOBRANTE DE CAMPAÑA | 📦 SALDO DE TEMPORADA — GUARDAR |
| ⛔ PÉRDIDA TOTAL | ⛔ PÉRDIDA DE STOCK — REVISAR CONTROL FÍSICO |
| ⚠️ VENTAS CON PÉRDIDA | ⚠️ VENDIÓ Y SE PERDIÓ — INVESTIGAR |
| 🔥💎 EXITOSO ACTIVO | 🔥 BESTSELLER ACTIVO — REPONER YA |
| 💎 EXITOSO PASADO | ⏸️ BESTSELLER EN PAUSA — EVALUAR |
| 💎 EXITOSO OLVIDADO | 💎 OPORTUNIDAD PERDIDA — REPONER YA |
| 🐢 ROTACIÓN LENTA SANA | 🐢 LENTO PERO CONSTANTE — REPONER POCO |
| 💤 DEMANDA EXTINTA | 💤 DEMANDA EXTINTA — NO REPONER |
| 🚨 QUIEBRE STOCK | 🚨 QUIEBRE DE BESTSELLER — COMPRAR YA |
| 👻 AGOTADO POTENCIAL ACTIVO | ✨ AGOTADO CON DEMANDA — REPONER |
| 💤 AGOTADO HISTÓRICO | 📉 EX-BESTSELLER ENFRIADO — EVALUAR |
| 🌿 PRODUCTO EMERGENTE | 🌿 PRODUCTO EMERGENTE — VIGILAR |
| 🪦 RESIDUO HISTÓRICO | 🪦 PRODUCTO MUERTO — DESCATALOGAR |
| 🪦 AGOTADO MARGINAL | 🪦 BAJO VOLUMEN AGOTADO — DESCATALOGAR |
| 👻 FALSO AGOTADO | 👻 AGOTADO NO PRIORITARIO |
| 🔄 REABASTECIDO RECIENTE | 🔄 STOCK RECIÉN LLEGADO — ESPERAR |
| 💀 MUERTO 90D | 💀 STOCK PARADO 90 DÍAS — LIQUIDAR |
| 👀 ALERTA VISUAL | 👀 STOCK BAJO QUIETO — VERIFICAR EN TIENDA |
| 🔄 REABASTECIDO ACTIVO | 🔄 LOTE NUEVO VENDIENDO BIEN |
| 🆕 RECIÉN REABASTECIDO | 🆕 RECIÉN REABASTECIDO — ESPERAR 1 SEMANA |
| 📉 RITMO PERDIDO | 📉 RITMO PERDIDO — EVALUAR ANTES DE REPONER |
| 💀 SALDO QUEMADO | 💀 LOTE FRENADO — LIQUIDAR, NO COMPRAR MÁS |
| 🔥📉 ALTA ROTACIÓN DECAYENDO | 🔥📉 ROTACIÓN BAJANDO — REPONER MENOS |
| 🔥 ALTA ROTACIÓN | 🔥 ALTA ROTACIÓN — PRIORIDAD DE COMPRA |
| 💫 ROTACIÓN ACTIVA | 💫 ROTACIÓN ACTIVA — MANTENER FLUJO |
| 🟢 INVENTARIO SANO | 🟢 INVENTARIO SANO — RITMO NORMAL |
| 🧊📉 EXCESO LIQUIDAR | 🧊📉 EXCESO + DEMANDA CAYENDO — PROMOCIONAR YA |
| 🧊 EXCESO DE INVENTARIO | 🧊 STOCK EXCESIVO — PROMOCIONAR |
| ⚠️ STOCK CRÍTICO | ⚠️ POCO STOCK CON DEMANDA — REPONER |
| 📈 BAJO VOLUMEN EN ALZA | 📈 VENDIENDO MÁS QUE ANTES — VIGILAR |
| 🐢 BAJA ROTACIÓN | 🐢 BAJA ROTACIÓN — PEDIR MENOS |
| ⚖️ EN ANÁLISIS | ⚖️ CASO ATÍPICO — REVISAR MANUAL |

Script de migración: `_beta/rename_clasif.py` (idempotente, ejecutar con `--dry` para previsualizar).

---

## P17 · Cobertura usaba velocidad lifetime del lote — insensible a cambios de ritmo

**Descubierto:** 2026-06-06 mientras explicaba al usuario cómo se calculaban los 45 días del guard P16. Pregunta del usuario: "¿desde la última recepción o la velocidad?".

### Síntoma
La columna `dias_cobertura` se calculaba con la fórmula:
```
dias_cobertura = stock / (unds_lote_total / dias_efectivos)
```
Es decir, velocidad PROMEDIO del lote completo. Eso significaba:
- SKUs **acelerando** (velocidad reciente > velocidad del lote) → cobertura sobreestimada → tarde en detectar como urgente.
- SKUs **desacelerando** (velocidad reciente < velocidad del lote) → cobertura subestimada → puede aparecer como urgente cuando en realidad tiene meses de stock.

### Caso testigo
TRAPEADOR GF-3602 MAGDALENA: lote llegó 08/04 con 25 unds. 60 días después tenía:
- Velocidad lifetime: 11/60 × 30 = 5.5/mes → cobertura 76d
- Velocidad últimos 30d: 7 unds → 7/mes → cobertura 60d (más cercana a la realidad)
- En este caso ambas > 45 → la clasificación final no cambia. Pero el principio es el problema.

### Solución aplicada
Agregada columna `dias_cobertura_reciente` en `metricas_reciente` que prioriza velocidad de los últimos 30d:
```sql
CASE
    WHEN m.unds_lote_total <= 0 THEN m.dias_cobertura    -- fallback lifetime
    WHEN (m.stock + m.reservado) = 0 THEN 0
    WHEN m.unds_vendidas_30d > 0 AND m.dias_con_stock_30d > 0
        THEN stock / (unds_vendidas_30d / dias_con_stock_30d)
    ELSE m.dias_cobertura                                -- fallback lifetime
END AS dias_cobertura_reciente
```

En la cascada de clasificación (CASE final), reemplazado `dias_cobertura` → `dias_cobertura_reciente` (12 ocurrencias por archivo).

Se mantiene `dias_cobertura` lifetime en la CTE `metricas` y en la CTE `transferencias` (donde detectar excedente sostenido es lo correcto).

### Resultado
- 3 SKU distribuciones cambian (algunos migran a otras cajas según si aceleran o desaceleran)
- TRAPEADOR GF-3602 sigue en 🐢 BAJA ROTACIÓN en ambas sucursales ✅
- ESMALTE-J01 sigue en 💀 LOTE FRENADO ✅
- 0 huérfanos en las 3 matrices

Aplicado vía `_beta/fix_p17_cobertura_reciente.py` (idempotente, identifica el rango de la cascada y solo reemplaza dentro de ese rango).

---

## P16 · "📈 VENDIENDO MÁS QUE ANTES" no chequeaba cobertura — clasificaba mal SKUs con stock para meses

**Descubierto:** 2026-06-06 — caso TRAPEADOR GF-3602 MAGDALENA (stock 14, proy 5.2/mes, cob ≈ 80 días).

### Síntoma
SKU con tendencia positiva (ventas recientes > ventas viejas) pero **cobertura alta** caía en la caja `📈 VENDIENDO MÁS QUE ANTES — VIGILAR` con instrucción "observar, no liquidar". Engañoso: el usuario lee "vigilar" y piensa "mantener al ritmo"; en realidad ya tiene stock para 80+ días y NO debería reponer.

### Caso testigo
TRAPEADOR GF-3602 — lote llegó 08/04/2026, vendió 11/25 en 60 días = 18% sell-through. Magdalena tenía 14 unds para vender al ritmo de 5.2/mes = **2.7 meses de cobertura**. Sin embargo aparecía como "VENDIENDO MÁS QUE ANTES" porque v_recent_45d (7 unds) > v_old_45d (4 unds) × 1.5.

### Causa raíz
La regla original NO chequeaba `dias_cobertura`:
```sql
WHEN proy_mes < umbral
     AND v_recent_45d > 0
     AND tendencia_creciente
     THEN '📈 VENDIENDO MÁS QUE ANTES'
```

Una tendencia positiva puede ser informativa, pero **operativamente no importa si ya tenés stock para meses** — lo que necesitás saber es "no comprar más".

### Solución aplicada
Agregado guard `dias_cobertura ≤ 45d` a la regla en los 3 SQL (04, 04b, 05):
```sql
WHEN proy_mes < umbral
     AND v_recent_45d > 0
     AND COALESCE(dias_cobertura, 9999) <= 45   -- ★ FIX P16
     AND tendencia_creciente
     THEN '📈 VENDIENDO MÁS QUE ANTES'
```

Si cobertura > 45d, el SKU cae al siguiente WHEN (🐢 BAJA ROTACIÓN — PEDIR MENOS) que es operativamente correcto: tiene stock + vende poco = bajar pedido.

La tendencia positiva queda preservada en la columna `Tendencia = 📈 Creciendo` (separada de la clasificación) — la info no se pierde, solo deja de gobernar la acción.

### Resultado
| Caja | Antes | Después |
|---|---:|---:|
| 📈 VENDIENDO MÁS QUE ANTES | 62 | **19** (-43) |
| 🐢 BAJA ROTACIÓN | 152 | **203** (+51) |

ESMALTE-J01 y caso testigo TRAPEADOR GF-3602 → ambas sucursales ahora en 🐢 BAJA ROTACIÓN. 0 huérfanos en las 3 matrices.

---

## P15 · Lote viejo con velocidad lifetime alta pero reciente ≈ 0 — "💀 LOTE FRENADO" (antes SALDO QUEMADO)

**Descubierto:** 2026-06-06 — caso ESMALTE-J01 (ESMALTE JARUSA) MAGDALENA.

### Síntoma
SKU clasificado como **🔥📉 ALTA ROTACIÓN DECAYENDO** con instrucción "reducir reposición — usar Vel 30d". Pero la realidad: lote llegó hace 9 meses, vendió fuerte los primeros 4 meses (jun-sep 2025), y desde octubre 2025 está **prácticamente parado** (29 unds en 6 meses = ~5/mes). Stock = 13 → ~3 meses de cobertura al ritmo real.

### Por qué se clasifica mal
La fórmula de `proy_mes` (en CTE `metricas`, `04b:444`):
```sql
proy_mes = (unds_lote_total / dias_efectivos) × 30
```
Es un PROMEDIO HISTÓRICO del lote completo. Para ESMALTE-J01: 128/80 × 30 = **48 unds/mes** (inflado por la temporada inicial). La velocidad REAL de los últimos 30 días es ~1 unds/mes.

Como `proy_mes ≥ 30` y la tendencia es decayendo (`v_recent_45d < v_old_45d × 0.7`), entra en ALTA ROT DECAYENDO. Pero "decayendo" sugiere que sigue rotando — y la realidad es que **ya cayó**.

### Caso testigo (datos reales)
| | Métrica |
|---|---|
| Stock | 13 |
| Vend Lote Total | 128 (9 meses) |
| Velocidad lifetime | 48/mes |
| Velocidad últimos 30d | ~1/mes (caída -98%) |
| DSV | 1 día (vendió 1 unidad ayer) |
| Edad del lote | 278 días |

### Solución aplicada · Nueva regla en SQL

Agregada antes de "ALTA ROTACIÓN DECAYENDO" en los 3 SQL (04, 04b, 05):
```sql
WHEN stock_disponible >= 5             -- saldo SIGNIFICATIVO (no agonía final)
     AND proy_mes >= 10                -- tuvo rotación histórica
     AND COALESCE(proy_30d_reciente, 0) < 5  -- velocidad REAL casi nula
     AND COALESCE(edad_dias, 0) >= 90  -- lote suficientemente viejo
     THEN '💀 SALDO QUEMADO: lote casi sin movimiento reciente — liquidar saldo (no comprar más)'
```

### Resultado de la aplicación
- **11 SKUs** caen en `💀 SALDO QUEMADO` en cada matriz
- Casos típicos capturados: PARAGUA (estacional invierno), SET VELA AROMATICA, CORREA MASCOTA, PLATO TENDIDO, MINI DELINEADOR (stk=52, dsv=4), BIZCOCHO COSTA CANCUN (estacional), SET PULSERA LUCES X50 (campaña), ESMALTE JARUSA ★, BYWIN TOALLITAS MR.POTATO (stk=46)
- 0 huérfanos · ESMALTE-J01 MAGDALENA: ANTES `🔥📉 ALTA ROTACIÓN DECAYENDO` → AHORA `💀 SALDO QUEMADO` ✅

### Patrón general (cuándo aplicará)
Cualquier SKU estacional/campaña con lote viejo:
- esmaltes/protector solar (verano)
- paraguas/abrigos (invierno)
- cuadernos/lapiceros (campaña escolar feb-marzo)
- juguetes específicos (navidad)
- chocolates corazón (febrero)
- snacks limited edition

Estos productos compran fuerte una vez, venden fuerte 1-3 meses, y dejan saldo. Antes el sistema los recomendaba "reponer" — ahora dice "liquidar".

### Discrepancia secundaria detectada (sin acción)
El reporte BSale del usuario mostraba ventas a S/ 0.00 desde 17/12/2025 que en mi BD están con precio S/ 2.90. Los tickets SÍ existen (verificado: 51262, 123819 con totales reales), pero el reporte BSale parece estar mostrando otra columna (¿costo, valor en libros del kardex?). NO afecta la clasificación porque mi BD tiene los precios correctos.

---

## P14 · `variant_costs.effective_cost = 0` infla el margen calculado

**Descubierto:** 2026-06-06 mientras investigábamos una supuesta "caída de margen de -14 pp" reportada por `/analytics/ticket-anatomy`.

### Síntoma
El endpoint reporta margen aparente que cae de 64.8% (abr) a 51.0% (may) — pareciera una crisis de mix o de costos. **Es 100% un artefacto.**

### Causa raíz
- **3,076 de ~3,847 variantes (80% del catálogo)** tienen `cost_source = 'NONE'` y `effective_cost = 0` en la tabla `variant_costs`
- El cálculo de margen `(ventas - costo) / ventas * 100` para esos SKUs da **100%** (porque costo=0)
- Si esos SKUs cambian de peso entre dos períodos, el margen-promedio-ponderado se mueve sin que haya cambiado nada operativo

### Magnitud del falso positivo
| Métrica | Aparente | Real (excluyendo cost=0) |
|---|---:|---:|
| Margen abril | 64.8% | **37.7%** |
| Margen mayo | 51.0% | **35.3%** |
| Δ | -14 pp | **-2.4 pp** |

### Tamaño del problema operativo
- **955 SKUs** vendieron en 90d sin tener costo registrado → **S/ 457,189** en ventas con margen no calculable
- Top 100 = 47.5% de esa cifra (Pareto puro — cargar 100 SKUs resuelve la mitad)
- Bestsellers afectados: CUAD SCOOL S/88H, CUADERNNO JUSTUS, PAPEL FOTOC MILLENIUM, TOALLITA HUMEDA BYWIN, ONE CARE pasta dental, etc.

### SQL para detectar
```sql
SELECT v.code, vpf.product_name,
       SUM(dd.total_amount) AS ventas_90d
FROM document_details dd
JOIN documents doc ON doc.bsale_document_id = dd.bsale_document_id
JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
JOIN v_products_full vpf ON vpf.bsale_product_id = v.bsale_product_id
LEFT JOIN variant_costs vc ON vc.bsale_variant_id = dd.bsale_variant_id
WHERE (doc.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 90
  AND COALESCE(doc.is_credit_note, FALSE) = FALSE
  AND NOT dd.is_gratuity
  AND (vc.effective_cost = 0 OR vc.effective_cost IS NULL)
GROUP BY v.code, vpf.product_name
ORDER BY ventas_90d DESC;
```

### Acción aplicada
- Excel `backend_hudec/costos_pendientes_priorizados.xlsx` generado con los 955 SKUs ordenados por venta 90d (columna `Costo (a cargar)` en amarillo, columna `Margen estimado %` con fórmula auto-calculada al llenar el costo)
- **Trabajo operativo (usuario)**: cargar costos en BSale empezando por el top 50-100 (cubre 35-48% de la venta)

### Fix técnico pendiente (cuando el usuario lo solicite)
1. `_period_metrics()` en `app/routers/analytics.py`: separar `margen_real` (sobre `cost > 0`) de `margen_aparente` (todo), devolver `cobertura_costo_pct`
2. `AnatomyCard.tsx`: mostrar `margen_real` con disclaimer si cobertura < 70%
3. `/analytics/kpis`: el `stock_valorizado` actualmente está MASIVAMENTE sub-valuado por el mismo motivo (multiplica stock × 0). Fix igual: excluir cost=0 o usar último precio de venta como proxy

### Por qué no se aplica el fix YA
Decisión del usuario (2026-06-06): "recién actualizaré los costos de los productos". Una vez cargados, el problema se auto-resuelve al siguiente sync (`variant_costs.synced_at`). Aplicar fixes técnicos sobre data que pronto será correcta es esfuerzo malgastado.

---

## Próximos pasos / patrones por explorar

### Análisis ya ejecutados (en este `.md`)
- ✅ D1 — divergencia entre sucursales → P8
- ✅ D2 — sell-through > 110% → **0 casos encontrados** (la BD está limpia en este aspecto)
- ✅ D3 — tickets gigantes → P9

### Pendientes de análisis (cuando el usuario quiera)
- [ ] **D4** Co-ocurrencia / cross-sell: qué productos se venden juntos en el mismo ticket (combos detectables)
- [ ] **D5** Devoluciones excesivas (`is_credit_note=true`) por SKU
- [ ] **D6** Estacionalidad descubierta: SKUs que solo venden en ciertos meses (no marcados como `seasonal_departments`)
- [ ] **D7** Patrones por día de la semana (SKU "solo viernes/sábado")
- [ ] **D8** Velocidad inicial vs sostenida: "moda" (pico 30d → silencio) vs "staple" (constante)
- [ ] **D9** Stock con ventas históricas pero zero recent (zombies): capital atascado
- [ ] **D10** Precio promedio drift: SKUs cuyo precio promedio cambió mucho mes a mes
- [ ] **D11** SKUs sin recepción en BD pero con ventas (stock por ajuste manual / error de carga)
- [ ] **D12** Gratuidades acumuladas (`is_gratuity = true`): costo invisible

### Decisiones pendientes
- [ ] **P1** (data corrupta): implementar guard en harvester (`harvester/sync_*.py`) que cape o rechace `quantity > 10⁴`.
- [ ] **P7** (Decayendo en agotados): decidir si "Decayendo" debe mutar a "Agotado" cuando stock = 0.
- [ ] **P8** decidir si flageamos exclusivos de sucursal en la clasificación.
- [ ] **P9** decidir si crear caja nueva 🎯 VENTA MAYORISTA o solo flag adicional.

---

## Convenciones para nuevos hallazgos

1. **Antes de agregar un caso individual**, verificar si encaja en un patrón existente (sumar al patrón) o si es un patrón nuevo (agregar nuevo `P#` al índice).
2. **Siempre incluir números reales** sacados de una query a la BD — no estimaciones.
3. **Documentar la versión del SQL** cuando se observó el bug (commit hash o fecha) si es posible.
4. **Vincular el patrón al fix** si ya se aplicó (sección del SQL, regla específica).
