"""
Compara la clasificación SQL (producción) con el clasificador Python
basado en tiempo. Reporta:
  - Distribución por etiqueta en cada lado
  - Matriz de migración: cuántos SKUs se mueven de qué a qué
  - 5 ejemplos concretos de cada migración importante

Uso: python -m _beta.comparar  (desde backend_hudec/)
"""
import asyncio
import io
import sys
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from sqlalchemy import text
from app.database import async_session_maker
from app.kawii_matrix import service
from _beta import clasificador_tiempo

# Inyectamos en el SELECT las columnas internas + dias_ciclo_venta calculado.
DEBUG = """
    stock_disponible AS "stock_disponible",
    unds_vendidas AS "unds_vendidas",
    unds_recibidas_90d AS "unds_recibidas_90d",
    unds_vendidas_lifetime AS "unds_vendidas_lifetime",
    unds_recibidas_lifetime AS "unds_recibidas_lifetime",
    unds_consumidas_lifetime AS "unds_consumidas_lifetime",
    unds_trasladadas_lifetime AS "unds_trasladadas_lifetime",
    proy_mes AS "proy_mes",
    dias_sin_venta_90d AS "dias_sin_venta",
    dias_desde_ultima_recep AS "dias_desde_ultima_recep",
    edad_dias AS "edad_dias",
    dias_cobertura AS "dias_cobertura",
    pct_frecuencia AS "pct_frecuencia",
    v_recent_45d AS "v_recent_45d",
    v_old_45d AS "v_old_45d",
    vel_30d AS "vel_30d",
    department_id AS "department_id",
    -- Métrica nueva clave del clasificador-tiempo: días entre 1ª venta del lote y última
    CASE
        WHEN ult_venta_lote IS NOT NULL AND COALESCE(primera_recep_90d, ultima_recepcion) IS NOT NULL
        THEN (ult_venta_lote - COALESCE(primera_recep_90d::date, ultima_recepcion::date))::int
        ELSE NULL
    END AS "dias_ciclo_venta",
"""
ANCHOR = 'dias_sin_venta_90d::int                  AS "Días sin Vender",'


async def main():
    sql = service._load_sql("04b").replace(ANCHOR, ANCHOR + "\n" + DEBUG, 1)
    async with async_session_maker() as db:
        # Resolver params igual que el servicio
        params = service._get_query_params()
        try:
            from app.routers.config_admin import get_exclusions, get_seasonal
            ex = await get_exclusions(db)
            params["excluded_departments"] = ex["departments"]
            params["excluded_categories"] = ex["categories"]
            params["seasonal_departments"] = await get_seasonal(db)
            # Pasar también al clasificador Python para consistencia
            clasificador_tiempo.SEASONAL_DEPARTMENTS = list(params["seasonal_departments"] or [])
        except Exception as e:
            print(f"warn params: {e}")
        await db.execute(text("SET LOCAL enable_nestloop = off"))
        await db.execute(text("SET LOCAL timezone = 'UTC'"))
        res = await db.execute(text(sql), params)
        cols = list(res.keys())
        rows = [dict(zip(cols, r)) for r in res.fetchall()]

    print(f"Total filas (SKU × sucursal): {len(rows)}\n")

    # Columna de Clasificación SQL
    clave_sql = next(c for c in cols if "lasificaci" in c.lower())

    # Aplicar clasificador Python a cada fila
    for r in rows:
        r["_clasif_python"] = clasificador_tiempo.clasificar_inventario_por_tiempo(r)
        r["_clasif_sql"] = str(r.get(clave_sql) or "").split(":")[0].strip()
        r["_clasif_py_short"] = r["_clasif_python"].split(":")[0].strip()

    # 1. Distribuciones
    print("═" * 70)
    print("DISTRIBUCIÓN — SQL actual (producción)")
    print("═" * 70)
    sql_counts = Counter(r["_clasif_sql"] for r in rows)
    for lab, n in sql_counts.most_common():
        print(f"  {n:5}  {lab}")

    print()
    print("═" * 70)
    print("DISTRIBUCIÓN — Python (clasificador tiempo)")
    print("═" * 70)
    py_counts = Counter(r["_clasif_py_short"] for r in rows)
    for lab, n in py_counts.most_common():
        print(f"  {n:5}  {lab}")

    # 2. Coincidencias y diferencias
    print()
    print("═" * 70)
    print("ACUERDO ENTRE LOS DOS CLASIFICADORES")
    print("═" * 70)
    iguales = sum(1 for r in rows if r["_clasif_sql"] == r["_clasif_py_short"])
    print(f"  Misma etiqueta:    {iguales:5}  ({iguales*100/len(rows):.1f}%)")
    print(f"  Etiqueta distinta: {len(rows)-iguales:5}  ({(len(rows)-iguales)*100/len(rows):.1f}%)")

    # 3. Matriz de migración: top 15 movimientos
    print()
    print("═" * 70)
    print("TOP 15 MIGRACIONES (SQL → Python) — quién se mueve a qué")
    print("═" * 70)
    migs = Counter((r["_clasif_sql"], r["_clasif_py_short"]) for r in rows if r["_clasif_sql"] != r["_clasif_py_short"])
    for (sql_lab, py_lab), n in migs.most_common(15):
        print(f"  {n:4}  {sql_lab[:35]:35} -> {py_lab}")

    # 4. Casos huérfanos en Python (catch-all)
    huerf_py = [r for r in rows if "EN ANÁLISIS" in r["_clasif_py_short"]]
    print()
    print(f"HUÉRFANOS Python (EN ANÁLISIS): {len(huerf_py)}")
    if huerf_py:
        print("  (estos no encajaron en ninguna rama del árbol Python)")
        for r in huerf_py[:5]:
            print(
                f"    {r.get('Código SKU')!r:15} {str(r.get('Sucursal'))[:9]:9} "
                f"stock={r['stock_disponible']} V90={r['unds_vendidas']} "
                f"dsv={r['dias_sin_venta']} dias_ciclo={r.get('dias_ciclo_venta')}"
            )

    # 5. Casos donde Python clasifica MEJOR (productos que en SQL estaban en cajas
    #    engañosas y Python detecta correctamente como "lento" o "olvidado")
    print()
    print("═" * 70)
    print("CASOS DONDE PYTHON APORTA NUEVA INFORMACIÓN (5 ejemplos por categoría nueva)")
    print("═" * 70)
    nuevas_py = ["💎 EXITOSO OLVIDADO", "🐢 ROTACIÓN LENTA SANA", "💤 DEMANDA EXTINTA"]
    for cat in nuevas_py:
        ejemplos = [r for r in rows if r["_clasif_py_short"] == cat][:5]
        if not ejemplos:
            continue
        print(f"\n  Python: {cat}  ({sum(1 for r in rows if r['_clasif_py_short']==cat)} casos)")
        for r in ejemplos:
            print(
                f"    {str(r.get('Código SKU'))[:14]:14} "
                f"{str(r.get('Sucursal')).replace('KAWII ','')[:9]:9} "
                f"dias_ciclo={r.get('dias_ciclo_venta')} "
                f"dsv={r['dias_sin_venta']} "
                f"sell={(float(r['unds_vendidas_lifetime'] or 0) + float(r['unds_consumidas_lifetime'] or 0) + float(r['unds_trasladadas_lifetime'] or 0)) / (float(r['unds_recibidas_lifetime']) if float(r['unds_recibidas_lifetime'] or 0) > 0 else 1)*100:.0f}% "
                f"SQL_dijo={r['_clasif_sql'][:30]}"
            )


if __name__ == "__main__":
    asyncio.run(main())
