"""
Migración segura: Crear tabla users, sincronizar, limpiar huérfanos, agregar FK.
Cada paso verifica el anterior antes de continuar.
"""
import sys
from pathlib import Path

root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from harvester import db
from harvester.sync_masters import sync_users

def run():
    db.init_pool()
    
    try:
        # ── PASO 1: Crear tabla users (IF NOT EXISTS = seguro) ──
        print("=" * 60)
        print("PASO 1: Creando tabla users...")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        bsale_user_id INTEGER PRIMARY KEY,
                        first_name VARCHAR(200),
                        last_name VARCHAR(200),
                        email VARCHAR(300),
                        bsale_office_id INTEGER REFERENCES offices(bsale_office_id),
                        is_active BOOLEAN DEFAULT TRUE NOT NULL,
                        synced_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_users_office ON users(bsale_office_id)
                """)
        print("  [OK] Tabla users creada (o ya existia)")

        # ── PASO 2: Sincronizar usuarios desde BSale ──
        print("\nPASO 2: Sincronizando usuarios desde BSale API...")
        stats = sync_users()
        print(f"  [OK] Usuarios sincronizados: {stats}")

        # Verificar que se insertaron
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                total_users = cur.fetchone()[0]
        print(f"  [OK] Total usuarios en tabla: {total_users}")

        if total_users == 0:
            print("  [WARN] No se encontraron usuarios en BSale.")
            print("         Los FK se agregarán igual (no hay conflicto si no hay datos).")

        # ── PASO 3: Limpiar huérfanos en documents ──
        print("\nPASO 3: Limpiando IDs huérfanos...")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                # Contar huérfanos en documents
                cur.execute("""
                    SELECT COUNT(*) FROM documents
                    WHERE bsale_user_id IS NOT NULL
                      AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users)
                """)
                orphan_docs = cur.fetchone()[0]
                print(f"  Documents con user_id huérfano: {orphan_docs}")

                if orphan_docs > 0:
                    cur.execute("""
                        UPDATE documents SET bsale_user_id = NULL
                        WHERE bsale_user_id IS NOT NULL
                          AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users)
                    """)
                    print(f"  [OK] {orphan_docs} documents limpiados (user_id -> NULL)")

                # Contar huérfanos en receptions
                cur.execute("""
                    SELECT COUNT(*) FROM receptions
                    WHERE bsale_user_id IS NOT NULL
                      AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users)
                """)
                orphan_recs = cur.fetchone()[0]
                print(f"  Receptions con user_id huérfano: {orphan_recs}")

                if orphan_recs > 0:
                    cur.execute("""
                        UPDATE receptions SET bsale_user_id = NULL
                        WHERE bsale_user_id IS NOT NULL
                          AND bsale_user_id NOT IN (SELECT bsale_user_id FROM users)
                    """)
                    print(f"  [OK] {orphan_recs} receptions limpiados (user_id -> NULL)")

        if orphan_docs == 0 and orphan_recs == 0:
            print("  [OK] No hay huérfanos, todo limpio")

        # ── PASO 4: Agregar FK constraints ──
        print("\nPASO 4: Agregando FK constraints...")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                # Verificar si el FK ya existe en documents
                cur.execute("""
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'documents_bsale_user_id_fkey'
                      AND table_name = 'documents'
                """)
                if cur.fetchone() is None:
                    cur.execute("""
                        ALTER TABLE documents
                            ADD CONSTRAINT documents_bsale_user_id_fkey
                            FOREIGN KEY (bsale_user_id) REFERENCES users(bsale_user_id)
                    """)
                    print("  [OK] FK documents -> users creada")
                else:
                    print("  [SKIP] FK documents -> users ya existia")

                # Verificar si el FK ya existe en receptions
                cur.execute("""
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'receptions_bsale_user_id_fkey'
                      AND table_name = 'receptions'
                """)
                if cur.fetchone() is None:
                    cur.execute("""
                        ALTER TABLE receptions
                            ADD CONSTRAINT receptions_bsale_user_id_fkey
                            FOREIGN KEY (bsale_user_id) REFERENCES users(bsale_user_id)
                    """)
                    print("  [OK] FK receptions -> users creada")
                else:
                    print("  [SKIP] FK receptions -> users ya existia")

        # ── PASO 5: Verificación final ──
        print("\nPASO 5: Verificación final...")
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT u.bsale_user_id, u.first_name, u.last_name, u.email, u.is_active
                    FROM users u ORDER BY u.bsale_user_id
                """)
                users = cur.fetchall()
                print(f"\n  {'ID':>5}  {'Nombre':25}  {'Email':30}  {'Activo'}")
                print(f"  {'─'*5}  {'─'*25}  {'─'*30}  {'─'*6}")
                for u in users:
                    nombre = f"{u[1] or ''} {u[2] or ''}".strip()
                    print(f"  {u[0]:>5}  {nombre:25}  {u[3] or '':30}  {'SI' if u[4] else 'NO'}")

                # Contar relaciones
                cur.execute("""
                    SELECT COUNT(DISTINCT bsale_user_id) FROM documents WHERE bsale_user_id IS NOT NULL
                """)
                docs_with_user = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(DISTINCT bsale_user_id) FROM receptions WHERE bsale_user_id IS NOT NULL
                """)
                recs_with_user = cur.fetchone()[0]

        print(f"\n  Usuarios distintos en documents:  {docs_with_user}")
        print(f"  Usuarios distintos en receptions: {recs_with_user}")

        print("\n" + "=" * 60)
        print("  MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)

    except Exception as exc:
        print(f"\n  [ERROR] La migración falló: {exc}")
        print("  Los cambios del paso actual se revirtieron automáticamente (rollback).")
        raise
    finally:
        db.close_pool()


if __name__ == "__main__":
    run()
