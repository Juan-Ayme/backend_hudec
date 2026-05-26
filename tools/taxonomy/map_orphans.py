#!/usr/bin/env python
"""
Script para mapear manualmente los product_types huérfanos.
NO elimina nada — solo asigna el category_id correcto y marca como mapped.

Uso:
    python map_orphans.py              # mapear los 3 por defecto
    python map_orphans.py --list       # listar huérfanos actuales
    python map_orphans.py --status     # verificar si quedaron mapeados
"""

import sys
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from harvester import db

MAPPINGS = {
    568: {"subcategory_id": 2638, "name": "BAMBU -> Productos de Bambu > Accesorios Varios de Bambu"},
    566: {"subcategory_id": 1157, "name": "Cuenco/Alcancia -> Tendencias Kawaii > Decoracion Kawaii > Alcancias Kawaii"},
    316: {"subcategory_id": 999,  "name": "Caramelo/Termo -> Hogar y Decoracion > Menaje de Cocina > Termos"},
}


def list_orphans():
    """Listar product_types sin mapear que tienen productos."""
    db.init_pool()
    try:
        with db.get_conn() as c, c.cursor() as cur:
            cur.execute("""
                SELECT pt.bsale_product_type_id, pt.name, COUNT(p.bsale_product_id)
                FROM product_types pt
                LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
                WHERE NOT pt.is_mapped
                GROUP BY 1,2 HAVING COUNT(p.bsale_product_id) > 0
                ORDER BY 3 DESC
            """)
            print("\nProductos huérfanos actuales:")
            for pt_id, pt_name, n_prods in cur.fetchall():
                print(f"  id={pt_id:4d}  prods={n_prods:2d}  {pt_name}")
            print()
    finally:
        db.close_pool()


def map_orphans():
    """Ejecutar los mappings."""
    db.init_pool()
    try:
        with db.get_conn() as c, c.cursor() as cur:
            print("\nAplicando mappings...\n")
            for pt_id, info in MAPPINGS.items():
                subcat_id = info["subcategory_id"]
                descr = info["name"]
                cur.execute(
                    "UPDATE product_types SET subcategory_id=%s, is_mapped=TRUE WHERE bsale_product_type_id=%s",
                    (subcat_id, pt_id),
                )
                rows = cur.rowcount
                print(f"  [{rows} row(s)] {pt_id}: {descr}")
            c.commit()
            print("\n[OK] Mappings aplicados correctamente")
    finally:
        db.close_pool()


def check_status():
    """Verificar estado después del mapeo."""
    db.init_pool()
    try:
        with db.get_conn() as c, c.cursor() as cur:
            print("\nVerificando estado...\n")
            for pt_id, _ in MAPPINGS.items():
                cur.execute(
                    "SELECT bsale_product_type_id, name, is_mapped, subcategory_id FROM product_types WHERE bsale_product_type_id=%s",
                    (pt_id,),
                )
                row = cur.fetchone()
                if row:
                    pt_id, name, is_mapped, subcat_id = row
                    status = "MAPEADO" if is_mapped else "SIN MAPEAR"
                    print(f"  {status}  id={pt_id}  subcat_id={subcat_id}  {name}")

            # Contar huérfanos restantes
            cur.execute("""
                SELECT COUNT(DISTINCT pt.bsale_product_type_id)
                FROM product_types pt
                LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
                WHERE NOT pt.is_mapped AND p.bsale_product_id IS NOT NULL
            """)
            total = cur.fetchone()[0]
            print(f"\nProductos huérfanos totales: {total}")
    finally:
        db.close_pool()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--list":
            list_orphans()
        elif cmd == "--status":
            check_status()
        else:
            print("Uso: python map_orphans.py [--list|--status]")
    else:
        # Ejecución por defecto: mapear
        list_orphans()
        input("\n¿Continuar con el mapeo? (Enter para sí, Ctrl+C para no)\n")
        map_orphans()
        check_status()
