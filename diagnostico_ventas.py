"""
Diagnóstico de discrepancia de ventas entre BSale y la base de datos local.

Compara:
  1. Total de ventas en la DB local (documentos no-NC)
  2. Total de documentos en BSale (API)
  3. Identifica brechas por rango de fechas

Uso:
    python diagnostico_ventas.py
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests
from datetime import datetime, date, timedelta, timezone
from harvester.config import (
    BSALE_BASE_URL, BSALE_HEADERS, OFFICES_TIENDA, TIPOS_VENTA, TIPOS_DEVOLUCION,
    DB_CONFIG,
)
import psycopg2
import psycopg2.extras


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def q(sql, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()


def scalar(sql, params=None):
    rows = q(sql, params)
    if rows:
        vals = list(rows[0].values())
        return vals[0] if vals else None
    return None


def bsale_count(extra=""):
    """Cuenta documentos en BSale con filtro extra."""
    url = f"{BSALE_BASE_URL}/documents.json?limit=1&state=0{extra}"
    resp = requests.get(url, headers=BSALE_HEADERS, timeout=30)
    data = resp.json()
    return data.get("count", 0)


def bsale_total_amount(since_unix, until_unix):
    """Suma total_amount de BSale paginando (para un rango de fechas)."""
    extra = f"&state=0&emissiondaterange=[{since_unix},{until_unix}]"
    url = f"{BSALE_BASE_URL}/documents.json?limit=50&offset=0{extra}"
    total = 0.0
    count = 0
    nc_count = 0
    nc_total = 0.0
    offset = 0

    while True:
        paged_url = f"{BSALE_BASE_URL}/documents.json?limit=50&offset={offset}{extra}"
        resp = requests.get(paged_url, headers=BSALE_HEADERS, timeout=30)
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for doc in items:
            if doc.get("state") != 0:
                continue
            dt = doc.get("document_type") or {}
            is_nc = dt.get("isCreditNote") == 1
            amt = float(doc.get("totalAmount") or 0)
            if is_nc:
                nc_count += 1
                nc_total += amt
            else:
                count += 1
                total += amt

        if len(items) < 50:
            break
        offset += 50

    return {"ventas_count": count, "ventas_total": total,
            "nc_count": nc_count, "nc_total": nc_total}


def main():
    print("=" * 70)
    print("  DIAGNÓSTICO DE VENTAS: BSale vs Base de Datos Local")
    print("=" * 70)
    print()

    # ── 1. Estado de la BD local ──
    print("── 1. ESTADO DE LA BASE DE DATOS LOCAL ──")
    total_docs_db = scalar("SELECT COUNT(*) FROM documents")
    total_docs_activos = scalar("SELECT COUNT(*) FROM documents WHERE is_active = TRUE")
    total_no_nc = scalar(
        "SELECT COUNT(*) FROM documents WHERE COALESCE(is_credit_note, FALSE) = FALSE"
    )
    total_nc = scalar(
        "SELECT COUNT(*) FROM documents WHERE is_credit_note = TRUE"
    )
    print(f"  Documentos totales en DB:         {total_docs_db:,}")
    print(f"  Documentos activos:               {total_docs_activos:,}")
    print(f"  Documentos NO credit note:        {total_no_nc:,}")
    print(f"  Notas de crédito:                 {total_nc:,}")

    # Última sincronización
    last_sync = q("""
        SELECT entity, status, started_at, finished_at,
               records_fetched, records_inserted
        FROM sync_log
        WHERE entity = 'documents'
        ORDER BY started_at DESC LIMIT 3
    """)
    print("\n  Últimas 3 sincronizaciones de documentos:")
    for s in last_sync:
        print(f"    {s['started_at']} | {s['status']} | fetched={s['records_fetched']} ins={s['records_inserted']}")

    # ── 2. Ventas por mes en DB ──
    print("\n── 2. VENTAS POR MES (DB LOCAL) ──")
    print("  Solo tiendas (offices:", OFFICES_TIENDA, ")")
    offices_sql = ",".join(str(o) for o in OFFICES_TIENDA)
    ventas_mes = q(f"""
        SELECT TO_CHAR((emission_date AT TIME ZONE 'UTC')::DATE, 'YYYY-MM') AS mes,
               COUNT(*) AS docs,
               ROUND(SUM(total_amount)::numeric, 2) AS venta_total
        FROM documents
        WHERE COALESCE(is_credit_note, FALSE) = FALSE
          AND bsale_office_id IN ({offices_sql})
        GROUP BY mes
        ORDER BY mes DESC
        LIMIT 6
    """)
    print(f"  {'Mes':<10} {'Docs':>8} {'Venta Total':>15}")
    print(f"  {'-'*10} {'-'*8} {'-'*15}")
    for r in ventas_mes:
        print(f"  {r['mes']:<10} {r['docs']:>8,} S/{r['venta_total']:>13,.2f}")

    # ── 3. Ventas del mes actual detallado por día ──
    print("\n── 3. VENTAS JUNIO 2026 POR DÍA (DB LOCAL) ──")
    ventas_junio = q(f"""
        SELECT (emission_date AT TIME ZONE 'UTC')::DATE AS dia,
               COUNT(*) AS docs,
               ROUND(SUM(total_amount)::numeric, 2) AS venta
        FROM documents
        WHERE COALESCE(is_credit_note, FALSE) = FALSE
          AND bsale_office_id IN ({offices_sql})
          AND (emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
          AND (emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
        GROUP BY dia
        ORDER BY dia
    """)
    total_junio_db = 0.0
    total_docs_junio = 0
    print(f"  {'Día':<12} {'Docs':>6} {'Venta':>12}")
    print(f"  {'-'*12} {'-'*6} {'-'*12}")
    for r in ventas_junio:
        total_junio_db += float(r['venta'])
        total_docs_junio += r['docs']
        print(f"  {str(r['dia']):<12} {r['docs']:>6} S/{float(r['venta']):>10,.2f}")
    print(f"  {'TOTAL':<12} {total_docs_junio:>6} S/{total_junio_db:>10,.2f}")

    # ── 4. Comparar con BSale API ──
    print("\n── 4. COMPARACIÓN CON BSALE API ──")
    
    # Total de documentos en BSale (sin filtro de fecha)
    bsale_total_count = bsale_count()
    print(f"  Total docs en BSale (state=0): {bsale_total_count:,}")
    print(f"  Total docs en DB local:        {total_no_nc:,} (no-NC) + {total_nc:,} (NC) = {total_docs_activos:,}")
    diff = bsale_total_count - total_docs_activos
    print(f"  Diferencia:                    {diff:,} {'⚠️ FALTAN EN DB' if diff > 0 else '✅ OK' if diff == 0 else '❓ SOBRAN EN DB'}")

    # Comparar junio 2026 contra BSale
    print("\n  Verificando junio 2026 contra BSale API...")
    jun_start = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    jun_end = int(datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    bsale_jun = bsale_total_amount(jun_start, jun_end)
    
    print(f"\n  JUNIO 2026 - BSale API:")
    print(f"    Documentos de venta: {bsale_jun['ventas_count']:,}  |  Total: S/{bsale_jun['ventas_total']:,.2f}")
    print(f"    Notas de crédito:    {bsale_jun['nc_count']:,}  |  Total: S/{bsale_jun['nc_total']:,.2f}")
    print(f"    Neto (ventas - NC):  S/{bsale_jun['ventas_total'] - bsale_jun['nc_total']:,.2f}")
    
    print(f"\n  JUNIO 2026 - DB Local:")
    print(f"    Documentos de venta: {total_docs_junio:,}  |  Total: S/{total_junio_db:,.2f}")

    nc_junio_db = scalar(f"""
        SELECT COALESCE(SUM(total_amount), 0)
        FROM documents
        WHERE is_credit_note = TRUE
          AND bsale_office_id IN ({offices_sql})
          AND (emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
          AND (emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
    """) or 0
    print(f"    Notas de crédito:    S/{float(nc_junio_db):,.2f}")
    print(f"    Neto (ventas - NC):  S/{total_junio_db - float(nc_junio_db):,.2f}")

    diff_junio = bsale_jun['ventas_total'] - total_junio_db
    diff_pct = (diff_junio / bsale_jun['ventas_total'] * 100) if bsale_jun['ventas_total'] else 0
    
    print(f"\n  📊 DIFERENCIA JUNIO:")
    print(f"    BSale - DB = S/{diff_junio:,.2f} ({diff_pct:+.1f}%)")
    if abs(diff_pct) > 1:
        print(f"    ⚠️ HAY DISCREPANCIA SIGNIFICATIVA")
    else:
        print(f"    ✅ Diferencia dentro del margen aceptable")

    # ── 5. Verificar tipos de documento ──
    print("\n── 5. DOCUMENTOS POR TIPO (DB LOCAL - JUNIO 2026) ──")
    por_tipo = q(f"""
        SELECT dt.name AS tipo, dt.bsale_document_type_id AS tipo_id,
               dt.is_credit_note, dt.is_sales_note,
               COUNT(*) AS docs,
               ROUND(SUM(d.total_amount)::numeric, 2) AS total
        FROM documents d
        JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
        WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
          AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
          AND d.bsale_office_id IN ({offices_sql})
        GROUP BY dt.name, dt.bsale_document_type_id, dt.is_credit_note, dt.is_sales_note
        ORDER BY total DESC
    """)
    print(f"  {'Tipo':<35} {'ID':>4} {'NC?':>4} {'Docs':>6} {'Total':>14}")
    print(f"  {'-'*35} {'-'*4} {'-'*4} {'-'*6} {'-'*14}")
    for r in por_tipo:
        nc = "SÍ" if r['is_credit_note'] else "NO"
        print(f"  {r['tipo'][:35]:<35} {r['tipo_id']:>4} {nc:>4} {r['docs']:>6} S/{float(r['total']):>12,.2f}")

    # ── 6. Rango de fechas de documento más antiguo y más reciente ──
    print("\n── 6. RANGO DE DOCUMENTOS EN DB ──")
    rango = q("""
        SELECT MIN((emission_date AT TIME ZONE 'UTC')::DATE) AS primer_doc,
               MAX((emission_date AT TIME ZONE 'UTC')::DATE) AS ultimo_doc,
               COUNT(*) AS total
        FROM documents
    """)
    if rango:
        r = rango[0]
        print(f"  Primer documento: {r['primer_doc']}")
        print(f"  Último documento: {r['ultimo_doc']}")
        print(f"  Total:            {r['total']:,}")

    # ── 7. Verificar si hay docs del día de hoy ──
    print("\n── 7. DOCUMENTOS DE HOY EN DB ──")
    today = date.today()
    docs_hoy = q(f"""
        SELECT COUNT(*) AS docs,
               COALESCE(ROUND(SUM(total_amount)::numeric, 2), 0) AS venta
        FROM documents
        WHERE COALESCE(is_credit_note, FALSE) = FALSE
          AND bsale_office_id IN ({offices_sql})
          AND (emission_date AT TIME ZONE 'UTC')::DATE = '{today}'
    """)
    if docs_hoy:
        r = docs_hoy[0]
        print(f"  Hoy ({today}): {r['docs']} documentos | S/{float(r['venta']):,.2f}")
        if r['docs'] == 0:
            print(f"  ⚠️ No hay ventas de hoy en la DB. ¿Falta sincronizar el día?")
    
    print("\n" + "=" * 70)
    print("  FIN DEL DIAGNÓSTICO")
    print("=" * 70)


if __name__ == "__main__":
    main()
