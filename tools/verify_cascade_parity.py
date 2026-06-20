"""Script de paridad SQL ↔ TS para la cascada de clasificación.

Toma N SKUs aleatorios del módulo 04 y, para cada uno:
  1. Recupera la clasificación del SQL via service.run_matrix(db, '04', sku=X).
  2. Llama al backend matrix_simulator.get_sku_detail para los metrics crudos.
  3. Ejecuta la cascada TS pipeando JSON a frontend_hudec/scripts/cascade-stdin.ts (tsx).
  4. Compara el rule_id matched (TS) contra la etiqueta del SQL — si difiere, reporta.

NO necesita servidores levantados — todo corre con conexiones directas a la DB.
Requiere: python (con app.* importable), npm/npx en PATH, frontend_hudec instalado.

Uso:
    python tools/verify_cascade_parity.py --n 200
    python tools/verify_cascade_parity.py --skus EP-9534,1000-2,77204702130714
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# Permitir correr el script desde cualquier cwd: el backend root es 2 niveles arriba.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ruta al frontend (debe estar al lado del backend, ajustar si tu setup difiere)
_FRONT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend_hudec"
_TSX_SCRIPT = _FRONT_DIR / "scripts" / "cascade-stdin.ts"


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"unsupported {type(o).__name__}")


def _run_ts(detail: dict) -> dict:
    payload = json.dumps(detail, default=_json_default).encode("utf-8")
    p = subprocess.run(
        ["npx", "--prefix", str(_FRONT_DIR), "tsx", str(_TSX_SCRIPT)],
        input=payload,
        capture_output=True,
        shell=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"tsx error: {p.stderr.decode('utf-8', errors='replace')[:300]}")
    out = p.stdout.decode("utf-8").strip().split("\n")[-1]
    return json.loads(out)


def _sql_label_to_rule_id(label: str) -> str:
    """Mapea la etiqueta de display del SQL al rule_id que usa la cascada TS.

    Las etiquetas SQL llevan emoji+texto+":"+descripción. Reconocemos por el
    verbo/keyword distintivo de cada regla.
    """
    L = (label or "").upper()
    if "DEMANDA EXTINTA" in L:                          return "demanda_extinta"
    if "OPORTUNIDAD PERDIDA" in L:                      return "oportunidad_perdida"
    if "BESTSELLER" in L and "AGOTADO" in L:            return "bestseller_pausado"
    if "BESTSELLER ACTIVO" in L:                        return "bestseller_activo"
    if "LENTO PERO CONSTANTE" in L:                     return "lento_constante"
    if "QUIEBRE DE BESTSELLER" in L:                    return "quiebre_bestseller"
    if "AGOTADO CON DEMANDA" in L:                      return "agotado_potencial_activo"
    if "EX-BESTSELLER ENFRIADO" in L:                   return "ex_bestseller_enfriado"
    if "PRODUCTO EMERGENTE" in L:                       return "producto_emergente"
    if "PRODUCTO MUERTO" in L:                          return "residuo_historico"
    if "RECIBIDO Y NO VENDIDO" in L:                    return "recibido_no_vendido"
    if "BAJO VOLUMEN AGOTADO" in L:                     return "bajo_volumen_agotado"
    if "AGOTADO NO PRIORITARIO" in L:                   return "agotado_no_prioritario"
    if "STOCK RECIÉN LLEGADO" in L or "STOCK RECIEN" in L: return "stock_recien_llegado"
    if "STOCK PARADO 90" in L:                          return "stock_parado_90d"
    if "STOCK BAJO QUIETO" in L:                        return "stock_bajo_quieto"
    if "LOTE NUEVO VENDIENDO BIEN" in L:                return "lote_nuevo_vendiendo_bien"
    if "RECIÉN REABASTECIDO" in L or "RECIEN REABASTEC" in L: return "recien_reabastecido"
    # Rule 25 (FIX P24, sección E) — fresca: contiene "AL RITMO DEL LOTE".
    #   Rule 30 también contiene "LOTE LLEGÓ" en el texto, así que el discriminador
    #   correcto es la frase "AL RITMO DEL LOTE" que solo aparece en la FRESH.
    if "ROTACIÓN ACTIVA AL BORDE" in L and "AL RITMO DEL LOTE" in L: return "rotacion_activa_al_borde_fresco"
    if "ALTA ROTACIÓN" in L and "LOTE LLEGÓ" in L:      return "alta_rotacion_lote_fresco"
    if "ALTA ROTACIÓN" in L and "BAJANDO" in L:         return "rotacion_bajando"
    if "ROTACIÓN BAJANDO" in L:                         return "rotacion_bajando"
    if "ALTA ROTACIÓN" in L:                            return "alta_rotacion"
    if "ROTACIÓN ACTIVA AL BORDE" in L:                 return "rotacion_activa_al_borde"
    if "ROTACIÓN ACTIVA" in L:                          return "rotacion_activa_mantener"
    if "INVENTARIO SANO" in L:                          return "inventario_sano"
    if "EXCESO + DEMANDA CAYENDO" in L:                 return "exceso_demanda_cayendo"
    if "STOCK EXCESIVO" in L or "EXCESO DE INVENTARIO" in L: return "exceso_inventario"
    if "LENTO CRÓNICO" in L:                            return "lento_cronico"
    if "POCO STOCK CON DEMANDA" in L:                   return "stock_critico_baja_rotacion"
    if "VENDIENDO MÁS QUE ANTES" in L or "BAJO VOLUMEN EN ALZA" in L: return "bajo_volumen_en_alza"
    if "BAJA ROTACIÓN" in L:                            return "baja_rotacion"
    if "RITMO PERDIDO" in L:                            return "ritmo_perdido"
    if "LOTE FRENADO" in L:                             return "lote_frenado_liquidar"
    if "PRODUCTO NUEVO" in L:                           return "producto_nuevo"
    if "TEMPORADA CERRADA" in L:                        return "temporada_cerrada_ok"
    if "SALDO DE TEMPORADA" in L or "SOBRANTE" in L:    return "sobrante_temporada"
    if "PÉRDIDA DE STOCK" in L:                         return "perdida_total_control_fisico"
    if "VENDIÓ Y SE PERDIÓ" in L:                       return "vendio_con_perdida_investigar"
    if "CASO ATÍPICO" in L:                             return "caso_atipico"
    return "(unknown:" + L[:50] + ")"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="cantidad de SKUs random a verificar")
    parser.add_argument("--skus", type=str, default=None, help="lista comma-separated de SKUs específicos")
    parser.add_argument("--module", default="04", help="módulo de matriz a usar como fuente (default 04)")
    args = parser.parse_args()

    # Import lazy para no tirar errores si solo se quiere --help
    from app.database import async_session_maker
    from app.kawii_matrix import service
    from app.routers import matrix_simulator as ms

    async with async_session_maker() as db:
        if args.skus:
            target_skus = [s.strip() for s in args.skus.split(",") if s.strip()]
        else:
            print(f"Cargando matriz {args.module} para muestrear {args.n} SKUs...")
            full = await service.run_matrix(db, args.module, limit=None)
            all_skus = {str(r.get("Código SKU")) for r in full["rows"] if r.get("Código SKU")}
            target_skus = random.sample(list(all_skus), min(args.n, len(all_skus)))
            print(f"  universo SKUs: {len(all_skus)}, muestrearemos: {len(target_skus)}")

        matches = 0
        mismatches = []
        errors = []

        for i, sku in enumerate(target_skus, 1):
            if i % 25 == 0:
                print(f"  [{i}/{len(target_skus)}] OK={matches} mismatch={len(mismatches)} err={len(errors)}")
            try:
                detail = await ms.get_sku_detail(sku, db)
                ts_result = _run_ts(detail)
            except Exception as e:
                errors.append((sku, str(e)[:200]))
                continue
            sql_res = await service.run_matrix(db, args.module, sku=sku, limit=10)
            sql_by_office: dict[str, str] = {}
            for r in sql_res["rows"]:
                for k in r:
                    if "lasific" in k.lower():
                        sql_by_office[str(r.get("Sucursal"))] = str(r.get(k) or "")
                        break
            for off in ts_result.get("offices", []):
                sql_label = sql_by_office.get(off["sucursal"], "")
                sql_id = _sql_label_to_rule_id(sql_label)
                ts_id = off.get("matched_id") or "(no_match)"
                if ts_id == sql_id:
                    matches += 1
                else:
                    mismatches.append({"sku": sku, "sucursal": off["sucursal"], "sql": sql_id, "ts": ts_id, "sql_label": sql_label[:60]})

        total = matches + len(mismatches)
        print(f"\n========== RESUMEN ==========")
        print(f"SKUs verificados: {len(target_skus)}")
        print(f"Evaluaciones totales (sku x sucursal): {total}")
        print(f"OK: {matches}  ({100*matches/total:.1f}%)" if total else "  (sin datos)")
        print(f"Mismatches: {len(mismatches)}")
        print(f"Errores: {len(errors)}")

        if mismatches:
            print("\n--- Primeros 30 mismatches ---")
            for m in mismatches[:30]:
                print(f"  {m['sku']:18} {m['sucursal']:18}  SQL='{m['sql']}'  TS='{m['ts']}'")
                print(f"    SQL label: {m['sql_label']}")
        if errors:
            print("\n--- Primeros 5 errores ---")
            for sku, msg in errors[:5]:
                print(f"  {sku}: {msg}")

        sys.exit(1 if (mismatches or errors) else 0)


if __name__ == "__main__":
    asyncio.run(main())
