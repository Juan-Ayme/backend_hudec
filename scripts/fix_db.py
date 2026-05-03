"""
fix_db.py — Script de parche para la base de datos.

PROPOSITO:
    Aplica cambios estructurales puntuales a la base de datos PostgreSQL
    que no estan cubiertos por el schema.sql inicial.

QUE HACE EXACTAMENTE:
    1. Agrega la columna `subcategory_id` a la tabla `products`.
       Esta columna permite hacer un "override" individual: asignar un producto
       a una subcategoria distinta a la de su product_type padre.

    2. Crea (o reemplaza) la vista `v_products_full`.
       Esta vista une products + product_types + la taxonomia completa
       (departments/categories/subcategories). Es la base de todos los
       reportes de catalogo del dashboard.

CUANDO EJECUTARLO:
    - Solo una vez, si la columna o la vista no existen en la BD.
    - Es seguro volver a ejecutar (usa ADD COLUMN IF NOT EXISTS y CREATE OR REPLACE VIEW).
    - Normalmente ya fue ejecutado. Ver ESTADO_PROYECTO.md.

COMO EJECUTAR:
    cd produccion
    python scripts/fix_db.py
"""

import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from harvester.config import DB_CONFIG

def fix_db():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    print("Agregando subcategory_id a products...")
    cur.execute("""
        ALTER TABLE products ADD COLUMN IF NOT EXISTS subcategory_id INT REFERENCES subcategories(id) ON DELETE SET NULL;
    """)

    print("Creando vista v_products_full...")
    cur.execute("""
        CREATE OR REPLACE VIEW v_products_full AS
        SELECT
            p.bsale_product_id,
            p.name AS product_name,
            p.is_active,
            pt.bsale_product_type_id,
            pt.name AS product_type_name,
            pt.is_mapped AS is_mapped,
            p.subcategory_id IS NOT NULL AS has_override,
            s.name AS subcategory,
            c.name AS category,
            d.name AS department
        FROM products p
        LEFT JOIN product_types pt ON p.bsale_product_type_id = pt.bsale_product_type_id
        LEFT JOIN subcategories s ON s.id = COALESCE(p.subcategory_id, pt.subcategory_id)
        LEFT JOIN categories c ON c.id = s.category_id
        LEFT JOIN departments d ON d.id = c.department_id;
    """)

    print("Todo listo.")
    cur.close()
    conn.close()

if __name__ == '__main__':
    fix_db()
