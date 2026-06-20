"""
Auditoría P20 fase 2: el Excel exportado vs la matriz 04b en vivo.

Verifica que la consolidación del Excel (1 fila por SKU, sumando sucursales)
sea fiel a la matriz:
  - Stock excel = Σ stock por sucursal
  - Vend Lote excel = Σ vend lote por sucursal
  - Clasificación = la de la sucursal DOMINANTE (más ventas S/)
  - ST% / Llegó hace / Vida lote = las del dominante
Además cuantifica:
  - Artefactos de consolidación: SKU con caja de stock=0 (BESTSELLER, etc.)
    pero stock consolidado >0 porque la otra sucursal sí tiene.
  - Divergencia de banda: columna "Cobertura" (lifetime) vs
    dias_cobertura_reciente (la que clasifica, P17).

Uso:  python -m _beta.audit_excel_vs_matriz "<ruta excel>"
"""
from __future__ import annotations
import asyncio, io, sys
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EXCEL_DEFAULT = r"C:\Users\juana\Downloads\04b_Matriz_90d_Jerárquica_2026-06-09 (2).xlsx"

# Cajas que exigen stock=0 a nivel sucursal (secciones B y C + especiales A)
CAJAS_STOCK0 = [
    "BESTSELLER ACTIVO", "BESTSELLER EN PAUSA", "OPORTUNIDAD PERDIDA",
    "LENTO PERO CONSTANTE", "DEMANDA EXTINTA", "QUIEBRE", "AGOTADO CON DEMANDA",
    "EX-BESTSELLER", "PRODUCTO EMERGENTE", "PRODUCTO MUERTO", "BAJO VOLUMEN AGOTADO",
    "AGOTADO NO PRIORITARIO", "TEMPORADA CERRADA", "PÉRDIDA DE STOCK",
    "VENDIÓ Y SE PERDIÓ", "RECIBIDO Y NO VENDIDO",
]


def fnum(v) -> float:
    if v is None or v == "" or v == "—":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def banda(d: float | None) -> str:
    if d is None:
        return "s/d"
    if d <= 0:
        return "agotado"
    if d < 30:
        return "<30"
    if d <= 45:
        return "30-45"
    return ">45"


async def main() -> None:
    from openpyxl import load_workbook
    from app.database import async_session_maker
    from app.kawii_matrix import service

    path = sys.argv[1] if len(sys.argv) > 1 else EXCEL_DEFAULT

    # ── matriz en vivo (misma vía que usa el exportador) ──
    async with async_session_maker() as db:
        res = await service.run_matrix(db, "04b", limit=None)
    matrix = res["rows"]
    by_sku: dict[str, list[dict]] = defaultdict(list)
    for r in matrix:
        by_sku[str(r.get("Código SKU") or "")].append(r)
    print(f"Matriz 04b: {len(matrix)} filas · {len(by_sku)} SKUs únicos")

    # ── Excel del usuario ──
    wb = load_workbook(path, data_only=True)
    excel_rows = []
    for sheet in wb.sheetnames:
        if sheet == "📊 Resumen":
            continue
        ws = wb[sheet]
        headers = None
        for row in ws.iter_rows(values_only=True):
            if headers is None and row and row[0] == "Tipo":
                headers = list(row)
                continue
            if headers and row[0] in ("▸ Producto", "⭐ Rescatable"):
                excel_rows.append(dict(zip(headers, row)))
    print(f"Excel: {len(excel_rows)} SKUs en hojas de departamento\n")

    # ── comparación ──
    err_stock, err_unds, err_clasif, err_st = [], [], [], []
    artefactos, no_encontrado = [], []
    for er in excel_rows:
        sku = str(er.get("SKU") or "")
        mrows = by_sku.get(sku)
        if not mrows:
            no_encontrado.append(sku)
            continue
        stock_m = sum(fnum(m.get("Stock Disp")) for m in mrows)
        unds_m = sum(fnum(m.get("Vend Lote Total")) for m in mrows)
        dom = max(mrows, key=lambda m: fnum(m.get("Vendido SKU S/")))
        clasif_m = str(dom.get("Clasificación") or "")
        st_m = dom.get("Sell-through Lote %")

        stock_e = fnum(er.get("Stock"))
        unds_e = fnum(er.get("Vend Lote"))
        clasif_e = str(er.get("Clasificación") or "")
        st_e = er.get("Sell-through %")

        if abs(stock_e - stock_m) > 0.01:
            err_stock.append((sku, stock_e, stock_m))
        if abs(unds_e - unds_m) > 0.01:
            err_unds.append((sku, unds_e, unds_m))
        if clasif_e.split(":")[0].strip() != clasif_m.split(":")[0].strip():
            err_clasif.append((sku, clasif_e[:40], clasif_m[:40]))
        if st_e is not None and st_m is not None:
            if abs(float(st_e) * 100 - float(st_m)) > 0.11:
                err_st.append((sku, float(st_e) * 100, float(st_m)))

        # artefacto: caja stock=0 pero stock consolidado >0
        if stock_e > 0 and any(c in clasif_e for c in CAJAS_STOCK0):
            otra = [m for m in mrows if m is not dom and fnum(m.get("Stock Disp")) > 0]
            artefactos.append((sku, clasif_e.split("—")[0].strip(), stock_e,
                               otra[0].get("Sucursal", "?") if otra else "?"))

    print("═══ FIDELIDAD EXCEL vs MATRIZ ═══")
    print(f"  SKUs no encontrados en matriz: {len(no_encontrado)}")
    for s in no_encontrado[:5]:
        print(f"    ✗ {s}")
    print(f"  Stock consolidado:    {len(err_stock)} errores")
    for s, e, m in err_stock[:5]:
        print(f"    ✗ {s}: excel={e} matriz={m}")
    print(f"  Vend Lote consolidado:{len(err_unds)} errores")
    for s, e, m in err_unds[:5]:
        print(f"    ✗ {s}: excel={e} matriz={m}")
    print(f"  Clasificación dominante: {len(err_clasif)} diferencias")
    for s, e, m in err_clasif[:8]:
        print(f"    ✗ {s}: excel='{e}' matriz='{m}'")
    print(f"  Sell-through %:       {len(err_st)} diferencias")
    for s, e, m in err_st[:5]:
        print(f"    ✗ {s}: excel={e:.1f} matriz={m:.1f}")

    print(f"\n═══ ARTEFACTOS DE CONSOLIDACIÓN ═══")
    print(f"  Caja de 'agotado' con stock consolidado >0: {len(artefactos)} SKUs")
    print(f"  (la caja viene de la sucursal dominante agotada; el stock, de la otra)")
    for s, c, st, suc in artefactos[:8]:
        print(f"    · {s}: '{c}' stock={st:.0f} (en {suc})")

    # ── divergencia de banda cobertura mostrada vs clasificante ──
    div = []
    for m in matrix:
        stock = fnum(m.get("Stock Disp"))
        if stock <= 0:
            continue
        cob_txt = str(m.get("Cobertura") or "")
        if cob_txt in ("s/d", "Agotado"):
            disp = None if cob_txt == "s/d" else 0.0
        elif cob_txt.startswith("+999"):
            disp = 9999.0
        else:
            try:
                disp = float(cob_txt.split(" ")[0])
            except ValueError:
                disp = None
        vida = m.get("Vida lote (días)")
        llego = m.get("Llegó hace (días)")
        cobrec = (float(vida) - float(llego)) if (vida is not None and llego is not None) else None
        if banda(disp) != banda(cobrec):
            div.append((m, disp, cobrec))
    print(f"\n═══ COBERTURA MOSTRADA (lifetime) vs CLASIFICANTE (reciente, P17) ═══")
    print(f"  Filas stock>0 en banda distinta: {len(div)} de "
          f"{sum(1 for m in matrix if fnum(m.get('Stock Disp')) > 0)}")
    for m, d, c in div[:8]:
        print(f"    · {m['Código SKU']} {str(m.get('Sucursal'))[:12]}: muestra {d} días, "
              f"clasifica con {c} → {str(m.get('Clasificación'))[:45]}")


if __name__ == "__main__":
    asyncio.run(main())
