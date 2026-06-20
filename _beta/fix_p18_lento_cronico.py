"""
Fix P18 (2026-06-08): 3 cambios coordinados en los 3 SQL principales.

1. **Renombrar columna** `"Días desde Últ. Recep"` → `"Llegó hace (días)"`
   (más intuitivo para el usuario).

2. **Agregar columna nueva** `"Sell-through Lote %"` después de "Vend Lote Total".
   Fórmula: `unds_lote_total / NULLIF(unds_lote_total + stock_disponible, 0) * 100`.
   Mide cuánto del lote actual ya se vendió.

3. **Agregar caja nueva** `🪦 LENTO CRÓNICO — NO REPONER` en la cascada de
   clasificación, antes de POCO STOCK CON DEMANDA. Condiciones:
   - stock > 0
   - edad_dias ≥ 180   (más de 6 meses en catálogo)
   - proy_mes < 5      (vel reciente baja)
   - unds_vendidas_lifetime < 60  (vendió poco en TODA su vida)

   Captura productos como GFQQ-240437 REL DE PARED (26 unds en 10 meses).
"""
from __future__ import annotations
import sys, io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = [
    ROOT / "app/kawii_matrix/sql/04_matriz_90d.sql",
    ROOT / "app/kawii_matrix/sql/04b_matriz_90d_jerarquico.sql",
    ROOT / "app/kawii_matrix/sql/05_matriz_operativa.sql",
]

# ─── 1. Renombrar columna ───
RENAME_OLD = 'dias_desde_ultima_recep  AS "Días desde Últ. Recep",'
RENAME_NEW = 'dias_desde_ultima_recep  AS "Llegó hace (días)",'

# ─── 2. Insertar columna Sell-through Lote % ───
# Anchor: después de "Vend Lote Total" antes de "Últ. Venta Lote"
ST_OLD = '''trim_scale(ROUND(unds_lote_total, 2))    AS "Vend Lote Total",
    ult_venta_lote                           AS "Últ. Venta Lote",'''

ST_NEW = '''trim_scale(ROUND(unds_lote_total, 2))    AS "Vend Lote Total",
    -- ★ FIX P18: sell-through del lote actual. Mide cuánto del lote
    --   recibido ya se vendió. Útil junto con "Llegó hace (días)" para
    --   detectar lotes lentos (alto ST con muchos días = caso GFQQ-240437).
    ROUND((unds_lote_total / NULLIF(unds_lote_total + stock_disponible, 0) * 100)::numeric, 1)
                                             AS "Sell-through Lote %",
    ult_venta_lote                           AS "Últ. Venta Lote",'''

# ─── 3. Insertar caja LENTO CRÓNICO antes de POCO STOCK CON DEMANDA ───
LC_OLD = '''        -- ⚠️ STOCK CRÍTICO: cob <30d + velocidad baja PERO venta reciente.'''

LC_NEW = '''        -- 🪦 LENTO CRÓNICO: producto que lleva mucho tiempo en catálogo
        --    (≥180d) pero vendió poco en toda su vida (<60 unds totales) Y
        --    con velocidad reciente baja (<5/mes). NO vale reponer aunque
        --    aparente "demanda activa" por unas pocas ventas recientes.
        --    P18 (2026-06-08): caso testigo GFQQ-240437 REL DE PARED MAG
        --    (26 unds en 10 meses → vel ~3/mes, lifetime). El sistema lo
        --    veía como ⚠ POCO STOCK CON DEMANDA por la vel reciente de los
        --    últimos 30d, pero el patrón lifetime es claramente lento crónico.
        WHEN stock_disponible > 0
             AND COALESCE(edad_dias, 0) >= 180
             AND COALESCE(proy_mes, 0) < 5
             AND COALESCE(unds_vendidas_lifetime, 0) < 60
             THEN '🪦 LENTO CRÓNICO — NO REPONER: vende <5/mes en toda su vida (no vale la pena reabastecer)'

        -- ⚠️ STOCK CRÍTICO: cob <30d + velocidad baja PERO venta reciente.'''


def apply(dry: bool = False) -> int:
    errors = 0
    for f in SQL_FILES:
        print(f"━━━ {f.name} ━━━")
        text = f.read_text(encoding="utf-8")
        original_len = len(text)

        # 1. Rename
        if RENAME_OLD in text:
            text = text.replace(RENAME_OLD, RENAME_NEW)
            print(f"  ✓ Renombrado 'Días desde Últ. Recep' → 'Llegó hace (días)'")
        else:
            print(f"  ⚠ Anchor de rename NO encontrado")
            errors += 1

        # 2. Sell-through column
        if ST_OLD in text:
            text = text.replace(ST_OLD, ST_NEW)
            print(f"  ✓ Agregada columna 'Sell-through Lote %'")
        else:
            print(f"  ⚠ Anchor de sell-through NO encontrado")
            errors += 1

        # 3. Lento crónico rule
        if LC_OLD in text:
            text = text.replace(LC_OLD, LC_NEW)
            print(f"  ✓ Agregada caja 🪦 LENTO CRÓNICO antes de STOCK CRÍTICO")
        else:
            print(f"  ⚠ Anchor de lento crónico NO encontrado")
            errors += 1

        if not dry:
            f.write_text(text, encoding="utf-8")
            print(f"  → Escrito · Δ {len(text) - original_len:+d} chars\n")
        else:
            print(f"  → DRY (no escrito)\n")
    return errors


if __name__ == "__main__":
    sys.exit(apply(dry="--dry" in sys.argv))
