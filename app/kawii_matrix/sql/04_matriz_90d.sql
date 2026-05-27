-- =============================================================
-- MATRIZ 90D — Foto pura del "ahora" (sin contexto histórico)
-- =============================================================
-- Ventana operativa: 90 días.
-- Velocidad: del LOTE ACTUAL (desde última recepción), con piso 7d.
-- Sucursales: 1 (Magdalena) y 3 (Asamblea).
-- =============================================================
WITH params AS (
    SELECT NOW()                              AS ahora,
        NOW() - INTERVAL '90 days'           AS fecha_corte,
        :sucursales_objetivo::int[]          AS sucursales_objetivo,
        :tipos_venta::int[]                  AS tipos_venta,
        :tipos_devolucion::int[]             AS tipos_devolucion,
        7                                    AS piso_dias_lote
),
ventas_diarias AS (
    SELECT
        d.bsale_office_id,
        dd.bsale_variant_id,
        DATE(d.emission_date) AS fecha,
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_venta) THEN dd.quantity ELSE 0 END) AS qty_venta,
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_devolucion) THEN dd.quantity ELSE 0 END) AS qty_devol
    FROM documents d
    JOIN document_details dd USING (bsale_document_id)
    CROSS JOIN params p
    WHERE d.is_active
      AND d.emission_date >= p.fecha_corte
      AND d.bsale_office_id = ANY(p.sucursales_objetivo)
      AND d.bsale_document_type_id = ANY(p.tipos_venta || p.tipos_devolucion)
    GROUP BY 1, 2, 3
),
ventas_90d AS (
    SELECT bsale_office_id, bsale_variant_id,
        SUM(qty_venta - qty_devol) AS unds_vendidas,
        MAX(fecha) FILTER (WHERE qty_venta - qty_devol > 0) AS ultima_venta,
        COUNT(DISTINCT fecha) FILTER (WHERE qty_venta - qty_devol > 0) AS dias_con_venta
    FROM ventas_diarias
    GROUP BY 1, 2
    HAVING SUM(qty_venta - qty_devol) > 0
),
-- ★ Ventas separadas en dos sub-periodos para calcular tendencia:
--    v_recent_45d: últimos 45 días
--    v_old_45d:    los 45 días anteriores (45-90 días atrás)
--    Permite detectar productos creciendo/decayendo dentro de la ventana 90d.
ventas_tendencia AS (
    SELECT vd.bsale_office_id, vd.bsale_variant_id,
        SUM(CASE WHEN vd.fecha >= (p.ahora - INTERVAL '45 days')::date
                 THEN vd.qty_venta - vd.qty_devol ELSE 0 END) AS v_recent_45d,
        SUM(CASE WHEN vd.fecha < (p.ahora - INTERVAL '45 days')::date
                 THEN vd.qty_venta - vd.qty_devol ELSE 0 END) AS v_old_45d
    FROM ventas_diarias vd CROSS JOIN params p
    GROUP BY 1, 2
),
-- ★ Ventas en los ÚLTIMOS 30 DÍAS naturales.
--    Base para "Vel últimos 30d" — refleja el comportamiento RECIENTE del SKU,
--    útil para reposición cuando el producto está creciendo/decayendo.
ventas_30d AS (
    SELECT vd.bsale_office_id, vd.bsale_variant_id,
        SUM(vd.qty_venta - vd.qty_devol) AS unds_vendidas_30d
    FROM ventas_diarias vd CROSS JOIN params p
    WHERE vd.fecha >= (p.ahora - INTERVAL '30 days')::date
    GROUP BY 1, 2
),
stock_sucursal AS (
    SELECT bsale_office_id, bsale_variant_id,
        quantity_available AS stock_disponible,
        quantity_reserved  AS stock_reservado
    FROM stock_levels sl CROSS JOIN params p
    WHERE sl.bsale_office_id = ANY(p.sucursales_objetivo)
),
recep_90d AS (
    SELECT r.bsale_office_id, rd.bsale_variant_id,
        MIN(r.admission_date) AS primera_recep_90d,
        MAX(r.admission_date) AS ultima_recep_90d,
        SUM(rd.quantity)      AS unds_recibidas_90d,
        COUNT(DISTINCT r.bsale_reception_id) AS num_recepciones_90d
    FROM receptions r
    JOIN reception_details rd USING (bsale_reception_id)
    CROSS JOIN params p
    WHERE r.bsale_office_id = ANY(p.sucursales_objetivo)
      AND r.admission_date >= p.fecha_corte
    GROUP BY 1, 2
),
primera_recep_total AS (
    SELECT r.bsale_office_id, rd.bsale_variant_id,
        MIN(r.admission_date) AS primera_recepcion,
        MAX(r.admission_date) AS ultima_recepcion,
        SUM(rd.quantity)      AS unds_recibidas_lifetime  -- total recibido en toda la vida del SKU
    FROM receptions r
    JOIN reception_details rd USING (bsale_reception_id)
    CROSS JOIN params p
    WHERE r.bsale_office_id = ANY(p.sucursales_objetivo)
    GROUP BY 1, 2
),
-- ★ Consumos LIFETIME (mermas/transferencias internas/regalos).
--    NO son ventas pero SÍ son salidas de inventario. Usado en la regla
--    "💎 EXITOSO PASADO" para calcular el verdadero sell-through:
--    (ventas + consumos) / recibido. Caso XK3179: vendió 4 + consumió 2 de 6 = 100%.
consumos_lifetime AS (
    SELECT c.bsale_office_id, cd.bsale_variant_id,
        SUM(cd.quantity) AS unds_consumidas_lifetime
    FROM consumptions c
    JOIN consumption_details cd USING (bsale_consumption_id)
    CROSS JOIN params p
    WHERE c.bsale_office_id = ANY(p.sucursales_objetivo)
    GROUP BY 1, 2
),
-- ★ Traslados de SALIDA LIFETIME (IDs configurables vía :tipos_traslado).
--    En COYA el tipo 53 = TRASLADO INTERNO (el tipo 37 no existe en este sistema).
--    Cuando una sucursal envía mercadería a otra, sale del inventario pero
--    NO se vende. Antes el SQL contaba esto como "recibido sin vender", inflando
--    el sell-through aparente.
--    Casos: 252590 (recibió 96, trasladó 48, vendió 48 → 100% real).
traslados_lifetime AS (
    SELECT d.bsale_office_id, dd.bsale_variant_id,
        SUM(dd.quantity) AS unds_trasladadas_lifetime
    FROM documents d
    JOIN document_details dd USING (bsale_document_id)
    CROSS JOIN params p
    WHERE d.is_active
      AND d.bsale_office_id = ANY(p.sucursales_objetivo)
      AND d.bsale_document_type_id = ANY(:tipos_traslado::int[])
    GROUP BY 1, 2
),
-- Ventas posteriores a la última recepción, LIMITADAS a 90d
-- (compat: se mantiene "Vend Post Recep" pero ya no se usa para velocidad)
ventas_post_recep AS (
    SELECT
        vd.bsale_office_id, vd.bsale_variant_id,
        SUM(vd.qty_venta - vd.qty_devol) AS unds_post_recep,
        MAX(vd.fecha) FILTER (WHERE vd.qty_venta - vd.qty_devol > 0) AS ult_venta_post_recep
    FROM ventas_diarias vd
    JOIN primera_recep_total prt
      ON prt.bsale_office_id = vd.bsale_office_id
     AND prt.bsale_variant_id = vd.bsale_variant_id
    WHERE vd.fecha >= prt.ultima_recepcion::date
    GROUP BY 1, 2
),
-- ★ Ventas LIFETIME del SKU (TODAS sus ventas, sin filtro alguno).
--    Usado para la regla 💎 PRODUCTO EXITOSO AGOTADO.
ventas_total_sku AS (
    SELECT d.bsale_office_id, dd.bsale_variant_id,
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_venta) THEN dd.quantity ELSE 0 END) -
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_devolucion) THEN dd.quantity ELSE 0 END) AS unds_vendidas_lifetime,
        MAX(d.emission_date::date) FILTER (WHERE d.bsale_document_type_id = ANY(p.tipos_venta)) AS ult_venta_lifetime
    FROM documents d
    JOIN document_details dd USING (bsale_document_id)
    CROSS JOIN params p
    WHERE d.is_active
      AND d.bsale_office_id = ANY(p.sucursales_objetivo)
      AND d.bsale_document_type_id = ANY(p.tipos_venta || p.tipos_devolucion)
    GROUP BY 1, 2
),
-- ★ Ventas del LOTE COMPLETO (ciclo actual del producto).
--    El ciclo inicia en:
--      - primera_recep_90d (si hubo recepciones en 90d → trata lotes múltiples cercanos como uno)
--      - ultima_recepcion lifetime (si no hubo recepciones en 90d → lote viejo)
--    Resuelve casos: Aloe Vera (2 lotes cercanos), B1721 (lote viejo).
ventas_lote_total AS (
    SELECT d.bsale_office_id, dd.bsale_variant_id,
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_venta) THEN dd.quantity ELSE 0 END) -
        SUM(CASE WHEN d.bsale_document_type_id = ANY(p.tipos_devolucion) THEN dd.quantity ELSE 0 END) AS unds_lote_total,
        MAX(d.emission_date::date) FILTER (WHERE d.bsale_document_type_id = ANY(p.tipos_venta)) AS ult_venta_lote,
        MIN(d.emission_date::date) FILTER (WHERE d.bsale_document_type_id = ANY(p.tipos_venta)) AS pri_venta_lote,
        COUNT(DISTINCT d.emission_date::date) FILTER (WHERE d.bsale_document_type_id = ANY(p.tipos_venta)) AS dias_con_venta_lote
    FROM documents d
    JOIN document_details dd USING (bsale_document_id)
    CROSS JOIN params p
    JOIN primera_recep_total prt
      ON prt.bsale_office_id = d.bsale_office_id
     AND prt.bsale_variant_id = dd.bsale_variant_id
    LEFT JOIN recep_90d r90
      ON r90.bsale_office_id = d.bsale_office_id
     AND r90.bsale_variant_id = dd.bsale_variant_id
    WHERE d.is_active
      AND d.bsale_office_id = ANY(p.sucursales_objetivo)
      AND d.bsale_document_type_id = ANY(p.tipos_venta || p.tipos_devolucion)
      AND d.emission_date >= COALESCE(r90.primera_recep_90d, prt.ultima_recepcion)
    GROUP BY 1, 2
),
jerarquia AS (
    SELECT p.bsale_product_id, p.name AS product_name,
        d.id AS department_id, d.name AS department,
        c.id AS category_id, c.name AS category,
        s.id AS subcategory_id, s.name AS subcategory
    FROM products p
    LEFT JOIN product_types pt ON p.bsale_product_type_id = pt.bsale_product_type_id
    LEFT JOIN subcategories s ON s.id = COALESCE(p.subcategory_id, pt.subcategory_id)
    LEFT JOIN categories c ON c.id = s.category_id
    LEFT JOIN departments d ON d.id = c.department_id
    WHERE p.is_active
),
base AS (
    SELECT bsale_office_id, bsale_variant_id FROM stock_sucursal WHERE stock_disponible > 0
    UNION SELECT bsale_office_id, bsale_variant_id FROM ventas_90d
    UNION SELECT bsale_office_id, bsale_variant_id FROM recep_90d
),
radiografia AS (
    SELECT b.bsale_office_id, b.bsale_variant_id,
        o.name AS sucursal, v.display_code,
        j.product_name, j.department, j.category, j.subcategory,
        COALESCE(v90.unds_vendidas, 0)::numeric    AS unds_vendidas,
        COALESCE(ss.stock_disponible, 0)::numeric  AS stock_disponible,
        COALESCE(ss.stock_reservado, 0)::numeric   AS stock_reservado,
        COALESCE(v90.dias_con_venta, 0)            AS dias_con_ventas,
        v90.ultima_venta,
        COALESCE(r90.unds_recibidas_90d, 0)::numeric AS unds_recibidas_90d,
        r90.primera_recep_90d, r90.ultima_recep_90d,
        prt.primera_recepcion, prt.ultima_recepcion,
        COALESCE(prt.unds_recibidas_lifetime, 0)::numeric AS unds_recibidas_lifetime,
        COALESCE(vts.unds_vendidas_lifetime, 0)::numeric  AS unds_vendidas_lifetime,
        vts.ult_venta_lifetime,
        COALESCE(vpr.unds_post_recep, 0)::numeric  AS unds_post_recep,
        vpr.ult_venta_post_recep,
        -- ★ NUEVO: datos del LOTE COMPLETO (sin filtro 90d)
        COALESCE(vlt.unds_lote_total, 0)::numeric  AS unds_lote_total,
        vlt.ult_venta_lote,
        vlt.pri_venta_lote,
        COALESCE(vlt.dias_con_venta_lote, 0)       AS dias_con_venta_lote,
        -- ★ Tendencia: ventas en sub-períodos 45d
        COALESCE(vt.v_recent_45d, 0)::numeric      AS v_recent_45d,
        COALESCE(vt.v_old_45d, 0)::numeric         AS v_old_45d,
        -- ★ Ventas últimos 30d naturales (para velocidad reciente)
        COALESCE(v30.unds_vendidas_30d, 0)::numeric AS unds_vendidas_30d,
        -- ★ Consumos LIFETIME (mermas — para sell-through real)
        COALESCE(cl.unds_consumidas_lifetime, 0)::numeric AS unds_consumidas_lifetime,
        -- ★ Traslados de salida LIFETIME (tipo 53 en COYA — para sell-through real)
        COALESCE(tl.unds_trasladadas_lifetime, 0)::numeric AS unds_trasladadas_lifetime
    FROM base b
    JOIN offices o   ON o.bsale_office_id = b.bsale_office_id
    JOIN variants v  ON v.bsale_variant_id = b.bsale_variant_id AND v.is_active
    JOIN jerarquia j ON j.bsale_product_id = v.bsale_product_id
    LEFT JOIN stock_sucursal  ss  ON ss.bsale_office_id = b.bsale_office_id AND ss.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN ventas_90d      v90 ON v90.bsale_office_id = b.bsale_office_id AND v90.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN recep_90d       r90 ON r90.bsale_office_id = b.bsale_office_id AND r90.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN primera_recep_total prt ON prt.bsale_office_id = b.bsale_office_id AND prt.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN ventas_post_recep vpr ON vpr.bsale_office_id = b.bsale_office_id AND vpr.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN ventas_lote_total vlt ON vlt.bsale_office_id = b.bsale_office_id AND vlt.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN ventas_total_sku  vts ON vts.bsale_office_id = b.bsale_office_id AND vts.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN ventas_tendencia  vt  ON vt.bsale_office_id  = b.bsale_office_id AND vt.bsale_variant_id  = b.bsale_variant_id
    LEFT JOIN ventas_30d        v30 ON v30.bsale_office_id = b.bsale_office_id AND v30.bsale_variant_id = b.bsale_variant_id
    LEFT JOIN consumos_lifetime cl  ON cl.bsale_office_id  = b.bsale_office_id AND cl.bsale_variant_id  = b.bsale_variant_id
    LEFT JOIN traslados_lifetime tl ON tl.bsale_office_id  = b.bsale_office_id AND tl.bsale_variant_id  = b.bsale_variant_id
    WHERE (j.department_id IS NULL OR NOT (j.department_id = ANY(:excluded_departments::int[])))
      AND (j.category_id IS NULL OR NOT (j.category_id = ANY(:excluded_categories::int[])))
),
calc AS (
    SELECT r.*,
        (r.unds_vendidas + r.stock_disponible) AS tdpv,
        CASE WHEN r.ultima_venta IS NOT NULL
             THEN DATE_PART('day', p.ahora - r.ultima_venta)::numeric
             ELSE NULL END AS dias_sin_venta_90d,
        CASE WHEN r.primera_recepcion IS NOT NULL
             THEN DATE_PART('day', p.ahora - r.primera_recepcion)::int
             ELSE NULL END AS edad_dias,
        CASE WHEN r.ultima_recepcion IS NOT NULL
             THEN DATE_PART('day', p.ahora - r.ultima_recepcion)::int
             ELSE NULL END AS dias_desde_ultima_recep,
        -- ★ dias_efectivos del CICLO ACTUAL.
        --    Inicio del ciclo: primera_recep_90d si hubo recepción en 90d, sino ultima_recepcion lifetime.
        --    Resuelve: Aloe Vera (2 lotes en 8 días = un solo ciclo de 9d, no de 1d).
        GREATEST(p.piso_dias_lote::numeric,
            CASE
                WHEN r.stock_disponible = 0
                     AND COALESCE(r.primera_recep_90d, r.ultima_recepcion) IS NOT NULL
                     AND r.ult_venta_lote IS NOT NULL
                THEN (r.ult_venta_lote - COALESCE(r.primera_recep_90d::date, r.ultima_recepcion::date))::numeric
                WHEN COALESCE(r.primera_recep_90d, r.ultima_recepcion) IS NOT NULL
                THEN DATE_PART('day', p.ahora - COALESCE(r.primera_recep_90d, r.ultima_recepcion))::numeric
                ELSE DATE_PART('day', p.ahora - p.fecha_corte)::numeric
            END
        ) AS dias_efectivos
    FROM radiografia r CROSS JOIN params p
),
totales_categoria AS (
    SELECT bsale_office_id, COALESCE(category, '(sin)') AS category,
        SUM(unds_vendidas) AS cat_ventas, SUM(tdpv) AS cat_tdpv
    FROM calc GROUP BY 1, 2
),
metricas AS (
    SELECT c.*, tc.cat_ventas, tc.cat_tdpv,
        -- ★ Velocidad calculada con LOTE COMPLETO (lifetime desde última recep)
        ROUND((c.unds_lote_total / c.dias_efectivos)::numeric, 4) AS ventas_dia,
        ROUND(((c.unds_lote_total / c.dias_efectivos) * 30)::numeric, 2) AS proy_mes,
        -- % Frecuencia usa días con venta del lote completo
        LEAST(100.0, ROUND((c.dias_con_venta_lote::numeric / GREATEST(c.dias_efectivos, 1)) * 100, 2)) AS pct_frecuencia,
        -- Cobertura usa (stock_disponible + stock_reservado) porque el reservado
        -- es inventario que físicamente está pero comprometido. Incluirlo refleja
        -- el inventario REAL antes de comprar más. Impacta cuando hay reservas activas.
        CASE
            WHEN c.unds_lote_total <= 0 THEN NULL
            WHEN (c.stock_disponible + c.stock_reservado) = 0 THEN 0
            ELSE LEAST(9999, CEIL((c.stock_disponible + c.stock_reservado) / (c.unds_lote_total / c.dias_efectivos)))::int
        END AS dias_cobertura,
        -- ★ Días con stock en los últimos 30d (Opción 2: no penaliza por agotamiento).
        --    - Si aún tiene stock: 30 días completos
        --    - Si se agotó: días desde (hoy-30) hasta la última venta del lote
        --    - Si nunca vendió o se agotó hace >30d: 0
        CASE
            WHEN c.stock_disponible > 0 THEN 30
            WHEN c.ult_venta_lote IS NULL THEN 0
            WHEN c.ult_venta_lote >= ((SELECT ahora FROM params) - INTERVAL '30 days')::date
                 THEN GREATEST(1, (c.ult_venta_lote - ((SELECT ahora FROM params) - INTERVAL '30 days')::date + 1))::int
            ELSE 0
        END AS dias_con_stock_30d
    FROM calc c
    LEFT JOIN totales_categoria tc
      ON tc.bsale_office_id = c.bsale_office_id
     AND tc.category = COALESCE(c.category, '(sin)')
),
-- ★ Velocidad reciente (últimos 30d) — Opción 2: solo cuenta días con stock.
--    Calculada en CTE separada para reutilizar dias_con_stock_30d y mantener
--    legibilidad en el SELECT final.
metricas_reciente AS (
    SELECT m.*,
        CASE
            WHEN m.dias_con_stock_30d > 0
                 AND m.unds_vendidas_30d > 0
            THEN ROUND((m.unds_vendidas_30d / m.dias_con_stock_30d)::numeric, 4)
            ELSE NULL
        END AS vel_30d,
        CASE
            WHEN m.dias_con_stock_30d > 0
                 AND m.unds_vendidas_30d > 0
            THEN ROUND(((m.unds_vendidas_30d / m.dias_con_stock_30d) * 30)::numeric, 2)
            ELSE NULL
        END AS proy_30d_reciente
    FROM metricas m
),
-- ★ Sugerencia de transferencia inter-sucursal.
-- Detecta SKUs con EXCESO en una sucursal (cob >90d) Y DÉFICIT en la otra
-- (stock < demanda mensual con proy ≥10). Calcula cuántas unidades transferir.
transferencias AS (
    SELECT
        donor.bsale_office_id  AS donor_office,
        donor.bsale_variant_id AS variant_id,
        recip.sucursal         AS sucursal_receptora,
        -- Cantidad sugerida: déficit del receptor, capado al exceso del donante.
        -- Mantiene 30 días de cobertura en el donante después de la transferencia.
        GREATEST(0, LEAST(
            FLOOR(donor.stock_disponible - donor.proy_mes)::int,   -- excedente sobre 1 mes de demanda
            CEIL(recip.proy_mes - recip.stock_disponible)::int     -- déficit del receptor
        )) AS unidades_sugeridas
    FROM metricas_reciente donor
    JOIN metricas_reciente recip
      ON donor.bsale_variant_id = recip.bsale_variant_id
     AND donor.bsale_office_id  <> recip.bsale_office_id
    WHERE donor.dias_cobertura > 90                                 -- donante con exceso
      AND donor.proy_mes > 0
      AND recip.stock_disponible < recip.proy_mes                   -- receptor con déficit
      AND recip.proy_mes >= 10                                      -- receptor vende constante
      AND donor.stock_disponible - donor.proy_mes >= 5              -- mínimo 5 unds para mover
)
SELECT
    sucursal                 AS "Sucursal",
    department               AS "Departamento",
    category                 AS "Categoría",
    subcategory              AS "Subcategoría",
    display_code             AS "Código SKU",
    product_name             AS "Producto",
    primera_recepcion::date  AS "1ª Recepción",
    ultima_recepcion::date   AS "Últ. Recepción",
    ultima_venta             AS "Últ. Venta (90d)",
    edad_dias                AS "Edad SKU (días)",
    dias_desde_ultima_recep  AS "Días desde Últ. Recep",

    -- Bloque 90d (ventana operativa: actividad reciente)
    trim_scale(ROUND(unds_vendidas, 2))      AS "Unds Vend (90d)",
    trim_scale(ROUND(unds_recibidas_90d, 2)) AS "Unds Recib (90d)",
    -- ★ Bloque LOTE COMPLETO (comportamiento real desde la última recepción)
    trim_scale(ROUND(unds_lote_total, 2))    AS "Vend Lote Total",
    ult_venta_lote                           AS "Últ. Venta Lote",
    pri_venta_lote                           AS "1ª Venta Lote",
    trim_scale(ROUND(stock_disponible, 2))   AS "Stock Disp",
    trim_scale(ROUND(stock_reservado, 2))    AS "Stock Reserv",
    -- Velocidad: precisión dinámica. Productos con vel <0.1/día usan 4 decimales
    -- para mantener Vel×30=Proy y Stk/Vel=Cob visualmente consistentes.
    -- Productos con vel ≥0.1/día mantienen 2 decimales (legibilidad).
    trim_scale(CASE WHEN ventas_dia < 0.1
                    THEN ROUND(ventas_dia, 4)
                    ELSE ROUND(ventas_dia, 2)
               END)                          AS "Velocidad (uds/día)",
    trim_scale(ROUND(proy_mes, 2))           AS "Proyección 30d",
    -- ★ Velocidad RECIENTE (últimos 30d, solo días con stock — Opción 2).
    --    Refleja cómo rota el SKU AHORA, sin diluirse con la "cola larga" del lote.
    --    Útil para decisiones de reposición: si vel_30d < ventas_dia → demanda cayó.
    trim_scale(CASE WHEN vel_30d IS NULL THEN NULL
                    WHEN vel_30d < 0.1 THEN ROUND(vel_30d, 4)
                    ELSE ROUND(vel_30d, 2)
               END)                          AS "Vel últimos 30d",
    trim_scale(ROUND(proy_30d_reciente, 2))  AS "Proy 30d (reciente)",
    trim_scale(ROUND(pct_frecuencia, 1))     AS "% Frecuencia",
    dias_con_venta_lote                      AS "Días con Venta",
    dias_sin_venta_90d::int                  AS "Días sin Vender",

    CASE
        -- FIX: "Sin datos" debe depender de si el lote tuvo ventas, no de
        -- unds_post_recep (deprecada), que marcaba "Sin datos" de más.
        WHEN dias_con_venta_lote = 0 THEN 'Sin datos'
        WHEN pct_frecuencia >= 20  THEN 'X (Constante)'
        WHEN pct_frecuencia >= 8   THEN 'Y (Variable)'
        ELSE 'Z (Errático / Ráfaga)'
    END                       AS "XYZ",
    CASE
        WHEN dias_cobertura IS NULL THEN 's/d'
        WHEN dias_cobertura = 0     THEN 'Agotado'
        WHEN dias_cobertura >= 9999 THEN '+999 días'
        ELSE dias_cobertura || ' días'
    END                       AS "Cobertura",
    -- % Rotación del Stock: V90 / (V90 + Stock). Mide qué fracción del inventario
    -- disponible se rotó. Por construcción ≤100% (cuando stock=0 da 100%).
    CASE WHEN tdpv > 0
         THEN trim_scale(ROUND((unds_vendidas / tdpv * 100)::numeric, 1))
         ELSE 0::numeric END   AS "% Rotación Stock",
    -- % Demanda vs Reposición: V90 / R90 (puede ser >100% si vendió más de lo
    -- recibido — indica demanda excedió reposición y agotó stock previo).
    -- Es la métrica que REALMENTE detecta "demanda insatisfecha".
    CASE WHEN unds_recibidas_90d > 0
         THEN trim_scale(ROUND((unds_vendidas / unds_recibidas_90d * 100)::numeric, 1))
         ELSE NULL::numeric END AS "% Demanda vs Reposición",

    -- Tendencia: compara ventas últimos 45d vs los 45d previos (dentro de 90d total).
    -- 📈 Creciendo: v_recent >1.5x v_old (claramente subiendo)
    -- 📉 Decayendo: v_recent <0.7x v_old (claramente bajando)
    -- → Estable: relación 0.7-1.5x
    -- 🆕 Inicio: sin ventas previas, solo recientes (producto nuevo o reactivado)
    -- 💤 Pausado: solo ventas previas, ninguna reciente (en pausa)
    CASE
        WHEN v_recent_45d = 0 AND v_old_45d = 0 THEN '—'
        WHEN v_old_45d = 0 AND v_recent_45d > 0 THEN '🆕 Inicio'
        WHEN v_recent_45d = 0 AND v_old_45d > 0 THEN '💤 Pausado'
        WHEN v_recent_45d > v_old_45d * 1.5 THEN '📈 Creciendo'
        WHEN v_recent_45d < v_old_45d * 0.7 THEN '📉 Decayendo'
        ELSE '→ Estable'
    END AS "Tendencia",

    -- Sugerencia de transferencia: si esta sucursal tiene exceso del SKU mientras
    -- la otra tiene déficit, sugiere cuántas unidades mover.
    CASE
        WHEN t.unidades_sugeridas IS NOT NULL AND t.unidades_sugeridas >= 5
        THEN '→ Transferir ' || t.unidades_sugeridas || ' a ' || t.sucursal_receptora
        ELSE NULL
    END AS "Sugerencia Transferencia",

    CASE
        -- NUEVO: ventana de gracia de 7 días para evaluar rotación.
        --    Cambio: bajado de 15d → 7d porque hay productos que se agotan antes
        --    de los 7 días (deben caer en QUIEBRE STOCK o LOTE AGOTADO RÁPIDO, no en NUEVO).
        --    Threshold <15 ventas para que productos como GF-3687 (vel=2.14/d, V90=15)
        --    salten directo a evaluación de rotación normal.
        WHEN primera_recepcion >= NOW() - INTERVAL '7 days'
             AND unds_vendidas < 15
             THEN '🌱 NUEVO: esperando ≥7d para evaluar rotación'

        WHEN stock_disponible = 0
             AND unds_recibidas_90d > 0
             AND unds_post_recep >= unds_recibidas_90d * 0.80
             AND primera_recep_90d IS NOT NULL
             AND ultima_venta IS NOT NULL
             AND (ultima_venta::date - primera_recep_90d::date) <= 30
             THEN '🚨 QUIEBRE STOCK: Lote vendido rápido (≤30d)'

        -- ★ 🔄 REABASTECIDO RECIENTE: producto que llegó hace ≤14d, aún sin venta.
        --    NO es MUERTO — apenas tuvo tiempo de estar en góndola. Esperar antes de juzgar.
        --    Va ANTES de MUERTO 90D para rescatar productos recién reabastecidos.
        --    Captura casos como 74992796365390 (recibió 33 hace 2d, stock 33).
        WHEN stock_disponible > 0
             AND unds_vendidas = 0
             AND dias_desde_ultima_recep IS NOT NULL
             AND dias_desde_ultima_recep <= 14
             THEN '🔄 REABASTECIDO RECIENTE: nueva recep (≤14d) aún sin venta — esperar'

        WHEN stock_disponible > 0 AND unds_vendidas = 0
             THEN '💀 MUERTO 90D: stock parado sin ventas (capital estancado)'

        -- ★ ⛔ PÉRDIDA TOTAL: vendió <20% del recibido lifetime Y se perdió mucho.
        --    Ahora considera también TRASLADOS DE SALIDA — si la mayoría del stock
        --    salió por traslado, no es pérdida sino redistribución (no entra aquí).
        WHEN stock_disponible = 0
             AND unds_recibidas_lifetime >= 5
             AND unds_consumidas_lifetime >= unds_recibidas_lifetime * 0.50
             AND unds_vendidas_lifetime < unds_recibidas_lifetime * 0.20
             AND unds_consumidas_lifetime > unds_trasladadas_lifetime  -- consumos > traslados (es pérdida real, no redistribución)
             THEN '⛔ PÉRDIDA TOTAL: casi sin ventas (<20%) — todo el stock se ajustó (revisar control físico)'

        -- ★ ⚠️ VENTAS CON PÉRDIDA: vendió 20-50% lifetime, pero también se perdió mucho.
        WHEN stock_disponible = 0
             AND unds_recibidas_lifetime >= 5
             AND unds_consumidas_lifetime > unds_vendidas_lifetime
             AND unds_vendidas_lifetime >= unds_recibidas_lifetime * 0.20
             AND unds_vendidas_lifetime < unds_recibidas_lifetime * 0.50
             AND unds_consumidas_lifetime > unds_trasladadas_lifetime  -- pérdida real, no redistribución
             THEN '⚠️ VENTAS CON PÉRDIDA: vendía pero también se perdió mucho (investigar control físico)'

        -- ★ 🔥💎 EXITOSO ACTIVO: vendió ≥80% lifetime Y SIGUE vendiendo (≤30d sin venta).
        --    FIX v3: incluye TRASLADOS como salidas (no es pérdida, es redistribución).
        --    Caso 252590: recibió 96, vendió 48, trasladó 48 → (48+0+48)/96 = 100% ✓
        --    Caso KD-2892: recibió 61, vendió 30, consumió 1, trasladó 30 → (30+1+30)/61 = 100% ✓
        WHEN stock_disponible = 0
             AND unds_vendidas_lifetime >= 1
             AND unds_recibidas_lifetime >= 2
             AND (unds_vendidas_lifetime + unds_consumidas_lifetime + unds_trasladadas_lifetime) >= unds_recibidas_lifetime * 0.80
             AND ultima_venta IS NOT NULL
             AND dias_sin_venta_90d <= 30
             THEN '🔥💎 EXITOSO ACTIVO: vendió todo lifetime Y sigue rotando — REPONER YA'

        -- ★ 💎 EXITOSO PASADO: sell-through ≥80% (ventas + consumos + traslados) pero sin demanda reciente.
        WHEN stock_disponible = 0
             AND unds_vendidas_lifetime >= 1
             AND unds_recibidas_lifetime >= 2
             AND (unds_vendidas_lifetime + unds_consumidas_lifetime + unds_trasladadas_lifetime) >= unds_recibidas_lifetime * 0.80
             AND edad_dias > 30
             THEN '💎 EXITOSO PASADO: stock salió casi al 100% pero sin demanda reciente (evaluar)'

        -- RESIDUO HISTÓRICO: producto antiguo (>180d) que nunca vendió en 90d con
        -- recepciones marginales (R90 <5) Y bajo volumen lifetime (<50).
        -- FIX: agregado threshold unds_vendidas_lifetime < 50 para no marcar como
        -- residuo productos exitosos antiguos (SD25167 vendió 475 unds y caía aquí).
        -- FIX v2: la regla EXITOSO PASADO de arriba ya rescata los chicos con
        -- sell-through ≥70%. Acá solo caen los chicos con sell-through bajo.
        WHEN stock_disponible = 0 AND unds_vendidas = 0
             AND unds_recibidas_90d BETWEEN 1 AND 4
             AND edad_dias > 180
             AND unds_vendidas_lifetime < 50
             THEN '🪦 RESIDUO HISTÓRICO: producto antiguo sin rotación (descatalogar)'

        -- FIX: agregado threshold lifetime <50 para que productos exitosos con
        -- devoluciones tardías caigan en AGOTADO HISTÓRICO en lugar de aquí.
        WHEN stock_disponible = 0 AND unds_vendidas = 0 AND unds_recibidas_90d > 0
             AND unds_vendidas_lifetime < 50
             THEN '❓ RECIBIDO Y NO VENDIDO: revisar (mermas/transferencias)'

        WHEN stock_disponible BETWEEN 1 AND 2 AND dias_sin_venta_90d BETWEEN 16 AND 59
             THEN '👀 ALERTA VISUAL: stock 1-2 unds sin movimiento 16-59d (revisar visibilidad/vencimiento)'

        WHEN stock_disponible = 0
             AND dias_sin_venta_90d <= 14
             AND proy_mes >= 10
             AND pct_frecuencia >= 20
             THEN '🚨 QUIEBRE STOCK (Alta Rotación X) - ¡Comprar Ya!'
        WHEN stock_disponible = 0
             AND dias_sin_venta_90d <= 14
             AND proy_mes >= 10
             AND pct_frecuencia < 8
             THEN '🚨 QUIEBRE STOCK (Alta Rotación Z - cuidado, ráfaga)'
        WHEN stock_disponible = 0
             AND dias_sin_venta_90d <= 14
             AND proy_mes >= 10
             THEN '🚨 QUIEBRE STOCK (Alta Rotación Y) - ¡Comprar Ya!'

        -- 💎 PRODUCTO EXITOSO AGOTADO: vendió ≥70% lifetime y tuvo volumen relevante.
        --    Captura productos como P0189 (vendió 798 de 872 lifetime), MAQ 10, etc.
        --    Esta regla va ANTES de LOTE AGOTADO RÁPIDO porque atrapa productos
        --    con ciclos LARGOS (>90d) pero que demostraron vendibilidad lifetime.
        --    Diferencia con LOTE AGOTADO RÁPIDO: no exige ciclo corto.
        WHEN stock_disponible = 0
             AND unds_recibidas_lifetime >= 50              -- volumen lifetime relevante
             AND unds_vendidas_lifetime >= unds_recibidas_lifetime * 0.70  -- ≥70% lifetime
             AND (ult_venta_lote - ultima_recepcion::date) > 90   -- ciclo largo (no es "lote rápido")
             THEN '💎 PRODUCTO EXITOSO AGOTADO: vendió 70%+ en su vida (candidato a reposición)'

        -- 🔥 LOTE AGOTADO RÁPIDO: vendió ≥70% del ciclo actual en ≤90 días Y reciente.
        --    Captura: Caramelo ROMA-11CM (100%), B1721 SOCKET (100%), Aloe Vera (2 lotes en 8d).
        --    Filtro de recencia: dias_sin_venta_90d ≤30. Sin él, productos viejos
        --    (DiasUltRec >90d) caían aquí pidiendo "reposición urgente" cuando las
        --    ventas eran históricas. Productos sin venta reciente → AGOTADO POTENCIAL.
        --    Lógica del % sell-through:
        --      - Si hubo recepciones en 90d → comparar con recibidas en 90d (caso Aloe)
        --      - Si no → comparar con recibido lifetime (caso B1721)
        WHEN stock_disponible = 0
             AND ult_venta_lote IS NOT NULL
             AND dias_sin_venta_90d <= 30                                 -- recencia: vendió en últimos 30d
             AND COALESCE(primera_recep_90d, ultima_recepcion) IS NOT NULL
             AND (ult_venta_lote - COALESCE(primera_recep_90d::date, ultima_recepcion::date)) <= 90
             AND unds_lote_total >= 3
             AND (
                 -- Caso A: hubo recepción en 90d → comparar con recibidas en 90d (60% threshold)
                 --    Más permisivo (60% en vez de 70%) para tolerar mermas/consumos no documentados.
                 (primera_recep_90d IS NOT NULL
                  AND unds_recibidas_90d > 0
                  AND unds_lote_total >= unds_recibidas_90d * 0.60)
                 OR
                 -- Caso B: sin recepción en 90d → comparar con lifetime (70% se mantiene)
                 (primera_recep_90d IS NULL
                  AND unds_recibidas_lifetime > 0
                  AND unds_lote_total >= unds_recibidas_lifetime * 0.70)
             )
             THEN '🔥 LOTE AGOTADO RÁPIDO: candidato a reposición (revisar demanda actual)'

        -- 🔥 STOCK PREVIO VENDIDO: producto agotado con buena venta 90d.
        --    Captura DOS sub-casos:
        --      (A) Vendió MÁS de lo recibido en 90d (consumió stock viejo) — caso PL-04, MH52-91
        --      (B) Vendió ≥70% de lo recibido en 90d (sell-through) — caso AS-3013A (77%)
        --    Threshold lifetime ≥50% (tolerante con mermas/consumos no documentados).
        --    Va DESPUÉS de LOTE AGOTADO RÁPIDO para no robar casos como B1721/P0189.
        --    FIX: el caso B exigía además "unds_vendidas >= 15", que mandaba a
        --    'AGOTADO MARGINAL' lotes chicos vendidos al 100% (ej. FXT-2289: 13/13).
        --    Se quitó ese piso: el sell-through ≥70% + el piso V90 ≥10 de arriba
        --    ya aseguran buena rotación sea el lote de 13 o de 18 unidades.
        WHEN stock_disponible = 0
             AND unds_vendidas >= 10
             AND unds_recibidas_lifetime > 0
             AND (
                 unds_vendidas > unds_recibidas_90d                            -- (A) vendió stock viejo
                 OR
                 (unds_recibidas_90d >= 3                                     -- (B) sell-through 90d ≥70%
                  AND unds_vendidas >= unds_recibidas_90d * 0.70)
             )
             AND (
                 unds_vendidas_lifetime >= unds_recibidas_lifetime * 0.50      -- vida ≥50% (laxo por mermas)
                 OR unds_vendidas >= 30                                         -- o muy alto volumen 90d
             )
             THEN '🔥 STOCK PREVIO VENDIDO: vendió del stock viejo (buena vida → reponer)'

        -- ★ 🔄 REABASTECIDO ACTIVO: stock fresco (≤14d) + cobertura aparente alta (>45d).
        --    Captura productos cuya cobertura está INFLADA por período sin stock previo.
        --    Aplica si cumple UNA de 2 condiciones:
        --      A) Velocidad real reciente (desde recep) ≥10/mes — vende bien AHORA
        --      B) Historial lifetime excelente (sell-through ≥70%) — vendió bien antes
        --    Caso B (360207): vendió 25 de 31 lifetime (80%), recibió hace 4d, vendió 1 →
        --    la vel reciente es baja pero el historial demuestra que rota cuando hay stock.
        WHEN stock_disponible > 0
             AND dias_desde_ultima_recep IS NOT NULL
             AND dias_desde_ultima_recep <= 14
             AND dias_cobertura > 45
             AND (
                 -- Caso A: vel real reciente buena
                 (unds_vendidas_30d >= 2
                  AND (unds_vendidas_30d::numeric / GREATEST(1, dias_desde_ultima_recep::numeric)) * 30 >= 10)
                 OR
                 -- Caso B: historial lifetime excelente (≥70% sell-through, ≥10 ventas)
                 (unds_vendidas_lifetime >= 10
                  AND unds_recibidas_lifetime > 0
                  AND unds_vendidas_lifetime >= unds_recibidas_lifetime * 0.70)
             )
             THEN '🔄 REABASTECIDO ACTIVO: vende bien (cob aparente alta es por vel diluida)'

        -- ★ FIX (tendencia): un producto de bajo volumen (proy <10) pero con
        --   tendencia POSITIVA — creciendo (📈) o emergente con historia — NO debe
        --   mandarse a liquidar. La velocidad promedio del lote lo subestima;
        --   las ventas recientes (45d) muestran que va en alza.
        --   FIX v3: el caso v_old_45d=0 ahora exige sell-through ≥50% del recibido.
        --   Productos como HO2131ORG (31d, vendió 2 de 18 = 11%) NO son "alza" —
        --   pasaron 30+ días y no rotan, deben caer en BAJA ROTACIÓN.
        WHEN proy_mes < 10
             AND v_recent_45d > 0
             AND (
                 -- 📈 Creciendo real: requiere historial previo Y aceleración ≥1.5x
                 (v_old_45d > 0 AND v_recent_45d > v_old_45d * 1.5)
                 OR
                 -- 🆕 Emergente CON tracción: >30d Y vendió ≥50% del recibido lifetime
                 (v_old_45d = 0 AND edad_dias > 30
                  AND unds_recibidas_lifetime > 0
                  AND unds_vendidas_lifetime >= unds_recibidas_lifetime * 0.50)
             )
             THEN '📈 BAJO VOLUMEN EN ALZA: vende poco pero la tendencia es positiva — observar, no liquidar'

        -- AGOTADO HACE TIEMPO: dividido en CUATRO casos para acción precisa:
        --   (1) AGOTADO POTENCIAL ACTIVO: lifetime ≥50 Y V90 ≥5 → reponer prioridad (demanda persiste)
        --   (2) AGOTADO HISTÓRICO: lifetime ≥50 pero V90 <5 → vendió en su vida pero demanda decayó
        --   (3) PRODUCTO EMERGENTE: V90 ≥15 pero lifetime <50 → corto historial, evaluar
        --   (4) AGOTADO MARGINAL: bajo volumen total → candidato a descatalogar
        --   FIX: el filtro usa COALESCE(dias_sin_venta_90d, 9999) para incluir
        --   productos con V90=0 (ventas netas 0 por devoluciones); antes el NULL
        --   los dejaba afuera y caían mal en FALSO AGOTADO.
        WHEN stock_disponible = 0 AND COALESCE(dias_sin_venta_90d, 9999) >= 15
             AND unds_vendidas_lifetime >= 50
             AND unds_vendidas >= 5
             THEN '👻 AGOTADO POTENCIAL ACTIVO: vendió ≥50 lifetime y aún en demanda (reponer prioridad)'
        WHEN stock_disponible = 0 AND COALESCE(dias_sin_venta_90d, 9999) >= 15
             AND unds_vendidas_lifetime >= 50
             THEN '💤 AGOTADO HISTÓRICO: vendió bien en vida pero demanda decayó (evaluar descatalogar)'
        WHEN stock_disponible = 0 AND COALESCE(dias_sin_venta_90d, 9999) >= 15
             AND unds_vendidas >= 15
             THEN '🌿 PRODUCTO EMERGENTE: vendió ≥15 en 90d pero corto historial lifetime (evaluar reposición)'
        WHEN stock_disponible = 0 AND COALESCE(dias_sin_venta_90d, 9999) >= 15
             THEN '🪦 AGOTADO MARGINAL: bajo volumen lifetime (<50 unds) — candidato a descatalogar'

        -- Regla 45d: SOLO si el producto realmente no rota (proy_mes < 10).
        --    Antes incluía "OR cobertura > 60" pero atrapaba productos sanos con cob 60-90
        --    (que pertenecen a INVENTARIO SANO). Si cob > 90 con proy alto → cae en EXCESO.
        WHEN stock_disponible > 0
             AND dias_desde_ultima_recep > 45
             AND proy_mes < 10
             THEN '🐢 BAJA ROTACIÓN (lote sin rotar >45d → liquidar/promocionar)'

        WHEN stock_disponible = 0 AND proy_mes < 10
             THEN '👻 FALSO AGOTADO: baja rotación + sin stock'

        -- ⚠️ STOCK CRÍTICO con venta RECIENTE → SÍ reponer aunque la rotación
        --    promedio sea baja. Captura productos como Sapolio (stock 3, vendió 3
        --    en últimos 30d, vel_30d=0.1): la cobertura es 17d y va a agotarse.
        WHEN dias_cobertura IS NOT NULL AND dias_cobertura < 30 AND proy_mes < 10
             AND vel_30d IS NOT NULL AND vel_30d > 0
             THEN '⚠️ STOCK CRÍTICO: poco stock + venta reciente (reponer aunque rotación baja)'

        -- ⚠️ STOCK CRÍTICO SIN venta reciente → no urgir (rotación realmente baja)
        WHEN dias_cobertura IS NOT NULL AND dias_cobertura < 30 AND proy_mes < 10
             THEN '⚠️ STOCK CRÍTICO pero BAJA ROTACIÓN (sin venta reciente — no urgir)'

        WHEN proy_mes < 10
             THEN '🐢 BAJA ROTACIÓN (proy <10 unds/mes — bajar pedido / revisar surtido)'

        -- Las clasificaciones de ALTA/MEDIA/SANO/EXCESO requieren stock > 0
        -- (defensa: ningún producto agotado puede ser "ALTA ROTACIÓN")
        --
        -- ALTA ROTACIÓN dividida por volumen absoluto (proy_mes):
        --   - proy ≥30/mes → ALTA ROTACIÓN real (volumen alto, prioridad de compra)
        --   - proy 10-29/mes → ROTACIÓN ACTIVA (vende constante pero volumen modesto)
        -- Resuelve 142 productos con vel <1/día que se mostraban como "alta rotación"
        -- siendo en realidad rotación activa de bajo volumen.

        -- ★ 🔥📉 ALTA ROTACIÓN DECAYENDO: vende mucho PERO la demanda está cayendo
        --    (v_recent_45d < v_old_45d * 0.7). Si compras al ritmo del lote completo
        --    vas a sobre-stockearte. Reponer al ritmo de los últimos 30d (proy reciente).
        --    Va ANTES de las 3 reglas ALTA ROTACIÓN X/Y/Z para atraparlas todas.
        WHEN stock_disponible > 0 AND proy_mes >= 30 AND dias_cobertura < 30
             AND v_recent_45d > 0 AND v_old_45d > 0
             AND v_recent_45d < v_old_45d * 0.7
             THEN '🔥📉 ALTA ROTACIÓN DECAYENDO (reducir reposición — usar Vel 30d)'

        WHEN stock_disponible > 0 AND proy_mes >= 30 AND dias_cobertura < 30 AND pct_frecuencia >= 20
             THEN '🔥 ALTA ROTACIÓN X (compra constante, vol ≥30/mes)'
        WHEN stock_disponible > 0 AND proy_mes >= 30 AND dias_cobertura < 30 AND pct_frecuencia < 8
             THEN '🔥 ALTA ROTACIÓN Z (ráfaga vol ≥30/mes — cuidado)'
        WHEN stock_disponible > 0 AND proy_mes >= 30 AND dias_cobertura < 30
             THEN '🔥 ALTA ROTACIÓN Y (variable, vol ≥30/mes)'

        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura < 30 AND pct_frecuencia >= 20
             THEN '💫 ROTACIÓN ACTIVA X (vol 10-29/mes, constante)'
        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura < 30 AND pct_frecuencia < 8
             THEN '💫 ROTACIÓN ACTIVA Z (vol 10-29/mes, ráfaga)'
        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura < 30
             THEN '💫 ROTACIÓN ACTIVA Y (vol 10-29/mes, variable)'

        -- ★ FIX: escala compactada (Opción A). MEDIA ROTACIÓN eliminada.
        --    SANO: 30-45d (antes 46-90d). EXCESO: >45d (antes >90d).
        --    Razón operativa: un producto con cob >45d ya es capital estancado.
        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura BETWEEN 30 AND 45
             THEN '🟢 INVENTARIO SANO (cob 30-45d — ritmo normal)'

        -- ★ 🧊📉 EXCESO LIQUIDAR: exceso (cob >45d) + demanda en caída.
        --    Doble alerta: capital estancado Y la demanda se está enfriando.
        --    Va ANTES de EXCESO DE INVENTARIO para separar los casos urgentes.
        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura > 45
             AND v_recent_45d > 0 AND v_old_45d > 0
             AND v_recent_45d < v_old_45d * 0.7
             THEN '🧊📉 EXCESO LIQUIDAR: capital estancado + demanda cayendo (promocionar urgente)'

        WHEN stock_disponible > 0 AND proy_mes >= 10 AND dias_cobertura > 45
             THEN '🧊 EXCESO DE INVENTARIO (capital estancado)'

        ELSE '⚖️ EN ANÁLISIS: caso no cubierto por reglas — revisar manualmente'
     END                       AS "Clasificación"

FROM metricas_reciente m
LEFT JOIN transferencias t
  ON t.donor_office = m.bsale_office_id
 AND t.variant_id   = m.bsale_variant_id
ORDER BY sucursal, category, "% Rotación Stock" DESC NULLS LAST;
