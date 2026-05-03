"""Compara datos de ventas locales vs BSale API."""
import sys, io
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from harvester import bsale_client, db
from datetime import datetime

# Verificar ventas del 21 de abril en BSale vs BD local
date_start = int(datetime(2026, 4, 21).timestamp())
date_end = int(datetime(2026, 4, 22).timestamp())

print("=" * 70)
print("COMPARACION VENTAS BSALE API vs BD LOCAL")
print("=" * 70)

# --- BSale API ---
print("\n--- BSale API ---")
for office_id in [1, 3]:
    url = f"https://api.bsale.io/v1/documents.json?limit=50&offset=0&emissiondate={date_start}&maxemissiondate={date_end}&officeid={office_id}&state=0"
    data = bsale_client.fetch(url)
    total_count = data.get("count", 0)
    items = data.get("items", [])
    
    # Sumar totales de BSale
    bsale_total = sum(float(doc.get("totalAmount", 0)) for doc in items)
    bsale_net = sum(float(doc.get("netAmount", 0)) for doc in items)
    
    print(f"  Oficina {office_id}: {total_count} docs totales (primera pagina: {len(items)})")
    print(f"    Suma total (primera pagina): {bsale_total:.2f}")
    print(f"    Suma neto (primera pagina): {bsale_net:.2f}")
    
    # Mostrar 3 ejemplo
    for doc in items[:3]:
        print(f"    Doc ID={doc.get('id')} total={doc.get('totalAmount')} net={doc.get('netAmount')} number={doc.get('number')}")

# --- BD Local ---
print("\n--- BD Local ---")
db.init_pool()
try:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Ventas del 21 abril por sucursal
            for office_id in [1, 3]:
                cur.execute("""
                    SELECT COUNT(*) as tickets,
                           ROUND(SUM(total_amount)::numeric, 2) as ventas,
                           ROUND(SUM(net_amount)::numeric, 2) as neto,
                           ROUND(AVG(total_amount)::numeric, 2) as ticket_prom
                    FROM documents
                    WHERE DATE(emission_date) = '2026-04-21'
                      AND COALESCE(is_credit_note, FALSE) = FALSE
                      AND bsale_office_id = %s
                """, (office_id,))
                row = cur.fetchone()
                print(f"  Oficina {office_id}: {row[0]} tickets | Ventas: {row[1]} | Neto: {row[2]} | Ticket prom: {row[3]}")
            
            # Verificar montos sospechosos - distribcion de montos
            print("\n--- Distribucion de montos de tickets ---")
            cur.execute("""
                SELECT 
                    CASE 
                        WHEN total_amount < 5 THEN '< 5'
                        WHEN total_amount < 10 THEN '5-10'
                        WHEN total_amount < 20 THEN '10-20'
                        WHEN total_amount < 50 THEN '20-50'
                        WHEN total_amount < 100 THEN '50-100'
                        WHEN total_amount < 200 THEN '100-200'
                        ELSE '200+'
                    END as rango,
                    COUNT(*) as tickets,
                    ROUND(SUM(total_amount)::numeric, 2) as ventas
                FROM documents
                WHERE emission_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
                GROUP BY 1
                ORDER BY 1
            """)
            for row in cur.fetchall():
                print(f"    {row[0]:>10} | Tickets: {row[1]:>5} | Ventas: {row[2]:>12}")
            
            # Ticket promedio general con documents.total_amount / count
            print("\n--- Ticket promedio correcto (doc.total_amount) ---")
            cur.execute("""
                SELECT ROUND(AVG(total_amount)::numeric, 2) as ticket_avg,
                       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_amount)::numeric, 2) as mediana,
                       ROUND(MIN(total_amount)::numeric, 2) as minimo,
                       ROUND(MAX(total_amount)::numeric, 2) as maximo
                FROM documents
                WHERE emission_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
            """)
            row = cur.fetchone()
            print(f"    Ticket promedio: {row[0]}")
            print(f"    Mediana: {row[1]}")
            print(f"    Minimo: {row[2]}")
            print(f"    Maximo: {row[3]}")
            
            # Hay docs con total_amount = 0?
            cur.execute("""
                SELECT COUNT(*) FROM documents
                WHERE total_amount = 0
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
            """)
            print(f"\n    Docs con total_amount = 0: {cur.fetchone()[0]}")
            
            # Notas de credito
            cur.execute("""
                SELECT COUNT(*), ROUND(SUM(total_amount)::numeric, 2)
                FROM documents
                WHERE is_credit_note = TRUE
                  AND bsale_office_id IN (1, 3)
            """)
            row = cur.fetchone()
            print(f"    Notas de credito: {row[0]} | Total: {row[1]}")
            
            # Comparar doc_type
            print("\n--- Documentos por tipo ---")
            cur.execute("""
                SELECT dt.name, dt.bsale_document_type_id,
                       COUNT(doc.*) as cant,
                       ROUND(SUM(doc.total_amount)::numeric, 2) as total
                FROM documents doc
                JOIN document_types dt ON dt.bsale_document_type_id = doc.bsale_document_type_id
                WHERE doc.bsale_office_id IN (1, 3)
                GROUP BY dt.name, dt.bsale_document_type_id
                ORDER BY cant DESC
            """)
            for row in cur.fetchall():
                print(f"    {row[0]:>35} (type={row[1]}) | Count: {row[2]:>5} | Total: {row[3]:>12}")
                
finally:
    db.close_pool()
