"""
Simulacro de limpieza de product_types sin mapear.

Fase 1 (SIMULACRO): Analiza y reporta cuáles product_types sin mapear
se pueden eliminar con seguridad.

Verifica en BD local:
  - Productos asociados (tabla products)
  - Atributos asociados (tabla product_type_attributes)
  - Ventas históricas (vía document_details -> variants -> products)

Verifica en BSale API:
  - Estado actual (activo/inactivo) de cada product_type

Fase 2 (--execute): Elimina de BSale y de la BD local los candidatos seguros.

Uso:
  python simulacro_limpieza_product_types.py              # Solo simulacro
  python simulacro_limpieza_product_types.py --execute     # Ejecutar eliminación
"""

import sys
import json
import time
import logging
import io
from datetime import datetime
from pathlib import Path

# Resolver ruta raiz del proyecto para importaciones
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from harvester import db, bsale_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_unmapped_product_types():
    """Obtiene todos los product_types sin mapear de la BD local."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT bsale_product_type_id, name, is_active, is_mapped, synced_at
                FROM product_types
                WHERE NOT is_mapped
                ORDER BY name
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_mapped_product_types():
    """Obtiene todos los product_types mapeados de la BD local."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT bsale_product_type_id, name, is_active, is_mapped, subcategory_id
                FROM product_types
                WHERE is_mapped
                ORDER BY name
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def check_local_dependencies(pt_ids: list[int]) -> dict:
    """
    Verifica dependencias locales para una lista de product_type IDs.
    Retorna dict: {pt_id: {products: N, attributes: N, doc_details: N, variants: N}}
    """
    result = {}
    if not pt_ids:
        return result

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Productos asociados
            cur.execute("""
                SELECT bsale_product_type_id, COUNT(*) as cnt
                FROM products
                WHERE bsale_product_type_id = ANY(%s)
                GROUP BY bsale_product_type_id
            """, (pt_ids,))
            product_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 2. Atributos asociados
            cur.execute("""
                SELECT bsale_product_type_id, COUNT(*) as cnt
                FROM product_type_attributes
                WHERE bsale_product_type_id = ANY(%s)
                GROUP BY bsale_product_type_id
            """, (pt_ids,))
            attr_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 3. Variantes asociadas (via products)
            cur.execute("""
                SELECT p.bsale_product_type_id, COUNT(v.bsale_variant_id) as cnt
                FROM products p
                JOIN variants v ON v.bsale_product_id = p.bsale_product_id
                WHERE p.bsale_product_type_id = ANY(%s)
                GROUP BY p.bsale_product_type_id
            """, (pt_ids,))
            variant_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 4. Ventas históricas (via document_details -> variants -> products)
            cur.execute("""
                SELECT p.bsale_product_type_id, COUNT(dd.bsale_detail_id) as cnt
                FROM products p
                JOIN variants v ON v.bsale_product_id = p.bsale_product_id
                JOIN document_details dd ON dd.bsale_variant_id = v.bsale_variant_id
                WHERE p.bsale_product_type_id = ANY(%s)
                GROUP BY p.bsale_product_type_id
            """, (pt_ids,))
            sales_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 5. Stock levels
            cur.execute("""
                SELECT p.bsale_product_type_id, COUNT(sl.bsale_stock_id) as cnt
                FROM products p
                JOIN variants v ON v.bsale_product_id = p.bsale_product_id
                JOIN stock_levels sl ON sl.bsale_variant_id = v.bsale_variant_id
                WHERE p.bsale_product_type_id = ANY(%s)
                GROUP BY p.bsale_product_type_id
            """, (pt_ids,))
            stock_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 6. Recepciones
            cur.execute("""
                SELECT p.bsale_product_type_id, COUNT(rd.bsale_reception_detail_id) as cnt
                FROM products p
                JOIN variants v ON v.bsale_product_id = p.bsale_product_id
                JOIN reception_details rd ON rd.bsale_variant_id = v.bsale_variant_id
                WHERE p.bsale_product_type_id = ANY(%s)
                GROUP BY p.bsale_product_type_id
            """, (pt_ids,))
            reception_counts = {row[0]: row[1] for row in cur.fetchall()}

    for pt_id in pt_ids:
        result[pt_id] = {
            "products": product_counts.get(pt_id, 0),
            "attributes": attr_counts.get(pt_id, 0),
            "variants": variant_counts.get(pt_id, 0),
            "sales": sales_counts.get(pt_id, 0),
            "stock_levels": stock_counts.get(pt_id, 0),
            "receptions": reception_counts.get(pt_id, 0),
        }

    return result


def check_bsale_status(pt_ids: list[int]) -> dict:
    """
    Consulta BSale API para verificar el estado real de cada product_type.
    Retorna dict: {pt_id: {exists: bool, state: int, name: str, ...}}
    """
    result = {}
    total = len(pt_ids)

    for i, pt_id in enumerate(pt_ids):
        if (i + 1) % 20 == 0 or i == 0:
            logger.info(f"  Verificando en BSale... {i+1}/{total}")

        try:
            data = bsale_client.fetch(
                f"https://api.bsale.io/v1/product_types/{pt_id}.json"
            )
            if data and "id" in data:
                result[pt_id] = {
                    "exists": True,
                    "state": data.get("state", -1),
                    "name": data.get("name", ""),
                    "isEditable": data.get("isEditable", None),
                    "productsCount": data.get("productsCount",
                                               data.get("products_count", None)),
                }
            else:
                result[pt_id] = {"exists": False, "state": -1, "name": ""}
        except Exception as e:
            logger.warning(f"  Error consultando BSale para pt_id={pt_id}: {e}")
            result[pt_id] = {"exists": False, "state": -1, "name": "", "error": str(e)}

    return result


def execute_deletion(candidates: list[dict]):
    """
    Ejecuta la eliminación real de los candidatos en BSale y BD local.
    """
    deleted_bsale = 0
    deleted_local = 0
    errors = []
    skipped = []

    total = len(candidates)
    print(f"\n{'='*70}")
    print(f"  EJECUTANDO ELIMINACIÓN DE {total} PRODUCT_TYPES")
    print(f"{'='*70}\n")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for i, c in enumerate(candidates):
                pt_id = c["bsale_product_type_id"]
                pt_name = c["name"]
                bsale_exists = c.get("bsale_exists", True)

                try:
                    # 1. Intentar eliminar de BSale (si existe allí)
                    if bsale_exists:
                        try:
                            bsale_client.delete(f"product_types/{pt_id}.json")
                            deleted_bsale += 1
                            print(f"  [{i+1}/{total}] ✓ BSale DELETE OK: {pt_name} (ID: {pt_id})")
                        except RuntimeError as e:
                            err_str = str(e)
                            if "404" in err_str:
                                print(f"  [{i+1}/{total}] ~ BSale 404 (ya no existe): {pt_name} (ID: {pt_id})")
                            elif "400" in err_str or "422" in err_str:
                                print(f"  [{i+1}/{total}] ✗ BSale rechazó DELETE (en uso): {pt_name} (ID: {pt_id})")
                                skipped.append({"id": pt_id, "name": pt_name, "reason": err_str})
                                continue  # No eliminar de local si BSale rechaza
                            else:
                                raise
                    else:
                        print(f"  [{i+1}/{total}] ~ No existe en BSale, solo eliminando local: {pt_name} (ID: {pt_id})")

                    # 2. Eliminar atributos asociados primero (FK)
                    cur.execute(
                        "DELETE FROM product_type_attributes WHERE bsale_product_type_id = %s",
                        (pt_id,)
                    )

                    # 3. Eliminar de BD local
                    cur.execute(
                        "DELETE FROM product_types WHERE bsale_product_type_id = %s",
                        (pt_id,)
                    )
                    deleted_local += 1

                except Exception as e:
                    print(f"  [{i+1}/{total}] ✗ ERROR: {pt_name} (ID: {pt_id}): {e}")
                    errors.append({"id": pt_id, "name": pt_name, "error": str(e)})

            conn.commit()

    return {
        "deleted_bsale": deleted_bsale,
        "deleted_local": deleted_local,
        "errors": errors,
        "skipped": skipped,
    }


def main():
    execute_mode = len(sys.argv) > 1 and sys.argv[1] == "--execute"

    print(f"\n{'='*70}")
    print(f"  SIMULACRO DE LIMPIEZA DE PRODUCT_TYPES SIN MAPEAR")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Modo: {'[!!] EJECUCION REAL' if execute_mode else '[SIM] SIMULACRO (dry-run)'}")
    print(f"{'='*70}\n")

    db.init_pool()
    try:
        # ============================================================
        # PASO 1: Obtener product_types de la BD local
        # ============================================================
        print("[1] PASO 1: Consultando BD local...")
        unmapped = get_unmapped_product_types()
        mapped = get_mapped_product_types()

        print(f"  Product_types mapeados:    {len(mapped)}")
        print(f"  Product_types sin mapear:  {len(unmapped)}")
        print(f"  Total:                     {len(mapped) + len(unmapped)}")

        if not unmapped:
            print("\n[OK] No hay product_types sin mapear. Nada que limpiar.")
            return

        # ============================================================
        # PASO 2: Verificar dependencias locales
        # ============================================================
        print(f"\n[2] PASO 2: Verificando dependencias en BD local para {len(unmapped)} sin mapear...")
        pt_ids = [pt["bsale_product_type_id"] for pt in unmapped]
        deps = check_local_dependencies(pt_ids)

        # Clasificar
        sin_dependencias = []
        con_dependencias = []

        for pt in unmapped:
            pt_id = pt["bsale_product_type_id"]
            d = deps.get(pt_id, {})
            total_deps = sum(d.values())

            pt["deps"] = d
            pt["total_deps"] = total_deps

            if total_deps == 0:
                sin_dependencias.append(pt)
            else:
                con_dependencias.append(pt)

        print(f"\n  Resultado del analisis de dependencias:")
        print(f"  |-- Sin dependencias (candidatos a eliminar):  {len(sin_dependencias)}")
        print(f"  +-- Con dependencias (se conservan):           {len(con_dependencias)}")

        if con_dependencias:
            print(f"\n  [!] Product_types sin mapear PERO con datos asociados:")
            for pt in con_dependencias[:30]:
                d = pt["deps"]
                print(f"      - {pt['name']} (ID: {pt['bsale_product_type_id']})")
                print(f"        productos={d['products']} variantes={d['variants']} "
                      f"ventas={d['sales']} stock={d['stock_levels']} "
                      f"atribs={d['attributes']} recepciones={d['receptions']}")
            if len(con_dependencias) > 30:
                print(f"      ... y {len(con_dependencias) - 30} más")

        if not sin_dependencias:
            print("\n[!] Todos los product_types sin mapear tienen dependencias. No se puede eliminar ninguno de forma segura.")
            return

        # ============================================================
        # PASO 3: Verificar estado en BSale API
        # ============================================================
        print(f"\n[3] PASO 3: Verificando estado en BSale API para {len(sin_dependencias)} candidatos...")
        bsale_status = check_bsale_status([pt["bsale_product_type_id"] for pt in sin_dependencias])

        # Enriquecer candidatos con info de BSale
        eliminables = []
        no_encontrados_bsale = []

        for pt in sin_dependencias:
            pt_id = pt["bsale_product_type_id"]
            bs = bsale_status.get(pt_id, {})
            pt["bsale_exists"] = bs.get("exists", False)
            pt["bsale_state"] = bs.get("state", -1)
            pt["bsale_products_count"] = bs.get("productsCount")

            if bs.get("exists"):
                # Existe en BSale - verificar si tiene productos allá
                bsale_prods = bs.get("productsCount")
                if bsale_prods is not None and bsale_prods > 0:
                    # Tiene productos en BSale aunque no en nuestra BD local
                    pt["nota"] = f"⚠️ BSale reporta {bsale_prods} productos"
                eliminables.append(pt)
            else:
                # No existe en BSale (ya fue eliminado o nunca existió allá)
                no_encontrados_bsale.append(pt)
                eliminables.append(pt)  # También eliminar de local

        # ============================================================
        # PASO 4: Reporte final
        # ============================================================
        print(f"\n{'='*70}")
        print(f"  REPORTE FINAL DEL SIMULACRO")
        print(f"{'='*70}\n")

        # Contadores por estado en BSale
        activos_bsale = [pt for pt in eliminables if pt.get("bsale_state") == 0]
        inactivos_bsale = [pt for pt in eliminables if pt.get("bsale_state") == 1]
        no_en_bsale = [pt for pt in eliminables if not pt.get("bsale_exists")]
        activos_local = [pt for pt in eliminables if pt.get("is_active")]
        inactivos_local = [pt for pt in eliminables if not pt.get("is_active")]

        print(f"  Resumen de {len(eliminables)} product_types eliminables:")
        print(f"  |-- Estado en BSale:")
        print(f"  |   |-- Activos (state=0):    {len(activos_bsale)}")
        print(f"  |   |-- Inactivos (state=1):  {len(inactivos_bsale)}")
        print(f"  |   +-- No existen en BSale:  {len(no_en_bsale)}")
        print(f"  +-- Estado en BD local:")
        print(f"      |-- Activos:    {len(activos_local)}")
        print(f"      +-- Inactivos:  {len(inactivos_local)}")

        # Separar los que tienen advertencia de productos en BSale
        con_prods_bsale = [pt for pt in eliminables if pt.get("nota")]
        sin_prods_bsale = [pt for pt in eliminables if not pt.get("nota")]

        if con_prods_bsale:
            print(f"\n  [!] {len(con_prods_bsale)} tienen productos en BSale (NO se eliminaran):")
            for pt in con_prods_bsale[:20]:
                print(f"      - {pt['name']} (ID: {pt['bsale_product_type_id']}) {pt['nota']}")
            # Remover estos de eliminables
            eliminables = sin_prods_bsale

        print(f"\n  [OK] {len(eliminables)} product_types se pueden eliminar con SEGURIDAD TOTAL:")
        print(f"     - 0 productos en BD local")
        print(f"     - 0 variantes")
        print(f"     - 0 ventas históricas")
        print(f"     - 0 stock")
        print(f"     - 0 recepciones")
        if not con_prods_bsale:
            print(f"     - 0 productos reportados por BSale API")

        # Listar algunos ejemplos
        print(f"\n  Primeros 30 candidatos:")
        for pt in eliminables[:30]:
            estado_local = "Inactiva" if not pt["is_active"] else "Activa"
            estado_bsale = "No en BSale" if not pt["bsale_exists"] else (
                "Inactiva" if pt["bsale_state"] == 1 else "Activa"
            )
            print(f"    - {pt['name']} (ID: {pt['bsale_product_type_id']}, "
                  f"Local: {estado_local}, BSale: {estado_bsale})")
        if len(eliminables) > 30:
            print(f"    ... y {len(eliminables) - 30} más")

        # ============================================================
        # Guardar reporte JSON
        # ============================================================
        report = {
            "fecha": datetime.now().isoformat(),
            "modo": "EJECUCION" if execute_mode else "SIMULACRO",
            "resumen": {
                "total_product_types": len(mapped) + len(unmapped),
                "mapeados": len(mapped),
                "sin_mapear": len(unmapped),
                "sin_dependencias": len(sin_dependencias),
                "con_dependencias": len(con_dependencias),
                "eliminables": len(eliminables),
                "con_productos_bsale": len(con_prods_bsale),
            },
            "eliminables": [
                {
                    "bsale_product_type_id": pt["bsale_product_type_id"],
                    "name": pt["name"],
                    "is_active_local": pt["is_active"],
                    "bsale_exists": pt.get("bsale_exists"),
                    "bsale_state": pt.get("bsale_state"),
                }
                for pt in eliminables
            ],
            "con_dependencias": [
                {
                    "bsale_product_type_id": pt["bsale_product_type_id"],
                    "name": pt["name"],
                    "deps": pt["deps"],
                }
                for pt in con_dependencias
            ],
        }

        report_path = "simulacro_limpieza_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  Reporte guardado en: {report_path}")

        # ============================================================
        # PASO 5: Ejecutar (si --execute)
        # ============================================================
        if execute_mode:
            print(f"\n{'='*70}")
            print(f"  [!!] MODO EJECUCION: Se eliminaran {len(eliminables)} product_types")
            print(f"{'='*70}")

            result = execute_deletion(eliminables)

            print(f"\n{'='*70}")
            print(f"  RESULTADO DE LA EJECUCION:")
            print(f"  |-- Eliminados de BSale:  {result['deleted_bsale']}")
            print(f"  |-- Eliminados de BD local: {result['deleted_local']}")
            print(f"  |-- Errores:              {len(result['errors'])}")
            print(f"  +-- Saltados por BSale:   {len(result['skipped'])}")
            print(f"{'='*70}\n")

            # Actualizar reporte con resultados
            report["resultado_ejecucion"] = result
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)

            # Verificación post-eliminación
            print("Verificacion post-eliminacion...")
            unmapped_post = get_unmapped_product_types()
            mapped_post = get_mapped_product_types()
            print(f"  Product_types mapeados:    {len(mapped_post)}")
            print(f"  Product_types sin mapear:  {len(unmapped_post)}")
            print(f"  Total:                     {len(mapped_post) + len(unmapped_post)}")
        else:
            print(f"\n  Para ejecutar la eliminacion real, usa:")
            print(f"     python simulacro_limpieza_product_types.py --execute")

    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
