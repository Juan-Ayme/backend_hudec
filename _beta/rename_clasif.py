"""
Script one-shot que aplica los 31 reemplazos de etiquetas de clasificación
en los 3 SQL (04, 04b, 05).

Diseño:
- (old, new) pairs ordenados por especificidad descendente (los más largos
  primero para evitar que un patrón corto matchee dentro de uno largo).
- Cada reemplazo es EXACTO: el old debe existir tal cual en el archivo,
  el new lo sustituye literalmente.
- Verifica al final que todos los reemplazos sucedieron (si un old no se
  encontró, se reporta como error).

Uso:
    python -m _beta.rename_clasif        # aplica
    python -m _beta.rename_clasif --dry  # solo reporta
"""
from __future__ import annotations
import sys
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = [
    ROOT / "app/kawii_matrix/sql/04_matriz_90d.sql",
    ROOT / "app/kawii_matrix/sql/04b_matriz_90d_jerarquico.sql",
    ROOT / "app/kawii_matrix/sql/05_matriz_operativa.sql",
]

# ─── 31 cambios de etiqueta ─────────────────────────────────────────────────
# Cada entry: (texto_old, texto_new). Buscar/reemplazar literal.
# Orden importa: los más largos primero para evitar matches anidados.
REPLACEMENTS: list[tuple[str, str]] = [
    # ════════════ Sección A: Casos especiales ════════════
    (
        "🌱 NUEVO: esperando ≥7d para evaluar rotación",
        "🌱 PRODUCTO NUEVO — ESPERAR: recién llegado (≤7d), aún no se puede evaluar rotación",
    ),
    (
        "✅ TEMPORADA CERRADA: vendió su campaña y se agotó — recomprar la próxima",
        "✅ TEMPORADA CERRADA OK — RECOMPRAR PRÓXIMA CAMPAÑA: estacional que vendió su ciclo y se agotó",
    ),
    (
        "📦 SOBRANTE DE CAMPAÑA: stock de temporada pasada — guardar para la próxima",
        "📦 SALDO DE TEMPORADA — GUARDAR: stock sobrante de campaña pasada, NO liquidar",
    ),
    (
        "⛔ PÉRDIDA TOTAL: casi sin ventas (<20%) — todo el stock se ajustó (revisar control físico)",
        "⛔ PÉRDIDA DE STOCK — REVISAR CONTROL FÍSICO: casi todo el stock se ajustó/perdió (mermas o robos)",
    ),
    (
        "⚠️ VENTAS CON PÉRDIDA: vendía pero también se perdió mucho (investigar control físico)",
        "⚠️ VENDIÓ Y SE PERDIÓ — INVESTIGAR: hay ventas pero también mermas grandes (revisar inventario)",
    ),
    # ════════════ Sección B: Stock=0, vendió bien ════════════
    (
        "🔥💎 EXITOSO ACTIVO: vendió todo lifetime con velocidad ≥10/mes Y sigue rotando — REPONER YA",
        "🔥 BESTSELLER ACTIVO — REPONER YA: vendió todo con demanda fuerte y sigue rotando — reposición urgente",
    ),
    (
        "💎 EXITOSO PASADO: vendió todo lifetime pero sin demanda reciente (evaluar antes de reponer)",
        "⏸️ BESTSELLER EN PAUSA — EVALUAR: vendió todo pero la demanda se enfrió, chequear si fue temporada",
    ),
    (
        "💎 EXITOSO OLVIDADO: vendió todo a buen ritmo pero >60d sin venta — REPONER YA",
        "💎 OPORTUNIDAD PERDIDA — REPONER YA: vendió bien y ya van +60d sin reabastecer (venta perdida diaria)",
    ),
    (
        "🐢 ROTACIÓN LENTA SANA: vendió todo lifetime a paso modesto (<10/mes) — reponer cantidades chicas",
        "🐢 LENTO PERO CONSTANTE — REPONER POCO: producto nicho que se agotó vendiendo despacio pero seguido",
    ),
    (
        "💤 DEMANDA EXTINTA: vendió todo lifetime pero >60d sin venta — no reponer",
        "💤 DEMANDA EXTINTA — NO REPONER: vendió todo pero +60d sin demanda (descatalogar)",
    ),
    # ════════════ Sección C: Stock=0, vendió poco ════════════
    (
        "🚨 QUIEBRE STOCK: alta rotación sin stock — ¡COMPRAR YA!",
        "🚨 QUIEBRE DE BESTSELLER — COMPRAR YA: alta rotación sin stock (cada día sin stock es venta perdida)",
    ),
    (
        "👻 AGOTADO POTENCIAL ACTIVO: vendió ≥50 lifetime y aún en demanda (reponer prioridad)",
        "✨ AGOTADO CON DEMANDA — REPONER: vendió ≥50 unds en su vida y la demanda continúa activa",
    ),
    (
        "💤 AGOTADO HISTÓRICO: vendió bien en vida pero demanda decayó (evaluar descatalogar)",
        "📉 EX-BESTSELLER ENFRIADO — EVALUAR: vendía bien pero la demanda cayó (ver si vale reabastecer)",
    ),
    (
        "🌿 PRODUCTO EMERGENTE: vendió ≥15 en 90d pero corto historial lifetime (evaluar reposición)",
        "🌿 PRODUCTO EMERGENTE — VIGILAR: vendió bien en 90d pero con historial corto (observar antes de reponer fuerte)",
    ),
    (
        "🪦 RESIDUO HISTÓRICO: producto antiguo sin rotación (descatalogar)",
        "🪦 PRODUCTO MUERTO — DESCATALOGAR: producto antiguo prácticamente sin rotación (sacar del catálogo)",
    ),
    (
        "🪦 AGOTADO MARGINAL: bajo volumen lifetime (<50 unds) — candidato a descatalogar",
        "🪦 BAJO VOLUMEN AGOTADO — DESCATALOGAR: vendió menos de 50 unds en toda su vida",
    ),
    (
        "👻 FALSO AGOTADO: baja rotación + sin stock (no priorizar reposición)",
        "👻 AGOTADO NO PRIORITARIO: sin stock pero la rotación era muy baja (no urgente reabastecer)",
    ),
    # ════════════ Sección D: Stock>0 sin ventas ════════════
    (
        "🔄 REABASTECIDO RECIENTE: nueva recep (≤14d) aún sin venta — esperar",
        "🔄 STOCK RECIÉN LLEGADO — ESPERAR: recepción nueva (≤14d) sin ventas todavía (normal, dejar madurar)",
    ),
    (
        "💀 MUERTO 90D: stock parado sin ventas (capital estancado)",
        "💀 STOCK PARADO 90 DÍAS — LIQUIDAR: hay stock pero no se mueve hace 3 meses (capital atrapado)",
    ),
    # ════════════ Sección E: Stock>0 con ventas ════════════
    (
        "👀 ALERTA VISUAL: stock 1-2 unds sin movimiento 16-59d (revisar visibilidad/vencimiento)",
        "👀 STOCK BAJO QUIETO — VERIFICAR EN TIENDA: 1-2 unds sin movimiento en semanas (chequear visibilidad/vencimiento)",
    ),
    (
        "🔄 REABASTECIDO ACTIVO: vende bien (cob aparente alta es por vel diluida)",
        "🔄 LOTE NUEVO VENDIENDO BIEN: llegó stock grande y ya rota — sano (la cobertura alta es por dilución)",
    ),
    (
        "🆕 RECIÉN REABASTECIDO: nuevo lote (≤7d) — esperar primera semana para evaluar",
        "🆕 RECIÉN REABASTECIDO — ESPERAR 1 SEMANA: lote nuevo (≤7d), todavía no se puede evaluar bien",
    ),
    (
        "📉 RITMO PERDIDO: vendió antes pero >45d sin venta — evaluar antes de reponer",
        "📉 RITMO PERDIDO — EVALUAR ANTES DE REPONER: vendía antes pero +45d sin venta (pensar si pausar)",
    ),
    (
        "💀 SALDO QUEMADO: lote casi sin movimiento reciente — liquidar saldo (no comprar más)",
        "💀 LOTE FRENADO — LIQUIDAR, NO COMPRAR MÁS: lote viejo con stock que ya casi no rota",
    ),
    (
        "🔥📉 ALTA ROTACIÓN DECAYENDO: vende mucho pero demanda cae (reducir reposición — usar Vel 30d)",
        "🔥📉 ROTACIÓN BAJANDO — REPONER MENOS: vende mucho pero menos que antes (usar ritmo nuevo, no histórico)",
    ),
    (
        "🔥 ALTA ROTACIÓN: vol ≥30/mes — prioridad de compra",
        "🔥 ALTA ROTACIÓN — PRIORIDAD DE COMPRA: vende ≥30/mes con poco stock (reposición urgente)",
    ),
    (
        "💫 ROTACIÓN ACTIVA: vol 10-29/mes — vende constante",
        "💫 ROTACIÓN ACTIVA — MANTENER FLUJO: vende 10-29/mes constante (reposición regular)",
    ),
    (
        "🟢 INVENTARIO SANO: cob 30-45d — ritmo normal",
        "🟢 INVENTARIO SANO — RITMO NORMAL: stock equilibrado con demanda (cob 30-45d, todo OK)",
    ),
    (
        "🧊📉 EXCESO LIQUIDAR: capital estancado + demanda cayendo (promocionar urgente)",
        "🧊📉 EXCESO + DEMANDA CAYENDO — PROMOCIONAR YA: demasiado stock Y la demanda se enfría",
    ),
    (
        "🧊 EXCESO DE INVENTARIO: capital estancado",
        "🧊 STOCK EXCESIVO — PROMOCIONAR: demasiado stock para la demanda actual (capital atrapado)",
    ),
    (
        "⚠️ STOCK CRÍTICO: poco stock + venta reciente (reponer aunque rotación baja)",
        "⚠️ POCO STOCK CON DEMANDA — REPONER: cobertura baja con rotación lenta pero activa (evitar quiebre)",
    ),
    (
        "📈 BAJO VOLUMEN EN ALZA: vende poco pero la tendencia es positiva — observar, no liquidar",
        "📈 VENDIENDO MÁS QUE ANTES — VIGILAR: vende poco pero la tendencia es positiva (observar, no liquidar)",
    ),
    (
        "🐢 BAJA ROTACIÓN: proy <10 unds/mes — bajar pedido / revisar surtido",
        "🐢 BAJA ROTACIÓN — PEDIR MENOS: vende menos de 10/mes (bajar próximo pedido, revisar surtido)",
    ),
    # Catch-all
    (
        "⚖️ EN ANÁLISIS: caso no cubierto por reglas — revisar manualmente",
        "⚖️ CASO ATÍPICO — REVISAR MANUAL: caso no cubierto por reglas (analizar a mano)",
    ),
]


def apply(dry: bool = False) -> int:
    """Aplica los reemplazos. Devuelve exit code: 0 si todo OK, 1 si hubo error."""
    print(f"Aplicando {len(REPLACEMENTS)} reemplazos en {len(SQL_FILES)} archivos SQL")
    print(f"Modo: {'DRY-RUN' if dry else 'EJECUTAR'}\n")

    total_errors = 0
    for f in SQL_FILES:
        print(f"━━━ {f.name} ━━━")
        text = f.read_text(encoding="utf-8")
        original_len = len(text)
        missing = []
        applied = 0
        for old, new in REPLACEMENTS:
            if old in text:
                text = text.replace(old, new)
                applied += 1
            else:
                missing.append(old[:60] + "...")
        if missing:
            print(f"  ⚠ {len(missing)} reemplazos NO encontrados (puede ser OK si la regla no está en este archivo):")
            for m in missing:
                print(f"    · {m}")
                total_errors += 1
        print(f"  ✓ Aplicados: {applied}/{len(REPLACEMENTS)}  |  Δ tamaño: {len(text) - original_len:+d} chars")
        if not dry:
            f.write_text(text, encoding="utf-8")
            print(f"  → Escrito a disco\n")
        else:
            print(f"  → DRY (no escrito)\n")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    sys.exit(apply(dry=dry))
