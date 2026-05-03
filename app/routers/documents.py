"""Endpoints de documentos (ventas / boletas / facturas / notas).

Por defecto solo lista documentos de las sucursales activas
(OFFICE_IDS en analytics_scripts/config.py). Si el frontend pasa
un office_id explicito (ej. para una vista de auditoria),
se respeta ese filtro especifico.
"""

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from analytics_scripts.config import OFFICE_IDS
from app.database import fetch_all, fetch_one, fetch_scalar

router = APIRouter(prefix="/documents", tags=["documents"])

_OFFICE_IDS_SQL = ", ".join(str(i) for i in OFFICE_IDS)


@router.get("")
def list_documents(
    date_from: date | None = None,
    date_to: date | None = None,
    document_type_id: int | None = None,
    office_id: int | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    where = []
    params: list = []
    if date_from:
        where.append("doc.emission_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("doc.emission_date < %s")
        params.append(date_to)
    if document_type_id:
        where.append("doc.bsale_document_type_id = %s")
        params.append(document_type_id)
    if office_id:
        # filtro explicito (override) — respetar lo que pase el frontend
        where.append("doc.bsale_office_id = %s")
        params.append(office_id)
    else:
        # filtro por defecto — solo sucursales activas
        where.append(f"doc.bsale_office_id IN ({_OFFICE_IDS_SQL})")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    total = fetch_scalar(f"SELECT COUNT(*) FROM documents doc {where_sql}", tuple(params)) or 0

    rows = fetch_all(f"""
        SELECT doc.bsale_document_id, doc.serial_number, doc.doc_number, doc.emission_date,
               doc.total_amount, doc.bsale_office_id, o.name AS office_name,
               dt.name AS document_type_name, doc.is_credit_note
        FROM documents doc
        LEFT JOIN offices o          ON o.bsale_office_id = doc.bsale_office_id
        LEFT JOIN document_types dt  ON dt.bsale_document_type_id = doc.bsale_document_type_id
        {where_sql}
        ORDER BY doc.emission_date DESC
        LIMIT %s OFFSET %s
    """, tuple(params) + (limit, offset))

    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/{doc_id}")
def get_document(doc_id: int) -> dict:
    doc = fetch_one("""
        SELECT doc.*, dt.name AS document_type_name, o.name AS office_name
        FROM documents doc
        LEFT JOIN document_types dt ON dt.bsale_document_type_id = doc.bsale_document_type_id
        LEFT JOIN offices o         ON o.bsale_office_id = doc.bsale_office_id
        WHERE doc.bsale_document_id = %s
    """, (doc_id,))
    if not doc:
        raise HTTPException(404, "Documento no encontrado")

    doc["detalles"] = fetch_all("""
        SELECT dd.bsale_variant_id, v.code, p.name AS producto,
               dd.quantity, dd.net_unit_value, dd.total_amount
        FROM document_details dd
        LEFT JOIN variants v  ON v.bsale_variant_id = dd.bsale_variant_id
        LEFT JOIN products p  ON p.bsale_product_id = v.bsale_product_id
        WHERE dd.bsale_document_id = %s
    """, (doc_id,))
    return doc


@router.get("/stats/summary")
def documents_summary() -> dict:
    return {
        "total_documentos": fetch_scalar("SELECT COUNT(*) FROM documents"),
        "total_detalles":   fetch_scalar("SELECT COUNT(*) FROM document_details"),
        "mas_reciente":     fetch_scalar("SELECT MAX(emission_date) FROM documents"),
        "mas_antiguo":      fetch_scalar("SELECT MIN(emission_date) FROM documents"),
        "por_tipo": fetch_all("""
            SELECT dt.name AS tipo, COUNT(*) AS cantidad
            FROM documents doc
            LEFT JOIN document_types dt ON dt.bsale_document_type_id = doc.bsale_document_type_id
            GROUP BY dt.name
            ORDER BY cantidad DESC
        """),
    }
