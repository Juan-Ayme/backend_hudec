-- Productos con sell-through lifetime ≥70%, stock > 0 actual
-- Para cruzarlos con clasificación del SQL principal
WITH ls AS (
    SELECT v.display_code AS sku, r.bsale_office_id AS office,
           SUM(rd.quantity) AS recibido_lt
    FROM reception_details rd
    JOIN receptions r USING(bsale_reception_id)
    JOIN variants v ON v.bsale_variant_id = rd.bsale_variant_id
    WHERE r.bsale_office_id IN (1,3) AND rd.quantity < 10000
    GROUP BY 1,2
),
vs AS (
    SELECT v.display_code AS sku, d.bsale_office_id AS office,
           SUM(CASE WHEN d.bsale_document_type_id IN (1,10,50,51,52,53) THEN dd.quantity ELSE 0 END) -
           SUM(CASE WHEN d.bsale_document_type_id IN (9,40,43) THEN dd.quantity ELSE 0 END) AS vendido_lt
    FROM document_details dd
    JOIN documents d USING(bsale_document_id)
    JOIN variants v ON v.bsale_variant_id = dd.bsale_variant_id
    WHERE d.bsale_office_id IN (1,3)
    GROUP BY 1,2
),
stock_act AS (
    SELECT v.display_code AS sku, sl.bsale_office_id AS office, sl.quantity_available AS stock
    FROM stock_levels sl
    JOIN variants v ON v.bsale_variant_id = sl.bsale_variant_id
    WHERE sl.bsale_office_id IN (1,3)
)
SELECT ls.sku,
       CASE WHEN ls.office = 1 THEN 'MAGDALENA' ELSE 'ASAMBLEA' END AS sucursal,
       ls.recibido_lt AS recibido,
       vs.vendido_lt AS vendido,
       ROUND((vs.vendido_lt / NULLIF(ls.recibido_lt, 0) * 100)::numeric, 1) AS pct,
       COALESCE(sa.stock, 0) AS stock_actual
FROM ls
LEFT JOIN vs ON ls.sku = vs.sku AND ls.office = vs.office
LEFT JOIN stock_act sa ON sa.sku = ls.sku AND sa.office = ls.office
WHERE ls.recibido_lt >= 10
  AND vs.vendido_lt >= ls.recibido_lt * 0.70
  AND COALESCE(sa.stock, 0) > 0
ORDER BY pct DESC, ls.recibido_lt DESC;
