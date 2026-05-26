"""
audit_final.py — Auditoria de ventas: base de datos local vs BSale.

PROPOSITO:
    Compara los totales de ventas en la base de datos PostgreSQL local
    contra lo que reporta BSale, explorando varios escenarios para
    identificar la fuente de cualquier discrepancia.

POR QUE EXISTEN DIFERENCIAS:
    Las discrepancias comunes entre BD local y BSale se deben a:
    1. Zona horaria: Postgres guarda en UTC, BSale reporta en hora Peru.
       Un documento emitido a las 23:00 PE puede quedar en "dia siguiente" en UTC.
    2. Tipo de documento: BSale puede incluir notas de credito (NC) o
       traslados internos que el reporte local excluye.
    3. Sucursales: BSale puede mostrar todas (incluyendo almacen) mientras
       que los reportes locales solo usan sucursales 1 y 3.

ESCENARIOS QUE CALCULA:
    A) Solo tiendas (O1+O3), sin NC, sin traslados internos  <- el mas "limpio"
    B) Solo tiendas (O1+O3), sin NC (incluye traslados)
    C) Todas las oficinas, sin NC
    D) Todas las oficinas, todos los tipos (incluso NC)
    E) Desglose net_amount / total_amount / tax_amount para O1+O3
    F) Suma desde document_details en vez de documents (cross-check)
    G) Solo almacen central (O4) - para identificar traslados
    H) Replica exacta de la query que usa el endpoint /analytics/kpis

COMO EJECUTAR:
    cd produccion
    python tools/audits/audit_final.py

NOTA: Requiere que la BD este actualizada (run_daily_sync.py reciente).
"""
import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from harvester import db, bsale_client
from datetime import datetime, timedelta, timezone

db.init_pool()

print("=" * 72)
print("  RESUMEN FINAL DE AUDITORIA")
print("=" * 72)

# =====================================================================
# Datos descubiertos en la auditoria anterior:
# BD LOCAL (7d, O1+O3, sin NC):           S/39,694.60  (2728 docs)
#   -> Incluye 22-abr a 28-abr (porque CURRENT_DATE=28-abr local)
# BSALE API (7d, O1+O3, state=0):         S/34,475.93  (2321 docs)
#   -> Incluye 23-abr a 29-abr (porque hoy UTC es 29-abr)
#
# El usuario dice que BSale muestra S/46,510 => quizás incluye
# TODAS las oficinas, o usa otro rango, o incluye traslados internos
# =====================================================================

with db.get_conn() as conn:
    with conn.cursor() as cur:
        print("\n--- ESCENARIOS DE SUMA EN BD LOCAL (ultimos 7 dias) ---\n")

        # Escenario A: Solo O1+O3, sin NC, sin traslado interno
        cur.execute("""
            SELECT SUM(d.total_amount), COUNT(*)
            FROM documents d
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
              AND d.bsale_document_type_id != 37
        """)
        r = cur.fetchone()
        print(f"A) O1+O3, sin NC, sin traslado:  S/{r[0]:>12,.2f}  ({r[1]} docs)")

        # Escenario B: Solo O1+O3, sin NC (incluye traslado interno)
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"B) O1+O3, sin NC:                S/{r[0]:>12,.2f}  ({r[1]} docs)")

        # Escenario C: TODAS oficinas, sin NC
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"C) TODAS oficinas, sin NC:        S/{r[0]:>12,.2f}  ({r[1]} docs)")

        # Escenario D: TODAS oficinas, TODOS los tipos (incluso NC)
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
        """)
        r = cur.fetchone()
        print(f"D) TODAS oficinas, TODOS tipos:   S/{r[0]:>12,.2f}  ({r[1]} docs)")

        # Escenario E: Usar SUM(net_amount) en vez de SUM(total_amount)
        cur.execute("""
            SELECT SUM(net_amount), SUM(total_amount), SUM(tax_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\nE) O1+O3 desglose:")
        print(f"   net_amount:    S/{r[0]:>12,.2f}")
        print(f"   total_amount:  S/{r[1]:>12,.2f}")
        print(f"   tax_amount:    S/{r[2]:>12,.2f}")
        print(f"   docs: {r[3]}")

        # Escenario F: Sumar desde document_details en vez de documents
        cur.execute("""
            SELECT SUM(dd.total_amount), COUNT(DISTINCT dd.bsale_document_id), COUNT(*)
            FROM document_details dd
            JOIN documents d ON d.bsale_document_id = dd.bsale_document_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\nF) SUM desde document_DETAILS:")
        print(f"   SUM(dd.total_amount):  S/{r[0]:>12,.2f}  ({r[1]} docs, {r[2]} lineas)")

        # Escenario G: Office 4 - ALMACEN CENTRAL
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND bsale_office_id = 4
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\nG) Solo ALMACEN CENTRAL (O4):  S/{r[0]:>12,.2f}  ({r[1]} docs)")

        # Escenario H: Lo que el endpoint /analytics/kpis usa realmente
        # (replica la query exacta de analytics.py)
        from analytics_scripts.config import OFFICE_IDS
        _oids_sql = ", ".join(str(i) for i in OFFICE_IDS)
        from datetime import date
        today = date.today()
        dfrom = today - timedelta(days=7)
        dto = today + timedelta(days=1)
        cur.execute(f"""
            SELECT COALESCE(SUM(total_amount), 0)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s
              AND (emission_date AT TIME ZONE 'UTC')::DATE < %s
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND bsale_office_id IN ({_oids_sql})
        """, (dfrom, dto))
        r = cur.fetchone()
        print(f"\nH) Endpoint /kpis (days=7):    S/{r[0]:>12,.2f}")
        print(f"   OFFICE_IDS: {OFFICE_IDS}")
        print(f"   Rango: {dfrom} a {dto}")

db.close_pool()

print("\n" + "=" * 72)
print("  USUARIO REPORTA BSALE = S/46,510.32")
print("  -> Verificar en BSale si incluye Office 4 (Almacen Central)")
print("  -> Los S/60,358 del Almacen Central son traslados internos")
print("=" * 72)
