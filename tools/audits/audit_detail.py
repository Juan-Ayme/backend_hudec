"""Analisis detallado de la discrepancia dia a dia."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from harvester import db

db.init_pool()
with db.get_conn() as conn:
    with conn.cursor() as cur:

        # Hora del servidor
        cur.execute("SELECT NOW() AT TIME ZONE 'UTC', CURRENT_DATE")
        r = cur.fetchone()
        print(f"Hora UTC actual: {r[0]}")
        print(f"CURRENT_DATE (local PG): {r[1]}")

        # BD local 22-abr
        cur.execute("""
            SELECT (emission_date AT TIME ZONE 'UTC')::DATE as dia,
                   COUNT(*), SUM(total_amount)
            FROM documents
            WHERE bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND (emission_date AT TIME ZONE 'UTC')::DATE = '2026-04-22'
            GROUP BY dia
        """)
        r = cur.fetchone()
        if r:
            print(f"\nBD local 22-abr: {r[1]} docs, S/{r[2]:,.2f}")
        else:
            print("\nBD local 22-abr: NO TIENE DATOS")

        # BD local 28-abr vs BSale API 28-abr
        cur.execute("""
            SELECT (emission_date AT TIME ZONE 'UTC')::DATE as dia,
                   COUNT(*), SUM(total_amount)
            FROM documents
            WHERE bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND (emission_date AT TIME ZONE 'UTC')::DATE = '2026-04-28'
            GROUP BY dia
        """)
        r = cur.fetchone()
        print(f"\nBD local  28-abr: {r[1]} docs, S/{r[2]:,.2f}")
        print(f"BSale API 28-abr: 354 docs, S/6,076.76")
        print(f"Diferencia: {354 - r[1]} docs faltan en BD, S/{6076.76 - float(r[2]):,.2f}")

        # Tipo de documento de los "Traslado Interno" - son ventas reales?
        cur.execute("""
            SELECT dt.bsale_document_type_id, dt.name,
                   dt.is_credit_note, dt.is_sales_note,
                   dt.code
            FROM document_types dt
            ORDER BY dt.bsale_document_type_id
        """)
        print("\nTodos los tipos de documento en BD:")
        for r in cur.fetchall():
            print(f"  ID={r[0]:>4}  name={r[1]:<30}  NC={r[2]}  NV={r[3]}  code={r[4]}")

        # Ultimos documentos del 28 abril
        cur.execute("""
            SELECT bsale_document_id, emission_date, total_amount,
                   bsale_office_id, bsale_document_type_id
            FROM documents
            WHERE bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND (emission_date AT TIME ZONE 'UTC')::DATE = '2026-04-28'
            ORDER BY bsale_document_id DESC
            LIMIT 10
        """)
        print(f"\nUltimos 10 docs del 28-abr en BD:")
        for r in cur.fetchall():
            print(f"  doc_id={r[0]}  emission={r[1]}  total={r[2]}  office={r[3]}  doctype={r[4]}")

        # Contar TODOS los docs en la BD incluyendo todas las oficinas, 
        # para ver si el total_amount global coincide con S/46,510 de BSale
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\nBD Total TODAS oficinas (7d, sin NC): S/{r[0]:,.2f}  ({r[1]} docs)")

        # Sin traslado interno
        cur.execute("""
            SELECT SUM(d.total_amount), COUNT(*)
            FROM documents d
            JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
              AND d.bsale_office_id IN (1, 3)
              AND d.bsale_document_type_id != 37
        """)
        r = cur.fetchone()
        print(f"BD O1+O3 SIN traslado interno: S/{r[0]:,.2f}  ({r[1]} docs)")

db.close_pool()
