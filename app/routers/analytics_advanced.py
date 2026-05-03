"""
Endpoints de analisis avanzado — consumibles por el frontend.

Ticket Promedio (basico):
  GET /analytics/ticket/trend           Tendencia mensual + variacion %
  GET /analytics/ticket/by-office       Por sucursal
  GET /analytics/ticket/depth           Profundidad (items/ticket) + diagnostico
  GET /analytics/ticket/by-category     Por categoria (arrastra vs impulsa)
  GET /analytics/ticket/diagnosis       Diagnostico ejecutivo completo

Ticket Promedio (avanzado — causa raiz cuantitativa):
  GET /analytics/ticket/waterfall       Descomposicion Laspeyres (precio/mix/items)
  GET /analytics/ticket/distribution    Percentiles P10-P95 inicio vs reciente
  GET /analytics/ticket/category-mix    Categorias que ganaron/perdieron share
  GET /analytics/ticket/by-weekday      Patron por dia de semana
  GET /analytics/ticket/anchor-products Productos de alto valor que perdieron share
  GET /analytics/ticket/advanced-diagnosis Veredicto ejecutivo consolidado

Inventario:
  GET /analytics/inventory/abc-xyz      Matriz ABC × XYZ completa
  GET /analytics/inventory/alerts       Solo productos BAJO ROP (para dashboard)
  GET /analytics/inventory/rop          Safety Stock + ROP todos los productos
  GET /analytics/inventory/eoq          Economic Order Quantity por producto
  GET /analytics/inventory/gmroi        GMROI + Inventory Turnover

Informe PDF:
  GET /analytics/report/pdf             Genera y descarga el informe PDF completo

Todos los endpoints devuelven JSON (excepto /report/pdf que devuelve PDF).
Los campos numericos estan redondeados para el frontend.
Los NaN/None se serializan como null.
"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

logger = logging.getLogger("kawii.api.analytics_advanced")

router = APIRouter(prefix="/analytics", tags=["analytics-advanced"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _run(fn, *args, **kwargs) -> dict:
    """
    Wrapper que ejecuta una funcion de analisis y captura errores
    de forma consistente para toda la API.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.exception("Error en analisis avanzado: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error calculando el analisis: {exc}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TICKET PROMEDIO
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/ticket/trend")
def ticket_trend(
    months: int = Query(12, ge=1, le=36,
                        description="Meses de historial a analizar"),
) -> dict:
    """
    Evolucion mensual del ticket promedio.

    Devuelve por mes:
    - venta_total, tickets, ticket_promedio
    - var_ticket_pct: variacion % vs mes anterior
    - estado: SUBE / BAJA / ESTABLE / BASE (primer mes)

    Incluye resumen con:
    - min, max, promedio del periodo
    - cambio_total_pct (primer mes vs ultimo)
    - meses_a_la_baja, meses_al_alza
    """
    from analytics_scripts.ticket_analysis import tendencia_mensual
    return _run(tendencia_mensual, months)


@router.get("/ticket/by-office")
def ticket_by_office(
    days: int = Query(180, ge=7, le=730,
                      description="Dias de historial"),
) -> dict:
    """
    Ticket promedio por sucursal.

    Incluye:
    - vs_global_pct: cuanto se aleja del promedio global
    - alerta: POR DEBAJO / SOBRE MEDIA / NORMAL
    """
    from analytics_scripts.ticket_analysis import analisis_sucursales
    return _run(analisis_sucursales, days)


@router.get("/ticket/depth")
def ticket_depth(
    months: int = Query(12, ge=1, le=36),
) -> dict:
    """
    Profundidad del ticket: items por compra vs precio unitario promedio.

    Distingue entre dos causas de caida del ticket:
    1. El cliente compra MENOS articulos (cross-selling debil)
    2. Se venden articulos MAS BARATOS (mix de precios)

    Incluye diagnostico automatico de causa raiz.
    """
    from analytics_scripts.ticket_analysis import profundidad_ticket
    return _run(profundidad_ticket, months)


@router.get("/ticket/by-category")
def ticket_by_category(
    days: int = Query(180, ge=7, le=730),
) -> dict:
    """
    Ticket promedio de linea por categoria.

    alerta:
    - ARRASTRA: categoria con ticket muy por debajo del promedio global
    - IMPULSA:  categoria que eleva el promedio
    - NORMAL:   dentro del rango esperado

    top_arrastran: las 5 categorias que mas bajan el promedio.
    """
    from analytics_scripts.ticket_analysis import ticket_por_categoria
    return _run(ticket_por_categoria, days)


@router.get("/ticket/diagnosis")
def ticket_diagnosis(
    months: int = Query(12, ge=1, le=36),
) -> dict:
    """
    Diagnostico ejecutivo completo del ticket promedio.

    Consolida: tendencia mensual + por sucursal +
    profundidad + por categoria.

    Incluye lista de recomendaciones priorizadas.
    """
    from analytics_scripts.ticket_analysis import diagnostico_completo
    return _run(diagnostico_completo, months)


# ─────────────────────────────────────────────────────────────────────────────
# TICKET PROMEDIO — ANALISIS AVANZADO DE CAUSA RAIZ
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/ticket/waterfall")
def ticket_waterfall(
    months: int = Query(12, ge=3, le=36,
                        description="Meses de historial a analizar"),
) -> dict:
    """
    Descomposicion cuantitativa del cambio en ticket promedio (Laspeyres).

    Responde: de los X pesos que bajo el ticket, cuanto viene de:
      - efecto_precio_puro  : los mismos productos se venden mas baratos
      - efecto_mix          : mayor participacion de categorias de bajo precio
      - efecto_items        : el cliente compra menos articulos por visita
      - efecto_interaccion  : combinacion de precio e items simultaneamente

    Compara los primeros N meses del periodo contra los ultimos N meses.
    """
    from analytics_scripts.ticket_diagnostico import waterfall_ticket
    return _run(waterfall_ticket, months)


@router.get("/ticket/distribution")
def ticket_distribution(
    months: int = Query(12, ge=3, le=36),
) -> dict:
    """
    Distribucion estadistica de los montos de ticket: inicio vs reciente.

    Percentiles: P10, P25, P50 (mediana), P75, P90, P95.

    Detecta cual segmento se afecto mas:
    - Si bajo P50 (mediana) -> la mayoria de clientes gasta menos
    - Si bajo P90/P95       -> los mejores clientes gastan menos
    - Si bajo P10           -> hay mas micro-transacciones

    Incluye 'interpretacion': parrafo legible con el hallazgo principal.
    """
    from analytics_scripts.ticket_diagnostico import distribucion_ticket
    return _run(distribucion_ticket, months)


@router.get("/ticket/category-mix")
def ticket_category_mix(
    months: int = Query(12, ge=3, le=36),
) -> dict:
    """
    Evolucion mensual del share de revenue por categoria.
    Clasifica cada categoria en:
      - ARRASTRA : gano share pero tiene precio unitario bajo
      - MEJORA   : gano share y tiene precio unitario alto
      - NEUTRAL  : cambio minimo

    Retorna data_mensual (por mes), cambios (inicio vs reciente),
    y las listas categorias_que_arrastran y categorias_que_mejoran.
    """
    from analytics_scripts.ticket_diagnostico import mix_categorias_evolucion
    return _run(mix_categorias_evolucion, months)


@router.get("/ticket/by-weekday")
def ticket_by_weekday(
    months: int = Query(6, ge=1, le=24),
) -> dict:
    """
    Ticket promedio y volumen por dia de la semana.

    Identifica dias 'problema' que arrastran el promedio semanal.
    Incluye alerta: BAJO / ALTO / NORMAL respecto al promedio global.
    Devuelve mejor_dia y peor_dia.
    """
    from analytics_scripts.ticket_diagnostico import ticket_por_dia_semana
    return _run(ticket_por_dia_semana, months)


@router.get("/ticket/anchor-products")
def ticket_anchor_products(
    months: int = Query(12, ge=3, le=36),
    top: int    = Query(20, ge=5, le=100,
                        description="Maximo de productos a retornar"),
) -> dict:
    """
    Productos de alto valor unitario que perdieron participacion de revenue.

    Criterio: precio_unit > mediana del periodo inicial
              Y perdieron mas de 0.5 puntos de share.

    Estos son los 'anclas de ticket': al perder share, bajan el precio
    unitario promedio incluso si sus precios individuales no cambiaron.

    Retorna anclas_perdidas, top_perdieron, top_ganaron.
    """
    from analytics_scripts.ticket_diagnostico import productos_ancla
    return _run(productos_ancla, months, top_n=top)


@router.get("/ticket/advanced-diagnosis")
def ticket_advanced_diagnosis(
    months: int = Query(12, ge=3, le=36),
) -> dict:
    """
    Diagnostico ejecutivo avanzado consolidado.

    Consolida: waterfall + distribucion + mix de categorias +
    dia de semana + productos ancla.

    Devuelve:
      - diagnostico      : parrafo ejecutivo con la causa raiz
      - causa_principal  : etiqueta corta
      - prioridades      : lista de acciones ordenadas por magnitud de impacto
      - modulos completos: waterfall, distribucion, mix, dias_semana, productos_ancla
    """
    from analytics_scripts.ticket_diagnostico import diagnostico_avanzado
    return _run(diagnostico_avanzado, months)


# ─────────────────────────────────────────────────────────────────────────────
# INVENTARIO
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/inventory/abc-xyz")
def inventory_abc_xyz() -> dict:
    """
    Matriz ABC × XYZ completa.

    - ABC: clasificacion por % de ingresos (A=80%, B=15%, C=5%)
    - XYZ: clasificacion por variabilidad de demanda (X estable, Y variable, Z erratica)
    - 9 cuadrantes: AX, AY, AZ, BX, BY, BZ, CX, CY, CZ

    Campos por producto:
    - demand_diaria_efectiva: max(WMA_diaria, rot_30d, rot_90d)
    - tendencia: SUBIENDO / ESTABLE / BAJANDO
    - pct_30d_vs_90d: aceleracion reciente (crecimiento 30d vs 90d en %)
    - cv_semanal: coeficiente de variacion semanal
    - abc_xyz: cuadrante (ej. 'AX', 'CZ')

    Incluye resumen de productos y revenue por cuadrante.
    """
    from analytics_scripts.inventory_analysis import calcular_abc_xyz
    return _run(calcular_abc_xyz)


@router.get("/inventory/alerts")
def inventory_alerts() -> dict:
    """
    Solo los productos BAJO ROP (necesitan reposicion inmediata).
    Ideal para mostrar como badge de alerta en el dashboard.

    Respuesta liviana: solo los campos necesarios para actuar.
    """
    from analytics_scripts.inventory_analysis import calcular_safety_stock_rop
    result = _run(calcular_safety_stock_rop)
    # Para el endpoint de alertas solo devolvemos lo critico
    return {
        "total_bajo_rop":   result.get("total_bajo_rop", 0),
        "alertas":          result.get("alertas", []),
        "parametros":       result.get("parametros", {}),
    }


@router.get("/inventory/rop")
def inventory_rop() -> dict:
    """
    Safety Stock y Reorder Point para todos los productos.

    Formulas:
    - Safety Stock = z × σ_diaria × √LeadTime   (z=1.65, LT=7 dias)
    - ROP = demand_diaria × LT + SS
    - estado_stock: BAJO ROP - REORDENAR / SIN MOVIMIENTO / OK

    Ordenado por urgencia (BAJO ROP primero) y luego por clase ABC.
    """
    from analytics_scripts.inventory_analysis import calcular_safety_stock_rop
    return _run(calcular_safety_stock_rop)


@router.get("/inventory/eoq")
def inventory_eoq() -> dict:
    """
    EOQ (Economic Order Quantity) por producto.

    Formula: EOQ = √(2 × D_anual × S / H)
    donde:
      D = demanda anual estimada
      S = costo fijo por pedido (configurable en analytics_scripts/config.py)
      H = costo unitario × tasa_holding (20% anual por defecto)

    Solo incluye productos con costo conocido.
    """
    from analytics_scripts.inventory_analysis import calcular_eoq
    return _run(calcular_eoq)


@router.get("/inventory/gmroi")
def inventory_gmroi(
    top: int = Query(50, ge=5, le=500,
                     description="Top N productos por GMROI"),
) -> dict:
    """
    GMROI y Rotacion de Inventario (annualized).

    GMROI = Margen Bruto / Costo Inventario Promedio
    - GMROI > 1.0: por cada CLP invertido, se genera mas de 1 CLP de margen
    - GMROI < 0.5: inventario improductivo

    inventory_turnover = COGS_anual / Inventario_a_costo
    - Turnover alto = inventario rota rapido (saludable)

    Incluye resumen global (inventario total, revenue estimado, GMROI global).
    """
    from analytics_scripts.inventory_analysis import calcular_gmroi
    return _run(calcular_gmroi, top_n=top)


# ─────────────────────────────────────────────────────────────────────────────
# INFORME PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/report/pdf",
    response_class=FileResponse,
    summary="Genera y descarga el informe PDF completo",
    tags=["analytics-advanced"],
)
def descargar_informe_pdf(
    months: int = Query(
        12, ge=3, le=24,
        description="Meses de historial para el analisis de ticket (default: 12)",
    ),
) -> FileResponse:
    """
    Genera el informe PDF completo de analisis KAWII y lo retorna como descarga.

    El informe incluye (9 paginas):
      1. Portada con KPIs y diagnostico resumido
      2. Waterfall de causas del cambio en ticket
      3. Distribucion del ticket (percentiles inicio vs reciente)
      4. Mix de categorias que arrastran el promedio
      5. Patron por dia de semana + productos ancla perdidos
      6. Recomendaciones ejecutivas priorizadas
      7. Matriz ABC x XYZ de inventario
      8. Alertas de reposicion (Bajo ROP)
      9. GMROI y Rotacion de Inventario

    **Advertencia:** este endpoint puede tardar 1-2 minutos
    porque recalcula todos los analisis de inventario.
    El frontend debe mostrar un indicador de carga.
    """
    try:
        from analytics_scripts.generate_report import generar_pdf

        # Genera en un archivo temporal
        tmp_path = tempfile.mktemp(
            suffix=".pdf",
            prefix=f"kawii_informe_{datetime.now().strftime('%Y%m%d')}_",
        )
        ruta = generar_pdf(output_path=tmp_path, months=months)

        filename = f"kawii_analisis_{datetime.now().strftime('%Y%m%d')}.pdf"
        return FileResponse(
            path=ruta,
            media_type="application/pdf",
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Generated-At": datetime.utcnow().isoformat(),
            },
        )
    except Exception as exc:
        logger.exception("Error generando PDF: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Error generando el informe PDF: {exc}",
        )
