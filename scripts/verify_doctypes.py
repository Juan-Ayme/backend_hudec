"""Analizar tipos de documento y su impacto en ventas."""
import sys, io
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from harvester import db

db.init_pool()
try:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Tipos de documento
            cur.execute("SELECT * FROM document_types ORDER BY bsale_document_type_id")
            cols = [d[0] for d in cur.description]
            print("--- Tipos de documento ---")
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                dtid = r["bsale_document_type_id"]
                name = r["name"]
                cn = r["is_credit_note"]
                sn = r["is_sales_note"]
                el = r["is_electronic"]
                ac = r["is_active"]
                print(f"  ID={dtid:>3} | {name:>30} | credit={cn} | sales={sn} | elec={el} | active={ac}")
            
            # Ventas solo con boletas/facturas electronicas (doc types reales de venta)
            # Excluir: tickets internos, devoluciones, notas de credito
            print("\n--- Comparacion: todos vs solo boletas/facturas ---")
            cur.execute("""
                SELECT 'TODOS' as tipo,
                       COUNT(*) as tickets,
                       ROUND(SUM(total_amount)::numeric, 2) as ventas,
                       ROUND(AVG(total_amount)::numeric, 2) as ticket_prom
                FROM documents
                WHERE emission_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
                UNION ALL
                SELECT 'SIN TICKETS INT',
                       COUNT(*),
                       ROUND(SUM(total_amount)::numeric, 2),
                       ROUND(AVG(total_amount)::numeric, 2)
                FROM documents
                WHERE emission_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
                  AND bsale_document_type_id != 10
                UNION ALL
                SELECT 'SOLO TICKETS',
                       COUNT(*),
                       ROUND(SUM(total_amount)::numeric, 2),
                       ROUND(AVG(total_amount)::numeric, 2)
                FROM documents
                WHERE emission_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND COALESCE(is_credit_note, FALSE) = FALSE
                  AND bsale_office_id IN (1, 3)
                  AND bsale_document_type_id = 10
            """)
            for row in cur.fetchall():
                print(f"  {row[0]:>20} | Tickets: {row[1]:>5} | Ventas: {row[2]:>12} | Ticket prom: {row[3]:>8}")
            
            # Docs con total_amount = 0 desglose
            print("\n--- Documentos con total_amount = 0 ---")
            cur.execute("""
                SELECT dt.name, COUNT(*) 
                FROM documents doc
                JOIN document_types dt ON dt.bsale_document_type_id = doc.bsale_document_type_id
                WHERE doc.total_amount = 0
                  AND doc.bsale_office_id IN (1, 3)
                GROUP BY dt.name
            """)
            for row in cur.fetchall():
                print(f"  {row[0]:>30} | Count: {row[1]}")
                
            # Verificar si BSale reporta un total diferente para cierto rango
            print("\n--- Verificacion BSale API: total ventas del 21 abril (todas paginas) ---")

finally:
    db.close_pool()

# Ahora consultar BSale API para sumar todo
from harvester import bsale_client
from datetime import datetime

date_start = int(datetime(2026, 4, 21).timestamp())
date_end = int(datetime(2026, 4, 22).timestamp())

total_bsale = 0.0
docs_bsale = 0

for office_id in [1, 3]:
    offset = 0
    office_total = 0.0
    office_docs = 0
    while True:
        url = f"https://api.bsale.io/v1/documents.json?limit=50&offset={offset}&emissiondate={date_start}&maxemissiondate={date_end}&officeid={office_id}&state=0"
        data = bsale_client.fetch(url)
        items = data.get("items", [])
        if not items:
            break
        for doc in items:
            amt = float(doc.get("totalAmount", 0))
            office_total += amt
            office_docs += 1
        offset += 50
        if len(items) < 50:
            break
    
    total_bsale += office_total
    docs_bsale += office_docs
    print(f"  BSale Oficina {office_id}: {office_docs} docs | Total: {office_total:.2f}")

print(f"  BSale Total 21 abril: {docs_bsale} docs | Ventas: {total_bsale:.2f}")
print(f"  Ticket promedio BSale: {total_bsale/docs_bsale:.2f}" if docs_bsale else "  Sin docs")
