"""
Fix P17 (2026-06-06): cambiar la cobertura usada en la clasificación de
"lifetime del lote" a "últimos 30 días reales" (con fallback al lifetime
cuando no hay datos recientes).

Cambios por archivo (04, 04b, 05):
1. En `metricas_reciente`: agregar columna `dias_cobertura_reciente` con la
   nueva fórmula (stock / vel_30d).
2. En la CASCADA de clasificación (CASE final del SELECT): reemplazar
   `dias_cobertura` por `dias_cobertura_reciente`.
3. En el SELECT FINAL (columnas devueltas al usuario): cambiar la fuente
   de "Días cobertura" para mostrar la reciente.

NO TOCAR:
- La CTE `metricas` donde se define `dias_cobertura` lifetime.
- La CTE `cat_baseline` (no usa dias_cobertura).
- La CTE `transferencias` del 04b (sigue usando lifetime, que es OK para
  detectar excedente sostenido).
"""
from __future__ import annotations
import sys, io, re
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = [
    ROOT / "app/kawii_matrix/sql/04_matriz_90d.sql",
    ROOT / "app/kawii_matrix/sql/04b_matriz_90d_jerarquico.sql",
    ROOT / "app/kawii_matrix/sql/05_matriz_operativa.sql",
]

# ─── PASO 1: agregar dias_cobertura_reciente a metricas_reciente ───
ADD_OLD = """        END AS proy_30d_reciente
    FROM metricas m
),"""

ADD_NEW = """        END AS proy_30d_reciente,
        -- ★ FIX P17 (2026-06-06): COBERTURA basada en velocidad RECIENTE.
        --   Cuando hay venta en los últimos 30d con stock, la cobertura
        --   refleja el ritmo de HOY, no del lote completo. Fallback al
        --   cálculo lifetime (m.dias_cobertura) si no hay datos recientes.
        --   Esto hace que SKUs acelerando se detecten más rápido como
        --   urgentes, y SKUs desacelerando muestren la realidad operativa.
        CASE
            WHEN m.unds_lote_total <= 0 THEN m.dias_cobertura
            WHEN (m.stock_disponible + m.stock_reservado) = 0 THEN 0
            WHEN m.unds_vendidas_30d > 0 AND m.dias_con_stock_30d > 0
                THEN LEAST(9999, CEIL(
                    (m.stock_disponible + m.stock_reservado) /
                    (m.unds_vendidas_30d::numeric / m.dias_con_stock_30d)
                ))::int
            ELSE m.dias_cobertura
        END AS dias_cobertura_reciente
    FROM metricas m
),"""


def find_classification_range(text: str) -> tuple[int, int]:
    """Encuentra el rango de la cascada de clasificación (entre 'SECCIÓN A'
    y la línea que cierra el CASE con 'END').
    """
    # Buscamos el comienzo: el comentario "SECCIÓN A · CASOS ESPECIALES"
    m_start = re.search(r"SECCIÓN A · CASOS ESPECIALES", text)
    if not m_start:
        raise ValueError("No se encontró 'SECCIÓN A' en el archivo")
    start = m_start.start()

    # Buscamos el final: la línea que cierra el CASE final
    # Patrón: 'END                       AS "Clasificación"'
    m_end = re.search(r"END\s+AS \"Clasificación\"", text[start:])
    if not m_end:
        raise ValueError("No se encontró END AS \"Clasificación\"")
    end = start + m_end.end()
    return start, end


def replace_in_range(text: str, start: int, end: int, old: str, new: str) -> tuple[str, int]:
    """Reemplaza `old` por `new` SOLO en el rango [start, end)."""
    section = text[start:end]
    count = section.count(old)
    section = section.replace(old, new)
    return text[:start] + section + text[end:], count


def apply(dry: bool = False) -> int:
    for f in SQL_FILES:
        print(f"━━━ {f.name} ━━━")
        text = f.read_text(encoding="utf-8")
        original = text

        # 1) Agregar columna
        if ADD_OLD in text:
            text = text.replace(ADD_OLD, ADD_NEW)
            print(f"  ✓ Agregado `dias_cobertura_reciente` a metricas_reciente")
        else:
            print(f"  ⚠ NO encontré el ancla de metricas_reciente — saltando")
            continue

        # 2) En la cascada de clasificación, reemplazar dias_cobertura por dias_cobertura_reciente
        start, end = find_classification_range(text)
        text, n_replaced = replace_in_range(
            text, start, end, "dias_cobertura", "dias_cobertura_reciente"
        )
        print(f"  ✓ Reemplazos en cascada de clasificación: {n_replaced}")

        # 3) En el SELECT final (después del END AS "Clasificación"), buscar la columna
        #    que muestra cobertura. Patrón típico: '"Días cobertura"' o '"Días Cob"'
        #    y reemplazar la fuente del valor.
        #    Ojo: esto puede haber MÚLTIPLES coincidencias. Hago un grep informativo.
        post_cascade = text[end:]
        cob_cols = re.findall(r'(\w+\.?\w*)\s+AS\s+"Días\s+[Cc]ob[^\"]*"', post_cascade)
        if cob_cols:
            print(f"  ℹ Columnas 'Días cobertura' encontradas en SELECT final: {cob_cols}")

        if not dry:
            f.write_text(text, encoding="utf-8")
            print(f"  → Escrito a disco · Δ {len(text) - len(original):+d} chars\n")
        else:
            print(f"  → DRY (no escrito)\n")

    return 0


if __name__ == "__main__":
    apply(dry="--dry" in sys.argv)
