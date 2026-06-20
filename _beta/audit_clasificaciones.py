"""
Auditoría P20 (2026-06-10): verificación independiente de las clasificaciones.

Método:
1. Ejecuta el SQL 04b con las variables INTERNAS de la cascada expuestas
   como columnas extra (_stock, _vlife, _proy, _umbral, etc.).
2. Replica la cascada de clasificación COMPLETA en Python (33 cajas,
   mismas condiciones, mismo orden, misma semántica NULL de SQL).
3. Compara la caja predicha por la réplica vs la que eligió el SQL.
   0 divergencias = la cascada se aplica exactamente como está documentada.
4. Chequeos matemáticos adicionales:
   - Sell-through Lote % = lote/(lote+stock)*100
   - Vida lote = llegó_hace + cobertura_reciente
   - Cobertura 'Agotado' ⟺ stock=0
   - P7: stock=0 + ventas 90d>0 ⇒ Tendencia '💤 Agotado'
   - Coherencia semántica de cajas (ej: OPORTUNIDAD PERDIDA ⇒ dsv>60)

Uso:  python -m _beta.audit_clasificaciones
"""
from __future__ import annotations
import asyncio, io, re, sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SQL_PATH = ROOT / "app/kawii_matrix/sql/04b_matriz_90d_jerarquico.sql"

AUDIT_COLS = """,
    stock_disponible            AS "_stock",
    unds_vendidas               AS "_v90",
    unds_recibidas_90d          AS "_r90",
    unds_vendidas_lifetime      AS "_vlife",
    unds_recibidas_lifetime     AS "_rlife",
    unds_consumidas_lifetime    AS "_clife",
    unds_trasladadas_lifetime   AS "_tlife",
    unds_vendidas_30d           AS "_v30",
    proy_mes                    AS "_proy",
    proy_30d_reciente           AS "_proy30rec",
    vel_30d                     AS "_vel30",
    dias_sin_venta_90d          AS "_dsv",
    edad_dias                   AS "_edad",
    dias_desde_ultima_recep     AS "_llego",
    dias_cobertura_reciente     AS "_cobrec",
    v_recent_45d                AS "_vrec45",
    v_old_45d                   AS "_vold45",
    GREATEST(3, LEAST(10, COALESCE(cb.avg_proy_cat, 10) * 0.5)) AS "_umbral",
    (primera_recepcion >= NOW() - INTERVAL '7 days')            AS "_es_nuevo7",
    (department_id = ANY(CAST(:seasonal_departments AS int[]))) AS "_es_estacional"
"""


def f(v) -> float | None:
    """Decimal/None → float/None."""
    return None if v is None else float(v)


def co(v, default=0.0) -> float:
    """COALESCE."""
    return default if v is None else float(v)


def replica_cascada(r: dict) -> str:
    """Réplica EXACTA de la cascada del SQL. Devuelve el prefijo de la caja.
    Semántica NULL de SQL: comparación con None = False (salvo COALESCE)."""
    stock = co(r["_stock"])
    v90 = co(r["_v90"])
    r90 = co(r["_r90"])
    vlife = co(r["_vlife"])
    rlife = co(r["_rlife"])
    clife = co(r["_clife"])
    tlife = co(r["_tlife"])
    v30 = f(r["_v30"])
    proy = f(r["_proy"])
    proy30rec = f(r["_proy30rec"])
    vel30 = f(r["_vel30"])
    dsv = f(r["_dsv"])
    edad = f(r["_edad"])
    llego = f(r["_llego"])
    cobrec = f(r["_cobrec"])
    vrec = f(r["_vrec45"])
    vold = f(r["_vold45"])
    umbral = co(r["_umbral"], 10.0)
    es_nuevo7 = bool(r["_es_nuevo7"])
    es_estacional = bool(r["_es_estacional"])

    dsv9 = dsv if dsv is not None else 9999.0
    llego9 = llego if llego is not None else 9999.0

    # ── Sección A ──
    if es_nuevo7 and v90 < 15:
        return "🌱 PRODUCTO NUEVO"
    if es_estacional and dsv9 > 30 and stock == 0 and vlife >= 1:
        return "✅ TEMPORADA CERRADA"
    if es_estacional and dsv9 > 30 and stock > 0:
        return "📦 SALDO DE TEMPORADA"
    if (stock == 0 and rlife >= 5 and clife >= rlife * 0.50
            and vlife < rlife * 0.20 and clife > tlife):
        return "⛔ PÉRDIDA DE STOCK"
    if (stock == 0 and rlife >= 5 and clife > vlife
            and vlife >= rlife * 0.20 and vlife < rlife * 0.50 and clife > tlife):
        return "⚠️ VENDIÓ Y SE PERDIÓ"

    # ── Sección B (stock=0, sell-through lifetime ≥80%) ──
    st80 = stock == 0 and rlife >= 2 and (vlife + clife + tlife) >= rlife * 0.80
    if st80 and proy is not None and proy >= umbral and dsv9 <= 30:
        return "🔥 BESTSELLER ACTIVO"
    if st80 and proy is not None and proy >= umbral and dsv9 <= 60:
        return "⏸️ BESTSELLER AGOTADO"  # P21: antes BESTSELLER EN PAUSA
    if st80 and proy is not None and proy >= umbral:
        return "💎 OPORTUNIDAD PERDIDA"
    if st80 and dsv9 <= 60:
        return "🐢 LENTO PERO CONSTANTE"
    if st80:
        return "💤 DEMANDA EXTINTA"

    # ── Sección C (stock=0, sell-through <80%) ──
    if stock == 0 and dsv9 <= 14 and proy is not None and proy >= umbral:
        return "🚨 QUIEBRE DE BESTSELLER"
    if stock == 0 and dsv9 >= 15 and vlife >= 50 and v90 >= 5:
        return "✨ AGOTADO CON DEMANDA"
    if stock == 0 and dsv9 >= 15 and vlife >= 50:
        return "📉 EX-BESTSELLER ENFRIADO"
    if stock == 0 and dsv9 >= 15 and v90 >= 15:
        return "🌿 PRODUCTO EMERGENTE"
    if (stock == 0 and v90 == 0 and 1 <= r90 <= 4
            and edad is not None and edad > 180 and vlife < 50):
        return "🪦 PRODUCTO MUERTO"
    if stock == 0 and v90 == 0 and r90 > 0 and vlife < 50:
        return "❓ RECIBIDO Y NO VENDIDO"
    if stock == 0 and dsv9 >= 15:
        return "🪦 BAJO VOLUMEN AGOTADO"
    if stock == 0 and proy is not None and proy < umbral:
        return "👻 AGOTADO NO PRIORITARIO"

    # ── Sección D (stock>0, sin ventas 90d) ──
    if stock > 0 and v90 == 0 and llego is not None and llego <= 14:
        return "🔄 STOCK RECIÉN LLEGADO"
    if stock > 0 and v90 == 0:
        return "💀 STOCK PARADO 90 DÍAS"

    # ── Sección E (stock>0, con ventas) ──
    if 1 <= stock <= 2 and dsv is not None and 16 <= dsv <= 59:
        return "👀 STOCK BAJO QUIETO"
    if (stock > 0 and llego is not None and llego <= 14
            and cobrec is not None and cobrec > 45
            and ((v30 is not None and v30 >= 2 and (v30 / max(1.0, llego)) * 30 >= 10)
                 or (vlife >= 10 and rlife > 0 and vlife >= rlife * 0.70))):
        return "🔄 LOTE NUEVO VENDIENDO BIEN"
    if (stock > 0 and llego is not None and llego <= 7 and vlife >= 1
            and cobrec is not None and cobrec > 45):
        return "🆕 RECIÉN REABASTECIDO"
    if stock > 0 and v90 > 0 and dsv9 > 45:
        return "📉 RITMO PERDIDO"
    if (stock >= 5 and proy is not None and proy >= 10
            and co(proy30rec) < 5 and co(edad) >= 90):
        return "💀 LOTE FRENADO"
    if (stock > 0 and proy is not None and proy >= 30
            and cobrec is not None and cobrec < 30
            and vrec is not None and vrec > 0 and vold is not None and vold > 0
            and vrec < vold * 0.7):
        return "🔥📉 ROTACIÓN BAJANDO"
    if (stock > 0 and proy is not None and proy >= 30
            and cobrec is not None and cobrec < 30):
        return "🔥 ALTA ROTACIÓN"
    if (stock > 0 and proy is not None and proy >= umbral
            and cobrec is not None and cobrec < 30):
        return "💫 ROTACIÓN ACTIVA"
    if (stock > 0 and proy is not None and proy >= umbral
            and cobrec is not None and 30 <= cobrec <= 45):
        return "🟢 INVENTARIO SANO"
    if (stock > 0 and proy is not None and proy >= umbral
            and cobrec is not None and cobrec > 45
            and vrec is not None and vrec > 0 and vold is not None and vold > 0
            and vrec < vold * 0.7 and llego9 > 7):
        return "🧊📉 EXCESO + DEMANDA CAYENDO"
    if (stock > 0 and proy is not None and proy >= umbral
            and cobrec is not None and cobrec > 45 and llego9 > 7):
        return "🧊 STOCK EXCESIVO"
    if (stock > 0 and co(edad) >= 180 and llego9 >= 30 and dsv9 >= 8  # P21 guard
            and co(vlife) < 60
            and edad is not None and edad > 0 and (co(vlife) / edad * 30) < 5):
        return "🪦 LENTO CRÓNICO"
    if (cobrec is not None and cobrec < 30 and proy is not None and proy < umbral
            and vel30 is not None and vel30 > 0):
        return "⚠️ POCO STOCK CON DEMANDA"
    if (proy is not None and proy < umbral and vrec is not None and vrec > 0
            and (cobrec if cobrec is not None else 9999) <= 45
            and ((vold is not None and vold > 0 and vrec > vold * 1.5)
                 or (vold is not None and vold == 0 and edad is not None and edad > 30
                     and rlife > 0 and vlife >= rlife * 0.50))):
        return "📈 VENDIENDO MÁS QUE ANTES"
    if proy is not None and proy < umbral:
        return "🐢 BAJA ROTACIÓN"

    return "⚖️ CASO ATÍPICO"


async def main() -> None:
    from sqlalchemy import text
    from app.database import async_session_maker
    from app.kawii_matrix.service import _get_query_params

    sql = SQL_PATH.read_text(encoding="utf-8")
    sql2, n = re.subn(
        r'(END\s+AS "Clasificación")\s*\n\s*FROM metricas_reciente m',
        r"\1" + AUDIT_COLS + "\nFROM metricas_reciente m",
        sql, count=1,
    )
    assert n == 1, "No se pudo inyectar las columnas de auditoría"

    async with async_session_maker() as db:
        params = _get_query_params()
        try:
            from app.routers.config_admin import get_exclusions, get_seasonal
            excl = await get_exclusions(db)
            params["excluded_departments"] = excl["departments"]
            params["excluded_categories"] = excl["categories"]
            params["seasonal_departments"] = await get_seasonal(db)
        except Exception:
            pass
        await db.execute(text("SET LOCAL enable_nestloop = off"))
        await db.execute(text("SET LOCAL timezone = 'UTC'"))
        res = await db.execute(text(sql2), params)
        cols = list(res.keys())
        rows = [dict(zip(cols, r)) for r in res.fetchall()]

    print(f"═══ AUDITORÍA 04b · {len(rows)} filas ═══\n")

    # ── 1. Réplica de cascada vs SQL ──
    mismatches = []
    for r in rows:
        esperado = replica_cascada(r)
        real = (r["Clasificación"] or "").split("—")[0].split(":")[0].strip()
        if not real.startswith(esperado):
            mismatches.append((r, esperado, real))
    print(f"1. CASCADA REPLICADA: {len(rows) - len(mismatches)}/{len(rows)} coinciden · "
          f"{len(mismatches)} divergencias")
    for r, esp, real in mismatches[:15]:
        print(f"   ✗ {r['Código SKU']} {r['Sucursal'][:12]}: SQL='{real}' réplica='{esp}'"
              f"  (stk={r['_stock']} proy={r['_proy']} cob={r['_cobrec']} dsv={r['_dsv']}"
              f" edad={r['_edad']} vlife={r['_vlife']})")

    # ── 2. Matemática de columnas derivadas ──
    bad_st, bad_vida, bad_cob = [], [], []
    for r in rows:
        lote, stock = co(r["Vend Lote Total"]), co(r["_stock"])
        st = f(r["Sell-through Lote %"])
        if lote + stock > 0 and st is not None:
            exp = round(lote / (lote + stock) * 100, 1)
            if abs(st - exp) > 0.11:
                bad_st.append((r, st, exp))
        vida, llego, cobrec = f(r["Vida lote (días)"]), f(r["_llego"]), f(r["_cobrec"])
        if llego is not None:
            exp_v = llego + (cobrec if cobrec is not None else 0)
            if vida is None or abs(vida - exp_v) > 0.5:
                bad_vida.append((r, vida, exp_v))
        cob_txt = str(r["Cobertura"] or "")
        if stock == 0 and cob_txt != "Agotado":
            bad_cob.append((r, cob_txt, "Agotado"))
        elif stock > 0 and cob_txt == "Agotado":
            bad_cob.append((r, cob_txt, "≠Agotado"))
    print(f"\n2. MATEMÁTICA DERIVADA:")
    print(f"   Sell-through Lote %:  {len(bad_st)} errores")
    for r, got, exp in bad_st[:5]:
        print(f"     ✗ {r['Código SKU']}: muestra {got}, esperado {exp}")
    print(f"   Vida lote (días):     {len(bad_vida)} errores")
    for r, got, exp in bad_vida[:5]:
        print(f"     ✗ {r['Código SKU']} {r['Sucursal'][:12]}: muestra {got}, esperado {exp} "
              f"(llegó={r['_llego']} cob={r['_cobrec']})")
    print(f"   Cobertura vs stock:   {len(bad_cob)} errores")
    for r, got, exp in bad_cob[:5]:
        print(f"     ✗ {r['Código SKU']}: '{got}' con stock={r['_stock']}")

    # ── 3. P7: tendencia de agotados ──
    bad_tend = [r for r in rows
                if co(r["_stock"]) == 0 and co(r["_v90"]) > 0
                and "Agotado" not in str(r["Tendencia"]) ]
    print(f"\n3. P7 TENDENCIA AGOTADOS: {len(bad_tend)} violaciones "
          f"(stock=0 + ventas 90d sin '💤 Agotado')")
    for r in bad_tend[:5]:
        print(f"     ✗ {r['Código SKU']} {r['Sucursal'][:12]}: tend='{r['Tendencia']}' v90={r['_v90']}")

    # ── 4. Coherencia semántica por caja ──
    sem = []
    for r in rows:
        c = r["Clasificación"] or ""
        dsv9 = co(r["_dsv"], 9999)
        stock = co(r["_stock"])
        if "OPORTUNIDAD PERDIDA" in c and dsv9 <= 60:
            sem.append((r, f"OPORTUNIDAD PERDIDA pero dsv={r['_dsv']} (esp >60)"))
        if "BESTSELLER ACTIVO" in c and dsv9 > 30:
            sem.append((r, f"BESTSELLER ACTIVO pero dsv={r['_dsv']} (esp ≤30)"))
        if "LENTO CRÓNICO" in c:
            edad, vlife = co(r["_edad"]), co(r["_vlife"])
            if edad < 180 or vlife >= 60 or (edad > 0 and vlife / edad * 30 >= 5):
                sem.append((r, f"LENTO CRÓNICO con edad={edad} vlife={vlife}"))
        if "INVENTARIO SANO" in c and (f(r["_cobrec"]) is None or not (30 <= f(r["_cobrec"]) <= 45)):
            sem.append((r, f"INVENTARIO SANO pero cob={r['_cobrec']} (esp 30-45)"))
        if "QUIEBRE" in c and dsv9 > 14:
            sem.append((r, f"QUIEBRE pero dsv={r['_dsv']} (esp ≤14)"))
        if "STOCK EXCESIVO" in c and (f(r["_cobrec"]) is None or f(r["_cobrec"]) <= 45):
            sem.append((r, f"STOCK EXCESIVO pero cob={r['_cobrec']} (esp >45)"))
    print(f"\n4. COHERENCIA SEMÁNTICA: {len(sem)} violaciones")
    for r, msg in sem[:10]:
        print(f"     ✗ {r['Código SKU']} {r['Sucursal'][:12]}: {msg}")

    # ── 5. Distribución final ──
    cnt = Counter((r["Clasificación"] or "").split("—")[0].split(":")[0].strip() for r in rows)
    print(f"\n5. DISTRIBUCIÓN ({len(cnt)} cajas):")
    for c, n in cnt.most_common():
        print(f"   {n:>5}  {c}")

    total_err = len(mismatches) + len(bad_st) + len(bad_vida) + len(bad_cob) + len(bad_tend) + len(sem)
    print(f"\n{'✅ AUDITORÍA LIMPIA' if total_err == 0 else f'⚠️ {total_err} HALLAZGOS'}")


if __name__ == "__main__":
    asyncio.run(main())
