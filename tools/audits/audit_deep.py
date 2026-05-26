"""
Investigar que campo usa BSale para reportar "ventas" y si hay docs faltantes.
"""
import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from harvester import db, bsale_client
from datetime import datetime, timedelta, timezone

db.init_pool()

today = datetime.now(timezone.utc).date()
BASE = "https://api.bsale.io/v1/documents.json"

print("=" * 72)
print("  INVESTIGACION DETALLADA: BSale vs BD Local")
print("=" * 72)

# Comparar DIA A DIA: BSale API vs BD local
bsale_grand = 0
bd_grand = 0

for i in range(6, -1, -1):
    day = today - timedelta(days=i)
    day_str = day.strftime("%Y-%m-%d")

    start_ts = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    end_ts = start_ts + 86400

    # BSale API total para el dia
    bsale_day = 0
    bsale_count = 0
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
                bsale_day += float(doc.get("totalAmount", 0))
                bsale_count += 1
            if offset + len(items) >= data.get("count", 0):
                break
            offset += len(items)

    # BD local total para el dia
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(total_amount), 0), COUNT(*)
                FROM documents
                WHERE (emission_date AT TIME ZONE 'UTC')::DATE = %s
                  AND bsale_office_id IN (1, 3)
                  AND COALESCE(is_credit_note, FALSE) = FALSE
            """, (day,))
            bd_r = cur.fetchone()
            bd_day = float(bd_r[0])
            bd_count = bd_r[1]

    diff = bd_day - bsale_day
    diff_docs = bd_count - bsale_count
    marker = " <-- DIFF" if abs(diff) > 1 else ""
    print(f"  {day_str}  BSale: {bsale_count:>4} docs S/{bsale_day:>10,.2f}  |  BD: {bd_count:>4} docs S/{bd_day:>10,.2f}  |  diff: {diff_docs:>+3} docs S/{diff:>+8,.2f}{marker}")

    bsale_grand += bsale_day
    bd_grand += bd_day

print(f"\n  TOTAL BSale API (7d): S/{bsale_grand:>12,.2f}")
print(f"  TOTAL BD Local (7d): S/{bd_grand:>12,.2f}")
print(f"  Diferencia:          S/{bd_grand - bsale_grand:>+12,.2f}")

# Ahora checkear un solo documento para ver si totalAmount en API == total_amount en BD
print("\n--- Verificacion de campo totalAmount de BSale API ---")
url = f"{BASE}?emissiondate={int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()) - 86400}&finalemissiondate={int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp())}&officeid=1&state=0&limit=3"
data = bsale_client.fetch(url)
for doc in data.get("items", [])[:3]:
    doc_id = doc.get("id")
    total_api = float(doc.get("totalAmount", 0))
    net_api = float(doc.get("netAmount", 0))
    tax_api = float(doc.get("taxAmount", 0))
    exempt_api = float(doc.get("exemptAmount", 0))

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT total_amount, net_amount, tax_amount
                FROM documents
                WHERE bsale_document_id = %s
            """, (doc_id,))
            bd_r = cur.fetchone()

    print(f"\n  Doc {doc_id}:")
    print(f"    API: total={total_api}  net={net_api}  tax={tax_api}  exempt={exempt_api}")
    if bd_r:
        print(f"    BD:  total={bd_r[0]}  net={bd_r[1]}  tax={bd_r[2]}")
        if abs(float(bd_r[0]) - total_api) > 0.01:
            print(f"    !!! MISMATCH en total_amount: API={total_api} vs BD={bd_r[0]}")
    else:
        print(f"    !!! NO ENCONTRADO EN BD")

# Checkear si BSale filtra con state=0 excluye algo que la BD tiene
print("\n--- Verificacion: hay docs con state!=0 en BSale que la BD incluya? ---")
with db.get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*), SUM(total_amount)
            FROM documents
            WHERE (emission_date AT TIME ZONE 'UTC')::DATE >= %s
              AND (emission_date AT TIME ZONE 'UTC')::DATE <= %s
              AND bsale_office_id IN (1, 3)
              AND COALESCE(is_credit_note, FALSE) = FALSE
              AND is_active = FALSE
        """, (today - timedelta(days=6), today))
        r = cur.fetchone()
        print(f"  Docs INACTIVOS en BD (7d, O1+O3): {r[0]} docs, S/{r[1] or 0:,.2f}")

db.close_pool()
print("\n" + "=" * 72)
