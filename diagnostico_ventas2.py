"""Diagnóstico complementario: verificar si la diferencia es por filtro de oficinas
o por montos incorrectos en la DB."""

import sys
from pathlib import Path
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import psycopg2, psycopg2.extras
from harvester.config import DB_CONFIG

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def q(sql):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

print("=" * 70)
print("  DIAGNOSTICO COMPLEMENTARIO")
print("=" * 70)

# 1. Ventas junio TODAS las oficinas (sin filtro)
print("\n-- 1. JUNIO 2026 POR OFICINA (TODAS) --")
rows = q("""
    SELECT o.name AS oficina, o.bsale_office_id,
           COUNT(*) AS docs,
           ROUND(SUM(d.total_amount)::numeric, 2) AS venta_total,
           ROUND(SUM(d.net_amount)::numeric, 2) AS neto,
           ROUND(SUM(d.tax_amount)::numeric, 2) AS igv
    FROM documents d
    LEFT JOIN offices o ON o.bsale_office_id = d.bsale_office_id
    WHERE COALESCE(d.is_credit_note, FALSE) = FALSE
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
    GROUP BY o.name, o.bsale_office_id
    ORDER BY venta_total DESC
""")
total_all = 0.0
total_docs_all = 0
print(f"  {'Oficina':<25} {'ID':>4} {'Docs':>6} {'Venta Total':>14} {'Neto':>14} {'IGV':>10}")
print(f"  {'-'*25} {'-'*4} {'-'*6} {'-'*14} {'-'*14} {'-'*10}")
for r in rows:
    total_all += float(r['venta_total'])
    total_docs_all += r['docs']
    print(f"  {(r['oficina'] or 'SIN OFICINA')[:25]:<25} {r['bsale_office_id'] or 0:>4} {r['docs']:>6} S/{float(r['venta_total']):>12,.2f} S/{float(r['neto']):>12,.2f} S/{float(r['igv']):>8,.2f}")
print(f"  {'TOTAL':<25} {'':>4} {total_docs_all:>6} S/{total_all:>12,.2f}")
print(f"\n  BSale API reporto: 6,277 docs | S/202,576.39")
print(f"  DB (TODAS oficinas):  {total_docs_all:,} docs | S/{total_all:,.2f}")
diff = 202576.39 - total_all
print(f"  Diferencia: {202576.39 - total_all:,.2f} en monto, {6277 - total_docs_all} en docs")

# 2. Verificar documentos con total_amount = 0
print("\n-- 2. DOCUMENTOS CON total_amount = 0 EN JUNIO --")
rows_zero = q("""
    SELECT o.name AS oficina, COUNT(*) AS docs
    FROM documents d
    LEFT JOIN offices o ON o.bsale_office_id = d.bsale_office_id
    WHERE d.total_amount = 0
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
    GROUP BY o.name
    ORDER BY docs DESC
""")
for r in rows_zero:
    print(f"  {r['oficina']}: {r['docs']} docs con total=0")
if not rows_zero:
    print("  Ninguno")

# 3. Comparar total_amount del header vs SUM de detalles
print("\n-- 3. HEADER vs DETALLES: hay discrepancia en montos? --")
rows_diff = q("""
    SELECT d.bsale_document_id, d.total_amount AS header_total,
           COALESCE(SUM(dd.total_amount), 0) AS detail_total,
           d.total_amount - COALESCE(SUM(dd.total_amount), 0) AS diferencia,
           o.name AS oficina
    FROM documents d
    LEFT JOIN document_details dd ON dd.bsale_document_id = d.bsale_document_id
    LEFT JOIN offices o ON o.bsale_office_id = d.bsale_office_id
    WHERE COALESCE(d.is_credit_note, FALSE) = FALSE
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
    GROUP BY d.bsale_document_id, d.total_amount, o.name
    HAVING ABS(d.total_amount - COALESCE(SUM(dd.total_amount), 0)) > 1
    ORDER BY ABS(d.total_amount - COALESCE(SUM(dd.total_amount), 0)) DESC
    LIMIT 20
""")
if rows_diff:
    print(f"  {'Doc ID':>10} {'Header':>12} {'Detalles':>12} {'Dif':>12} {'Oficina':<20}")
    print(f"  {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*20}")
    for r in rows_diff:
        print(f"  {r['bsale_document_id']:>10} S/{float(r['header_total']):>10,.2f} S/{float(r['detail_total']):>10,.2f} S/{float(r['diferencia']):>10,.2f} {r['oficina']}")
    total_dif = sum(float(r['diferencia']) for r in rows_diff)
    print(f"  Total discrepancia en estos {len(rows_diff)} docs: S/{total_dif:,.2f}")
else:
    print("  No hay discrepancia header vs detalles")

# 4. Documentos sin detalles (posible causa de montos faltantes)
print("\n-- 4. DOCUMENTOS SIN DETALLES EN JUNIO --")
rows_no_det = q("""
    SELECT d.bsale_document_id, d.total_amount, d.bsale_document_type_id,
           dt.name AS tipo, o.name AS oficina
    FROM documents d
    LEFT JOIN document_details dd ON dd.bsale_document_id = d.bsale_document_id
    LEFT JOIN document_types dt ON dt.bsale_document_type_id = d.bsale_document_type_id
    LEFT JOIN offices o ON o.bsale_office_id = d.bsale_office_id
    WHERE dd.bsale_detail_id IS NULL
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
      AND (d.emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
      AND d.total_amount > 0
    ORDER BY d.total_amount DESC
    LIMIT 20
""")
if rows_no_det:
    print(f"  {len(rows_no_det)} docs sin detalles con monto > 0:")
    for r in rows_no_det:
        print(f"    Doc {r['bsale_document_id']}: S/{float(r['total_amount']):,.2f} | {r['tipo']} | {r['oficina']}")
else:
    print("  Todos los documentos tienen detalles")

# 5. Verificar por tipo de documento vs BSale
print("\n-- 5. TIPOS DE DOCUMENTO EN TODA LA DB --")
rows_tipos = q("""
    SELECT dt.bsale_document_type_id, dt.name, dt.is_credit_note, dt.is_sales_note
    FROM document_types dt
    ORDER BY dt.bsale_document_type_id
""")
for r in rows_tipos:
    nc = "NC" if r['is_credit_note'] else "  "
    sn = "SN" if r['is_sales_note'] else "  "
    print(f"  ID={r['bsale_document_type_id']:>3} | {nc} {sn} | {r['name']}")

# 6. Verificar montos del detail (net vs total para entender si BSale da bruto y DB guarda neto)
print("\n-- 6. MUESTRA DE 10 DOCS RECIENTES: comparar net vs total --")
sample = q("""
    SELECT d.bsale_document_id, d.total_amount AS doc_total, d.net_amount AS doc_net,
           d.tax_amount AS doc_tax,
           COALESCE(SUM(dd.total_amount), 0) AS det_total_sum,
           COALESCE(SUM(dd.net_amount), 0) AS det_net_sum
    FROM documents d
    LEFT JOIN document_details dd ON dd.bsale_document_id = d.bsale_document_id
    WHERE (d.emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-15'
      AND COALESCE(d.is_credit_note, FALSE) = FALSE
      AND d.bsale_office_id IN (1, 3)
      AND d.total_amount > 0
    GROUP BY d.bsale_document_id, d.total_amount, d.net_amount, d.tax_amount
    ORDER BY d.total_amount DESC
    LIMIT 10
""")
print(f"  {'Doc ID':>10} {'Total':>10} {'Neto':>10} {'IGV':>10} {'Det.Total':>10} {'Det.Neto':>10}")
for r in sample:
    print(f"  {r['bsale_document_id']:>10} {float(r['doc_total']):>10,.2f} {float(r['doc_net']):>10,.2f} {float(r['doc_tax']):>10,.2f} {float(r['det_total_sum']):>10,.2f} {float(r['det_net_sum']):>10,.2f}")

# 7. Verificar si BSale da importes en centavos o enteros
print("\n-- 7. RANGO DE total_amount (distribucion) --")
dist = q("""
    SELECT 
        COUNT(*) FILTER (WHERE total_amount = 0) AS zero,
        COUNT(*) FILTER (WHERE total_amount > 0 AND total_amount < 10) AS lt10,
        COUNT(*) FILTER (WHERE total_amount >= 10 AND total_amount < 50) AS r10_50,
        COUNT(*) FILTER (WHERE total_amount >= 50 AND total_amount < 100) AS r50_100,
        COUNT(*) FILTER (WHERE total_amount >= 100 AND total_amount < 500) AS r100_500,
        COUNT(*) FILTER (WHERE total_amount >= 500) AS gt500,
        ROUND(AVG(total_amount)::numeric, 2) AS promedio,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_amount)::numeric, 2) AS mediana
    FROM documents
    WHERE COALESCE(is_credit_note, FALSE) = FALSE
      AND bsale_office_id IN (1, 3)
      AND (emission_date AT TIME ZONE 'UTC')::DATE >= '2026-06-01'
      AND (emission_date AT TIME ZONE 'UTC')::DATE <= '2026-06-30'
""")
if dist:
    d = dist[0]
    print(f"  Docs con total=0:       {d['zero']}")
    print(f"  Docs S/0-10:            {d['lt10']}")
    print(f"  Docs S/10-50:           {d['r10_50']}")
    print(f"  Docs S/50-100:          {d['r50_100']}")
    print(f"  Docs S/100-500:         {d['r100_500']}")
    print(f"  Docs S/500+:            {d['gt500']}")
    print(f"  Promedio:               S/{float(d['promedio']):,.2f}")
    print(f"  Mediana:                S/{float(d['mediana']):,.2f}")

print("\n" + "=" * 70)
