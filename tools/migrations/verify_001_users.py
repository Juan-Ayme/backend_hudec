"""Verificar que la tabla users se creo correctamente."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from harvester import db

db.init_pool()

with db.get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT bsale_user_id, first_name, last_name, email, is_active FROM users ORDER BY bsale_user_id")
        rows = cur.fetchall()
        print(f"Total: {len(rows)} usuarios\n")
        print(f"  {'ID':>5}  {'Nombre':25}  {'Email':30}  Activo")
        print(f"  {'-----':>5}  {'-------------------------':25}  {'------------------------------':30}  ------")
        for r in rows:
            nombre = ((r[1] or "") + " " + (r[2] or "")).strip()
            print(f"  {r[0]:>5}  {nombre:25}  {r[3] or '':30}  {'SI' if r[4] else 'NO'}")

        # Relaciones
        cur.execute("SELECT COUNT(DISTINCT bsale_user_id) FROM documents WHERE bsale_user_id IS NOT NULL")
        d = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT bsale_user_id) FROM receptions WHERE bsale_user_id IS NOT NULL")
        r2 = cur.fetchone()[0]

        # FK constraints
        cur.execute("""
            SELECT constraint_name, table_name
            FROM information_schema.table_constraints
            WHERE constraint_name IN ('documents_bsale_user_id_fkey', 'receptions_bsale_user_id_fkey')
        """)
        fks = cur.fetchall()

print(f"\nUsuarios distintos en documents:  {d}")
print(f"Usuarios distintos en receptions: {r2}")
print(f"\nFK constraints activas: {len(fks)}")
for fk in fks:
    print(f"  - {fk[0]} ({fk[1]})")

print("\nTodo OK!" if len(fks) == 2 else "\nALERTA: Faltan FK constraints")

db.close_pool()
