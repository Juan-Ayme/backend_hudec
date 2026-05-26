"""
Auditoría rápida: ¿por qué la BD local muestra más ventas que BSale?
Compara los últimos 7 días, solo oficinas 1 y 3.
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from harvester import db, bsale_client
from datetime import datetime, timedelta, timezone

db.init_pool()

print("=" * 72)
print("  AUDITORIA DE VENTAS - ULTIMOS 7 DIAS - OFICINAS 1 Y 3")
print("=" * 72)

with db.get_conn() as conn:
    with conn.cursor() as cur:

        # 1. Total general
        cur.execute("""
            SELECT SUM(total_amount), COUNT(*)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\n[BD LOCAL] Total ventas (sin NC, offices 1+3): S/{r[0]:,.2f}  ({r[1]} docs)")

        # 2. Desglose por tipo de documento
        cur.execute("""
            SELECT dt.bsale_document_type_id, dt.name, dt.is_credit_note,
                   dt.is_sales_note, COUNT(*) as n, SUM(d.total_amount) as total
            FROM documents d
            JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
            GROUP BY dt.bsale_document_type_id, dt.name, dt.is_credit_note, dt.is_sales_note
            ORDER BY total DESC NULLS LAST
        """)
        rows = cur.fetchall()
        print("\nDesglose por tipo de documento:")
        header = f"  {'ID':>4}  {'Tipo':<40}  {'NC?':>4}  {'NV?':>4}  {'Docs':>6}  {'Total':>12}"
        print(header)
        print("  " + "-" * len(header))
        for r in rows:
            total_str = f"S/{r[5]:>10,.2f}" if r[5] else "S/      0.00"
            print(f"  {r[0]:>4}  {r[1]:<40}  {str(r[2]):>4}  {str(r[3]):>4}  {r[4]:>6}  {total_str}")

        # 3. Sin notas de venta
        cur.execute("""
            SELECT SUM(d.total_amount), COUNT(*)
            FROM documents d
            JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
              AND COALESCE(dt.is_sales_note, FALSE) = FALSE
        """)
        r = cur.fetchone()
        print(f"\n[BD LOCAL] Sin NC y sin Notas de Venta: S/{r[0]:,.2f}  ({r[1]} docs)")

        # 4. Solo notas de venta
        cur.execute("""
            SELECT SUM(d.total_amount), COUNT(*)
            FROM documents d
            JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
              AND COALESCE(dt.is_sales_note, FALSE) = TRUE
        """)
        r = cur.fetchone()
        nv_total = r[0] or 0
        nv_count = r[1] or 0
        print(f"[BD LOCAL] Solo Notas de Venta: S/{nv_total:,.2f}  ({nv_count} docs)")

        # 5. Desglose por oficina
        cur.execute("""
            SELECT d.bsale_office_id, o.name, COUNT(*), SUM(d.total_amount)
            FROM documents d
            LEFT JOIN offices o ON o.bsale_office_id = d.bsale_office_id
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
            GROUP BY d.bsale_office_id, o.name
            ORDER BY d.bsale_office_id
        """)
        print("\nDesglose por oficina (sin NC):")
        for r in cur.fetchall():
            marker = " <-- incluida" if r[0] in (1, 3) else " (excluida del filtro)"
            print(f"  Office {r[0]}: {(r[1] or 'NULL'):<30}  {r[2]:>5} docs  S/{r[3]:>10,.2f}{marker}")

        # 6. Desglose por dia (para comparar dia a dia con BSale)
        cur.execute("""
            SELECT (d.emission_date AT TIME ZONE 'UTC')::DATE as dia,
                   COUNT(*), SUM(d.total_amount)
            FROM documents d
            WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND d.bsale_office_id IN (1, 3)
              AND COALESCE(d.is_credit_note, FALSE) = FALSE
            GROUP BY dia
            ORDER BY dia
        """)
        print("\nDesglose por dia (offices 1+3, sin NC):")
        for r in cur.fetchall():
            print(f"  {r[0]}  {r[1]:>5} docs  S/{r[2]:>10,.2f}")

        # 7. Verificar documentos con total_amount = 0
        cur.execute("""
            SELECT COUNT(*), SUM(total_amount)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= CURRENT_DATE - 6
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= CURRENT_DATE
              AND bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND total_amount = 0
        """)
        r = cur.fetchone()
        print(f"\nDocumentos con total_amount = 0: {r[0]} docs")

        # 8. Comparar con BSale API dia por dia
        print("\n" + "=" * 72)
        print("  COMPARANDO CON BSALE API...")
        print("=" * 72)

        today = datetime.now(timezone.utc).date()
        bsale_total = 0
        bsale_docs = 0

        BASE = "https://api.bsale.io/v1/documents.json"

        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")

            start_ts = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
            end_ts = start_ts + 86400

            day_total_1 = 0
            day_count_1 = 0
            day_total_3 = 0
            day_count_3 = 0

            for office_id in [1, 3]:
                offset = 0
                while True:
                    url = (
                        f"{BASE}?emissiondate={start_ts}"
                        f"&finalemissiondate={end_ts}"
                        f"&officeid={office_id}"
                        f"&state=0&limit=50&offset={offset}"
                    )
                    data = bsale_client.fetch(url)
                    items = data.get("items", [])
                    if not items:
                        break
                    for doc in items:
                        amt = float(doc.get("totalAmount", 0))
                        if office_id == 1:
                            day_total_1 += amt
                            day_count_1 += 1
                        else:
                            day_total_3 += amt
                            day_count_3 += 1
                    if offset + len(items) >= data.get("count", 0):
                        break
                    offset += len(items)

            day_bsale = day_total_1 + day_total_3
            bsale_total += day_bsale
            bsale_docs += day_count_1 + day_count_3
            print(f"  {day_str}  BSale: {day_count_1+day_count_3:>4} docs  S/{day_bsale:>10,.2f}  (O1:{day_count_1}/{day_total_1:,.2f}  O3:{day_count_3}/{day_total_3:,.2f})")

        print(f"\n  BSALE API TOTAL (7d, O1+O3): S/{bsale_total:,.2f}  ({bsale_docs} docs)")

db.close_pool()
print("\n" + "=" * 72)
print("  AUDITORIA COMPLETADA")
print("=" * 72)
