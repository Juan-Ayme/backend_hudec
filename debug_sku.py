import os
import asyncio
from decimal import Decimal

os.environ["TIMEZONE"] = "America/Lima"

from app.database import async_session_maker
from app.kawii_matrix.service import run_matrix

async def main():
    async with async_session_maker() as session:
        sku = "JIN-1174"
        
        print(f"Buscando SKU: {sku}...")
        
        # 1. Obtenemos datos de las matrices base
        matrix_04 = await run_matrix(session, "04", limit=99999)
        
        rows = [r for r in matrix_04["rows"] if r.get("Código SKU") == sku]
        
        print("\n=== ESTADO DEL SKU EN CADA SUCURSAL (Matriz 04) ===")
        if not rows:
            print("El SKU NO APARECE en la matriz 04 base. Podría estar filtrado por exclusión de taxonomía o inactivo.")
            
        print("\n=== EVALUACIÓN EN MATRIZ DE TRASLADOS 08 ===")
        matrix_08 = await run_matrix(session, "08", limit=99999)
        rows_08 = [r for r in matrix_08["rows"] if r.get("SKU") == sku]
        
        output = {
            "sku": sku,
            "matriz_04": rows,
            "matriz_08": rows_08
        }
        
        with open("debug_sku_output.json", "w", encoding="utf-8") as f:
            import json
            json.dump(output, f, default=str, indent=2)
            
        print("Done. Check debug_sku_output.json")

if __name__ == "__main__":
    asyncio.run(main())
