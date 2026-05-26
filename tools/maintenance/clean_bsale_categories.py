import sys
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from harvester import db, bsale_client
from app.database import fetch_all

def list_candidates():
    db.init_pool()
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT pt.bsale_product_type_id AS id, pt.name, pt.is_active
                FROM product_types pt
                LEFT JOIN products p ON p.bsale_product_type_id = pt.bsale_product_type_id
                WHERE NOT pt.is_mapped
                GROUP BY pt.bsale_product_type_id, pt.name, pt.is_active
                HAVING COUNT(p.bsale_product_id) = 0
                ORDER BY pt.name
            """)
            
            # Convert to list of dicts
            cols = [desc[0] for desc in cur.description]
            candidates = [dict(zip(cols, row)) for row in cur.fetchall()]
            return candidates
    finally:
        db.close_pool()

def main():
    candidates = list_candidates()
    
    print(f"\nSe han encontrado {len(candidates)} categorias (product_types) obsoletas en tu BD local.")
    print("Estas categorias NO estan mapeadas a tu taxonomia y tienen 0 productos asociados.")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        print("\nIniciando limpieza en BSale y BD Local...\n")
        deleted_count = 0
        error_count = 0
        
        db.init_pool()
        try:
            with db.get_conn() as conn, conn.cursor() as cur:
                for c in candidates:
                    pt_id = c["id"]
                    pt_name = c["name"]
                    
                    try:
                        # Call BSale API DELETE
                        # Note: Requests might fail if BSale prevents deletion due to historical sales
                        bsale_client.delete(f"product_types/{pt_id}.json")
                        
                        # BSale either deletes it or throws an error. If we get here, it succeeded.
                        # Delete from local DB
                        cur.execute("DELETE FROM product_types WHERE bsale_product_type_id = %s", (pt_id,))
                        deleted_count += 1
                        print(f" [OK] Eliminado permanentemente: {pt_name} (ID: {pt_id})")
                        
                    except Exception as e:
                        error_count += 1
                        err_msg = str(e)
                        if "foreign key" in err_msg.lower() or "reference" in err_msg.lower() or "400" in err_msg:
                            print(f" [!] No se pudo eliminar (probablemente en uso histórico en BSale): {pt_name} (ID: {pt_id})")
                            
                            # Si no se puede borrar de BSale, al menos lo inactivamos en BSale si no lo estaba
                            # (Opcional, pero por ahora solo avisamos)
                        else:
                            print(f" [ERROR] Falló {pt_name} (ID: {pt_id}): {err_msg}")
                            
                conn.commit()
        finally:
            db.close_pool()
            
        print(f"\nResumen: Eliminados exitosamente = {deleted_count}, Retenidos por BSale (uso histórico) = {error_count}")
    else:
        # Just list them
        print("\nEjemplo de categorias que se eliminaran:")
        for c in candidates[:20]:
            estado = "Inactiva" if not c["is_active"] else "Activa"
            print(f" - {c['name']} (ID: {c['id']}, {estado})")
            
        if len(candidates) > 20:
            print(f"   ... y {len(candidates) - 20} mas.")
            
        print("\nPara eliminarlas permanentemente en BSale y en tu base de datos local, ejecuta:")
        print("  python clean_bsale_categories.py --execute")

if __name__ == "__main__":
    main()
