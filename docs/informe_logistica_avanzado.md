# 📊 Informe Técnico: Análisis Logístico Estadístico Avanzado (Kawii V2.0)

Este documento sirve como manual y hoja de ruta para comprender todas las métricas, algoritmos y filtros que está procesando actualmente la base de datos a través de la consulta maestra `estadistica_logistica_avanzada.sql`.

---

## 🎯 Objetivo de la Consulta
Transformar los datos transaccionales brutos de ventas y stock en **información logística predictiva**. El objetivo es avisarte cuándo un producto se va a agotar, si sus ventas son estables o riesgosas, y qué porcentaje de tu inversión inicial ya has recuperado.

---

## 🧮 1. Diccionario de Métricas (Las Columnas Exportadas)

### `Días Reales con Stock`
* **¿Qué mide?** La cantidad exacta de tiempo que el producto estuvo en la vitrina disponible para que el cliente lo compre.
* **El Algoritmo:** Cruza el historial diario (`stock_history`) para contar los días con stock mayor a cero (Gaps & Islands). Si un producto se agotó por 5 días a mitad de semana, la fórmula **no cuenta** esos 5 días. Esto evita que tu promedio de ventas salga artificialmente bajo.

### `Ritmo de Venta Mensual Proyectado`
* **¿Qué mide?** La velocidad pura de venta, estandarizada a una ventana de 30 días.
* **El Algoritmo:** `(Ventas Totales / Días Reales con Stock) * 30`. Si vendiste 5 jabones en los únicos 15 días que tuviste stock, tu ritmo real es de 10 jabones al mes.

### `% Tasa de Éxito (Sell-Through)`
* **¿Qué mide?** La efectividad de tu compra. ¿Qué porcentaje del lote que recibiste ya se vendió?
* **El Algoritmo:** `(Ventas Totales / Cantidad Total Recibida) * 100`. 
* **Regla Inteligente de Ceros:** Si el producto no tuvo ingresos en el periodo evaluado (es inventario antiguo), el sistema calcula matemáticamente tu *Inventario Inicial Estimado* sumando las ventas más el stock actual, para así darte un porcentaje preciso sin lanzar error de "división por cero".

### `Variabilidad Diaria (Desviación Poblacional)` y `Perfil de Riesgo`
* **¿Qué mide?** Si el producto es estable o es una montaña rusa impredecible.
* **El Algoritmo:** Para esto creamos un *Calendario Virtual* que rellena con un "0" los días en que no vendiste nada. Luego aplica la fórmula estadística `STDDEV_POP()`.
* **Perfil de Riesgo:** 
  * **"ALTO RIESGO"**: Sus ventas saltan bruscamente (ej. 30 ventas un día, cero ventas los 6 días siguientes).
  * **"ESTABLE"**: Vende de forma constante a lo largo de la semana.

### `Días de Cobertura Restante` (Days of Supply)
* **¿Qué mide?** La fecha de caducidad teórica de tu estante. ¿En cuántos días te quedas sin stock?
* **El Algoritmo:** `Stock Actual / Promedio Diario de Ventas`.

### `Clasificación (Semáforo Híbrido)`
Cruza el Ritmo de Venta y la Cobertura para emitir una alerta ejecutiva:
* 🟢 **INVENTARIO SANO:** Tienes para más de 45 días y vende bien.
* ⚡ **MEDIA ROTACIÓN:** Tienes entre 30 y 45 días de stock.
* 🔥 **ALTA ROTACIÓN:** Tienes menos de 30 días de stock. ¡Atención!
* ⚠️ **CRÍTICO pero BAJA ROTACIÓN:** Te estás quedando sin stock, pero es un producto estancado (ritmo < 10 al mes).
* 🐢 **BAJA ROTACIÓN:** Ritmo mensual menor a 10.

---

## 🧹 2. Limpieza de Datos (Los Filtros Aplicados)

Para que tu tabla final salga impecable y lista para gerencia, el código tiene "escudos" de limpieza:

1. **Filtro de "Productos Fantasma":** (`WHERE cantidad_recibida_lote > 0`). Elimina aquellos productos que tienen cero stock, cero ventas y cero ingresos.
2. **Exclusión de Almacenes Inactivos:** Se excluye totalmente el Almacén 4 (`bsale_office_id NOT IN (4)`).
3. **Filtros de Departamentos:** Excluye dinámicamente los departamentos 11 y 12.
4. **Ventas Puras:** Solo cuenta documentos activos y excluye notas de crédito (`is_active = TRUE AND is_credit_note = FALSE`).
