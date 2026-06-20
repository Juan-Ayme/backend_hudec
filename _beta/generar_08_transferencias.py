"""
Generador de `08_transferencias.sql`.

Toma las CTEs base de `_matriz_90d_base.sql` (la base compartida de las
matrices 04/04b/05, hasta `cat_baseline`) y les suma un SELECT final dedicado
a sugerencias de transferencia entre sucursales — pares (sucursal_donante,
sucursal_receptora) × SKU con clasificación de causa, unidades sugeridas,
impacto $ y prioridad.

Por qué un generador y no copy-paste manual:
  - Las CTEs base son ~500 líneas. Si la base cambia (fix de métricas, nueva
    columna), 08 debe sincronizarse o reportará data desfasada.
  - Correr este script regenera 08 desde la base en 2 segundos.

Uso:
    python -m _beta.generar_06_transferencias
"""
from __future__ import annotations
import sys
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app/kawii_matrix/sql/_matriz_90d_base.sql"
DST = ROOT / "app/kawii_matrix/sql/08_transferencias.sql"


HEADER = """\
-- =============================================================
-- MATRIZ 08 — SUGERENCIAS DE TRANSFERENCIA INTER-SUCURSAL
-- =============================================================
-- ⚠ ARCHIVO AUTO-GENERADO por `_beta/generar_06_transferencias.py`.
--   NO editar manualmente las CTEs base (van desde `params` hasta
--   `cat_baseline`). Si 04b cambia, regenerar con:
--       python -m _beta.generar_06_transferencias
--
-- Objetivo de esta matriz:
--   Encontrar SKUs donde una sucursal tiene STOCK SOBRANTE (exceso,
--   lote frenado, baja rotación, muerto) Y la otra sucursal tiene
--   DEMANDA INSATISFECHA (quiebre, alta rotación con poco stock,
--   agotado con demanda). Sugiere cantidad a transferir, impacto
--   estimado en S/ y prioridad.
--
-- Devuelve UNA fila por cada par (donante × receptor × SKU) válido.
--   Si ambas sucursales son candidatas a donar/recibir, sale en ambas
--   direcciones — el usuario elige.
-- =============================================================
"""


# El SELECT final del módulo 06. Se concatena después de las CTEs base.
# Las CTEs base ya terminan con `),` — agregamos `precio_por_sku AS (...)`
# como CTE adicional (no necesita coma extra al principio).
SELECT_06 = r"""

-- ════════════════════════════════════════════════════════════════════
-- SELECT FINAL — Pares (donante, receptor) para el MISMO SKU
-- ════════════════════════════════════════════════════════════════════
-- precio_ref = precio promedio observado (monto/unds de quien tenga ventas).
-- Calculado fuera del JOIN para evitar dividir por cero.
precio_por_sku AS (
    SELECT bsale_variant_id,
           bsale_office_id,
           CASE WHEN unds_vendidas > 0
                THEN ROUND((monto_vendido_90d / unds_vendidas)::numeric, 2)
                ELSE NULL
           END AS precio_prom
    FROM metricas_reciente
)

SELECT
    -- ───── Identificación del SKU ─────
    donor.bsale_variant_id,
    donor.display_code              AS "SKU",
    donor.product_name              AS "Producto",
    donor.department                AS "Depto",
    donor.category                  AS "Categoría",
    donor.subcategory               AS "Subcat",

    -- ───── DONANTE: sucursal que da ─────
    donor.sucursal                  AS "↗ Donante (sucursal)",
    donor.stock_disponible::int     AS "Donante stock",
    ROUND(donor.proy_mes, 1)        AS "Donante proy lifetime",
    ROUND(donor.proy_30d_reciente, 1) AS "Donante proy 30d real",
    donor.dias_cobertura            AS "Donante cob días",
    CASE
        WHEN donor.ult_venta_lote IS NULL THEN NULL
        ELSE (CURRENT_DATE - donor.ult_venta_lote)::int
    END                              AS "Donante DSV",

    -- ───── RECEPTOR: sucursal que recibe ─────
    recip.sucursal                  AS "↘ Receptor (sucursal)",
    recip.stock_disponible::int     AS "Receptor stock",
    ROUND(recip.proy_mes, 1)        AS "Receptor proy lifetime",
    ROUND(recip.proy_30d_reciente, 1) AS "Receptor proy 30d real",
    recip.dias_cobertura            AS "Receptor cob días",
    CASE
        WHEN recip.ult_venta_lote IS NULL THEN NULL
        ELSE (CURRENT_DATE - recip.ult_venta_lote)::int
    END                              AS "Receptor DSV",

    -- ───── RAZÓN del par ─────
    --   Por qué el donante puede ceder
    CASE
        WHEN donor.stock_disponible >= 5
             AND donor.proy_mes >= 10
             AND COALESCE(donor.proy_30d_reciente, 0) < 5
             AND COALESCE((CURRENT_DATE - donor.primera_recepcion::date), 0) >= 90
            THEN '💀 LOTE FRENADO (vendía antes, hoy parado)'
        WHEN donor.dias_cobertura > 90 AND donor.proy_mes >= 10
            THEN '🧊 EXCESO DE INVENTARIO (cob >90d)'
        WHEN donor.unds_vendidas = 0
             AND donor.stock_disponible >= 5
             AND donor.primera_recepcion < (CURRENT_DATE - INTERVAL '60 days')
            THEN '💀 STOCK MUERTO (sin venta en 90d)'
        WHEN donor.proy_mes < 10
             AND donor.stock_disponible >= 15
             AND donor.dias_cobertura > 60
            THEN '🐢 BAJA ROTACIÓN con stock alto'
        ELSE NULL
    END                              AS "Razón donante",

    --   Por qué el receptor necesita
    CASE
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 30
            THEN '🚨 QUIEBRE de bestseller'
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 10
            THEN '🚨 Sin stock con demanda activa'
        WHEN recip.dias_cobertura IS NOT NULL
             AND recip.dias_cobertura < 14
             AND recip.proy_mes >= 30
            THEN '🔥 Alta rotación, cob <14d'
        WHEN recip.dias_cobertura IS NOT NULL
             AND recip.dias_cobertura < 21
             AND recip.proy_mes >= 10
            THEN '⚠ Poco stock con demanda'
        WHEN recip.stock_disponible = 0 AND recip.unds_vendidas_lifetime >= 10
            THEN '💎 Agotado, hay demanda histórica'
        ELSE NULL
    END                              AS "Razón receptor",

    -- ───── UNIDADES SUGERIDAS ─────
    --   regla: mover el mínimo entre
    --     (a) excedente del donante  — si el donante está muerto/frenado,
    --         puede transferir TODO; si solo es exceso, deja 30d cob
    --     (b) déficit del receptor   — cubre 60d de demanda
    GREATEST(1, LEAST(
        CASE
            WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                THEN donor.stock_disponible::int
            ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
        END,
        CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
    ))                               AS "Unds sugeridas",

    -- Stock del donante DESPUÉS de transferir
    GREATEST(0, donor.stock_disponible::int -
        GREATEST(1, LEAST(
            CASE
                WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                    THEN donor.stock_disponible::int
                ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
            END,
            CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
        ))
    )                                AS "Donante stock post",

    -- Stock del receptor DESPUÉS de transferir
    (recip.stock_disponible::int +
        GREATEST(1, LEAST(
            CASE
                WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                    THEN donor.stock_disponible::int
                ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
            END,
            CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
        ))
    )                                AS "Receptor stock post",

    -- Cobertura post del receptor (estimada con proy_mes)
    CASE
        WHEN recip.proy_mes <= 0 THEN NULL
        ELSE CEIL((
            recip.stock_disponible +
            GREATEST(1, LEAST(
                CASE
                    WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                        THEN donor.stock_disponible::int
                    ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
                END,
                CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
            ))
        ) / (recip.proy_mes / 30.0))::int
    END                              AS "Receptor cob post",

    -- ───── IMPACTO ECONÓMICO ─────
    --   precio promedio observado (del receptor o del donante)
    COALESCE(pp_r.precio_prom, pp_d.precio_prom)        AS "Precio prom S/",

    --   impacto $ = unds_sugeridas × precio
    ROUND(
        (GREATEST(1, LEAST(
            CASE
                WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                    THEN donor.stock_disponible::int
                ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
            END,
            CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
        )) * COALESCE(pp_r.precio_prom, pp_d.precio_prom, 0))::numeric,
        2
    )                                AS "Impacto S/ estimado",

    -- ───── PRIORIDAD ─────
    --   1 = urgentísimo (receptor sin stock + bestseller),
    --   2 = urgente, 3 = alta, 4 = media, 5 = baja
    CASE
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 30 THEN 1
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 10 THEN 2
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 14 THEN 3
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 30 THEN 4
        ELSE 5
    END                              AS "Prioridad",

    -- ───── CLASIFICACIÓN ─────
    -- Necesaria para que build_workbook (que agrupa el Excel maquetado) tenga
    -- una columna principal. Es el nivel de prioridad expresado en texto.
    CASE
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 30
            THEN '🚨 URGENTÍSIMO: receptor sin stock + bestseller — TRANSFERIR YA'
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 10
            THEN '🚨 URGENTE: receptor sin stock con demanda activa'
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 14
            THEN '🔥 ALTA: receptor con cobertura crítica (<14 días)'
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 30
            THEN '⚠ MEDIA: receptor con cobertura baja (<30 días)'
        ELSE '🐢 BAJA: transferencia oportunista (no crítica)'
    END                              AS "Clasificación"

FROM metricas_reciente donor
JOIN metricas_reciente recip
  ON donor.bsale_variant_id = recip.bsale_variant_id
 AND donor.bsale_office_id <> recip.bsale_office_id
LEFT JOIN precio_por_sku pp_d
  ON pp_d.bsale_variant_id = donor.bsale_variant_id
 AND pp_d.bsale_office_id  = donor.bsale_office_id
LEFT JOIN precio_por_sku pp_r
  ON pp_r.bsale_variant_id = recip.bsale_variant_id
 AND pp_r.bsale_office_id  = recip.bsale_office_id
WHERE
    -- DONANTE: tiene stock suficiente Y está en alguna situación de
    -- excedente (cualquier criterio activa la regla)
    donor.stock_disponible >= 5
    AND (
        -- exceso
        (donor.dias_cobertura > 90 AND donor.proy_mes >= 5)
        OR
        -- lote frenado (P15)
        (donor.proy_mes >= 10
         AND COALESCE(donor.proy_30d_reciente, 0) < 5
         AND COALESCE((CURRENT_DATE - donor.primera_recepcion::date), 0) >= 90)
        OR
        -- muerto: sin ventas 90d con stock recibido hace tiempo
        (donor.unds_vendidas = 0
         AND donor.primera_recepcion < (CURRENT_DATE - INTERVAL '60 days'))
        OR
        -- baja rotación con stock alto
        (donor.proy_mes < 10 AND donor.stock_disponible >= 15
         AND donor.dias_cobertura > 60)
    )
    -- RECEPTOR: tiene demanda activa Y necesita más stock
    AND recip.proy_mes >= 5
    AND (
        recip.stock_disponible = 0
        OR (recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 30)
    )
    -- Que el receptor NO sea otro caso de exceso (evita transferir entre
    -- 2 sucursales que ambas tienen sobrante)
    AND NOT (recip.dias_cobertura > 60)
    -- Sanity: el SKU debe estar identificado
    AND donor.bsale_variant_id IS NOT NULL
ORDER BY
    -- 1° prioridad (urgentísimos primero), 2° impacto $ (mayor primero)
    CASE
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 30 THEN 1
        WHEN recip.stock_disponible = 0 AND recip.proy_mes >= 10 THEN 2
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 14 THEN 3
        WHEN recip.dias_cobertura IS NOT NULL AND recip.dias_cobertura < 30 THEN 4
        ELSE 5
    END ASC,
    (GREATEST(1, LEAST(
        CASE
            WHEN COALESCE(donor.proy_30d_reciente, 0) < 5 OR donor.unds_vendidas = 0
                THEN donor.stock_disponible::int
            ELSE FLOOR(GREATEST(0, donor.stock_disponible - donor.proy_mes))::int
        END,
        CEIL(GREATEST(0, recip.proy_mes * 2 - recip.stock_disponible))::int
    )) * COALESCE(pp_r.precio_prom, pp_d.precio_prom, 0)) DESC
"""


def generate() -> None:
    src_text = SRC.read_text(encoding="utf-8")

    # Cortamos al final de `cat_baseline` (la última CTE base que necesitamos).
    cat_marker = "cat_baseline AS ("
    idx = src_text.index(cat_marker)
    end = src_text.index("),", idx) + 2
    base_ctes = src_text[:end]

    # Reemplazamos el header de la base por el header de 08
    base_ctes = base_ctes.replace(
        "-- BASE COMPARTIDA de las matrices 04 / 04b / 05",
        "-- MATRIZ 90D BASE (heredada de _matriz_90d_base) — CTEs para 08_transferencias",
    )

    output = HEADER + "\n" + base_ctes + SELECT_06

    DST.write_text(output, encoding="utf-8")
    print(f"OK · Generado {DST.name}")
    print(f"   {len(output)} chars · {output.count(chr(10))+1} líneas")
    print(f"   CTEs base: {base_ctes.count(chr(10))+1} líneas heredadas de 04b")


if __name__ == "__main__":
    generate()
