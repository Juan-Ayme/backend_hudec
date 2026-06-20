"""
Simulación del cambio: threshold de velocidad de FIJO (10/mes) a ADAPTATIVO por categoría.

Nueva fórmula:  umbral = MAX(3, LEAST(10, avg_proy_cat * 0.5))
  - MAX(3, ...):  piso absoluto — bajo este nivel no califica para "exitoso"
  - LEAST(10, ...): tope: categorías de alta rotación mantienen el 10 actual
  - avg_proy_cat * 0.5: para categorías nicho, baja el umbral al 50% del promedio

Reporta:
  - Distribución de avg_proy por categoría (¿hay categorías nicho?)
  - Cuántos productos se mueven de qué a qué (matriz de migración)
  - SKUs específicos que ya validamos (FXT-2289, MS-2697, SKY ESPUMA, B1045, etc.)
  - Posibles efectos colaterales
"""
import asyncio
import io
import statistics
import sys
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from sqlalchemy import text
from app.database import async_session_maker
from app.kawii_matrix import service

# Inyectar columnas internas que necesitamos para reclasificar
DEBUG = """
    stock_disponible AS "_stock",
    unds_vendidas AS "_v90",
    unds_recibidas_90d AS "_r90",
    unds_vendidas_lifetime AS "_vL",
    unds_recibidas_lifetime AS "_rL",
    unds_consumidas_lifetime AS "_cL",
    unds_trasladadas_lifetime AS "_tL",
    proy_mes AS "_proy",
    dias_sin_venta_90d AS "_dsv",
    dias_desde_ultima_recep AS "_dur",
    edad_dias AS "_edad",
    dias_cobertura AS "_cob",
    pct_frecuencia AS "_freq",
    v_recent_45d AS "_vr45",
    v_old_45d AS "_vo45",
    vel_30d AS "_v30",
    primera_recepcion AS "_1arec",
    department_id AS "_dept_id",
"""
ANCHOR = 'dias_sin_venta_90d::int                  AS "Días sin Vender",'


def _f(v):
    return float(v or 0)


def _sell_through(r):
    rL = _f(r["_rL"])
    if rL == 0:
        return 0
    return (_f(r["_vL"]) + _f(r["_cL"]) + _f(r["_tL"])) / rL


def reclasificar(row, umbral_proy: float, umbral_alta_rot: float = 30) -> str:
    """Aplica la misma cascada del SQL pero con el umbral de velocidad parametrizado."""
    stock = _f(row["_stock"])
    v90 = _f(row["_v90"])
    r90 = _f(row["_r90"])
    vL = _f(row["_vL"])
    rL = _f(row["_rL"])
    cL = _f(row["_cL"])
    tL = _f(row["_tL"])
    proy = _f(row["_proy"])
    dsv = row["_dsv"]
    dsv_n = dsv if dsv is not None else 9999
    edad = row["_edad"]
    dur = row["_dur"]
    cob = row["_cob"]
    freq = _f(row["_freq"])
    vr45 = _f(row["_vr45"])
    vo45 = _f(row["_vo45"])
    v30 = row["_v30"]
    primera = row["_1arec"]
    sell = (vL + cL + tL) / rL if rL > 0 else 0

    # ─── A · Casos especiales ───────────────────────────────────────
    if primera and edad is not None and edad <= 7 and v90 < 15:
        return "🌱 NUEVO"
    if stock == 0 and rL >= 5 and cL > tL:
        if cL >= rL * 0.50 and vL < rL * 0.20:
            return "⛔ PÉRDIDA TOTAL"
        if cL > vL and rL * 0.20 <= vL < rL * 0.50:
            return "⚠️ VENTAS CON PÉRDIDA"

    # ─── B · Stock=0 + vendió todo ──────────────────────────────────
    if stock == 0 and rL >= 2 and sell >= 0.80:
        if proy >= umbral_proy and dsv_n <= 30:
            return "🔥💎 EXITOSO ACTIVO"
        if proy >= umbral_proy and dsv_n <= 60:
            return "💎 EXITOSO PASADO"
        if proy >= umbral_proy and dsv_n > 60:
            return "💎 EXITOSO OLVIDADO"  # ★ caja nueva (que ya íbamos a agregar)
        if proy < umbral_proy and dsv_n <= 60:
            return "🐢 ROTACIÓN LENTA SANA"
        return "💤 DEMANDA EXTINTA"

    # ─── C · Stock=0 + vendió poco ──────────────────────────────────
    if stock == 0:
        if dsv_n <= 14 and proy >= umbral_proy:
            return "🚨 QUIEBRE STOCK"
        if dsv_n >= 15 and vL >= 50 and v90 >= 5:
            return "👻 AGOTADO POTENCIAL ACTIVO"
        if dsv_n >= 15 and vL >= 50:
            return "💤 AGOTADO HISTÓRICO"
        if dsv_n >= 15 and v90 >= 15:
            return "🌿 PRODUCTO EMERGENTE"
        if v90 == 0 and r90 > 0 and vL < 50:
            return "❓ RECIBIDO Y NO VENDIDO"
        if stock == 0 and dsv_n >= 15:
            return "🪦 AGOTADO MARGINAL"
        if proy < umbral_proy:
            return "👻 FALSO AGOTADO"

    # ─── D · Stock>0 + sin ventas ───────────────────────────────────
    if stock > 0 and v90 == 0:
        if dur is not None and dur <= 14:
            return "🔄 REABASTECIDO RECIENTE"
        return "💀 MUERTO 90D"

    # ─── E · Stock>0 + con ventas ───────────────────────────────────
    if stock > 0 and v90 > 0:
        if 1 <= stock <= 2 and dsv is not None and 16 <= dsv <= 59:
            return "👀 ALERTA VISUAL"
        if dur is not None and dur <= 14 and cob is not None and cob > 45:
            v30f = _f(v30)
            if v30f >= 2 and (v30f / max(1, dur)) * 30 >= umbral_proy:
                return "🔄 REABASTECIDO ACTIVO"
            if vL >= 10 and rL > 0 and vL / rL >= 0.70:
                return "🔄 REABASTECIDO ACTIVO"
        if cob is not None:
            if proy >= umbral_alta_rot and cob < 30:
                if vr45 > 0 and vo45 > 0 and vr45 < vo45 * 0.7:
                    return "🔥📉 ALTA ROTACIÓN DECAYENDO"
                return "🔥 ALTA ROTACIÓN"
            if proy >= umbral_proy and cob < 30:
                return "💫 ROTACIÓN ACTIVA"
            if proy >= umbral_proy and 30 <= cob <= 45:
                return "🟢 INVENTARIO SANO"
            if proy >= umbral_proy and cob > 45:
                if vr45 > 0 and vo45 > 0 and vr45 < vo45 * 0.7:
                    return "🧊📉 EXCESO LIQUIDAR"
                return "🧊 EXCESO DE INVENTARIO"
            if cob < 30 and proy < umbral_proy:
                if v30 is not None and _f(v30) > 0:
                    return "⚠️ STOCK CRÍTICO"
                return "⚠️ STOCK CRÍTICO BAJA ROT"
        if proy < umbral_proy and vr45 > 0:
            if (vo45 > 0 and vr45 > vo45 * 1.5) or (
                vo45 == 0 and edad is not None and edad > 30 and rL > 0 and vL >= rL * 0.50
            ):
                return "📈 BAJO VOLUMEN EN ALZA"
        if proy < umbral_proy:
            return "🐢 BAJA ROTACIÓN"

    return "⚖️ EN ANÁLISIS"


async def main():
    sql = service._load_sql("04b").replace(ANCHOR, ANCHOR + "\n" + DEBUG, 1)
    async with async_session_maker() as db:
        params = service._get_query_params()
        try:
            from app.routers.config_admin import get_exclusions, get_seasonal
            ex = await get_exclusions(db)
            params["excluded_departments"] = ex["departments"]
            params["excluded_categories"] = ex["categories"]
            params["seasonal_departments"] = await get_seasonal(db)
        except Exception:
            pass
        await db.execute(text("SET LOCAL enable_nestloop = off"))
        await db.execute(text("SET LOCAL timezone = 'UTC'"))
        res = await db.execute(text(sql), params)
        cols = list(res.keys())
        rows = [dict(zip(cols, r)) for r in res.fetchall()]

    clave_sql = next(c for c in cols if "lasificaci" in c.lower())
    for r in rows:
        r["_clasif_sql"] = str(r.get(clave_sql) or "").split(":")[0].strip()

    # ─── Calcular avg_proy por CATEGORÍA ──────────────────────────────
    by_cat = defaultdict(list)
    for r in rows:
        cat = (r.get("Categoría") or "(sin)").strip()
        proy = _f(r["_proy"])
        if proy > 0:
            by_cat[cat].append(proy)

    avg_cat = {cat: sum(v) / len(v) for cat, v in by_cat.items() if len(v) >= 3}

    # Mostrar distribución de avg_cat (para entender el rango)
    print("═" * 70)
    print("AVG proy_mes POR CATEGORÍA (top 10 más altas y bottom 10 más bajas)")
    print("═" * 70)
    sorted_cats = sorted(avg_cat.items(), key=lambda x: -x[1])
    print("  TOP 10 (alta rotación promedio):")
    for cat, avg in sorted_cats[:10]:
        print(f"    {avg:>7.1f}/mes  {cat[:50]}  ({len(by_cat[cat])} SKUs)")
    print("  BOTTOM 10 (baja rotación promedio):")
    for cat, avg in sorted_cats[-10:]:
        print(f"    {avg:>7.1f}/mes  {cat[:50]}  ({len(by_cat[cat])} SKUs)")

    # ─── Aplicar reclasificación nueva ────────────────────────────────
    for r in rows:
        cat = (r.get("Categoría") or "(sin)").strip()
        avg = avg_cat.get(cat, 10)  # si no hay avg confiable, usa 10
        # Threshold adaptativo: MAX(3, LEAST(10, avg * 0.5))
        umbral = max(3.0, min(10.0, avg * 0.5))
        r["_umbral_adapt"] = round(umbral, 1)
        r["_clasif_new_fija"] = reclasificar(r, umbral_proy=10)  # baseline con umbral fijo (debería = SQL)
        r["_clasif_new_adapt"] = reclasificar(r, umbral_proy=umbral)

    # ─── Sanity check: la reclasificación con umbral=10 debería coincidir con SQL ─
    print()
    print("═" * 70)
    print("SANITY CHECK · Python con umbral=10 vs SQL actual")
    print("═" * 70)
    matches = sum(1 for r in rows if r["_clasif_sql"].split(":")[0].strip() == r["_clasif_new_fija"])
    print(f"  Coincidencias: {matches}/{len(rows)} ({matches*100/len(rows):.1f}%)")
    print("  (Si es <95% mi reimplementación tiene bugs — ajustar antes de seguir)")

    # ─── Migraciones por el umbral ADAPTATIVO ─────────────────────────
    print()
    print("═" * 70)
    print("MIGRACIONES con umbral ADAPTATIVO (vs umbral fijo=10)")
    print("═" * 70)
    moves = Counter(
        (r["_clasif_new_fija"], r["_clasif_new_adapt"])
        for r in rows
        if r["_clasif_new_fija"] != r["_clasif_new_adapt"]
    )
    total_movidos = sum(moves.values())
    print(f"  Total productos que cambian de caja: {total_movidos} de {len(rows)} ({total_movidos*100/len(rows):.1f}%)")
    print()
    print("  Top 15 movimientos:")
    for (old, new), n in moves.most_common(15):
        print(f"    {n:4}  {old[:30]:30} -> {new}")

    # ─── Distribución global de la nueva clasificación ────────────────
    print()
    print("═" * 70)
    print("DISTRIBUCIÓN FINAL (con umbral adaptativo)")
    print("═" * 70)
    counts_new = Counter(r["_clasif_new_adapt"] for r in rows)
    for lab, n in counts_new.most_common():
        old_n = sum(1 for r in rows if r["_clasif_new_fija"] == lab)
        delta = n - old_n
        sign = "+" if delta > 0 else ""
        print(f"  {n:5} ({sign}{delta:>+4})  {lab}")

    # ─── Casos críticos que el usuario ya validó ──────────────────────
    print()
    print("═" * 70)
    print("CHECK · SKUs ya validados (no deberían empeorar)")
    print("═" * 70)
    casos = [
        "FXT-2289", "MS-2697", "B1045", "74914422901242",
        "74931689020221", "300050845", "EP-9534", "KD-2605",
        "DA-180-1", "GF-3414", "CF-18/02",
    ]
    for sku in casos:
        for r in rows:
            if str(r.get("Código SKU")) == sku:
                suc = str(r.get("Sucursal", "")).replace("KAWII ", "")[:9]
                cat = (r.get("Categoría") or "")[:25]
                old = r["_clasif_new_fija"]
                new = r["_clasif_new_adapt"]
                arrow = " ✓" if old == new else " ★"
                print(
                    f"  {sku:18}{suc:9} cat={cat:25} "
                    f"proy={_f(r['_proy']):>6.1f} umbral={r['_umbral_adapt']:>4.1f} | "
                    f"{old[:25]:25} -> {new[:25]}{arrow}"
                )


if __name__ == "__main__":
    asyncio.run(main())
