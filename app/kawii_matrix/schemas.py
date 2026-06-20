"""Pydantic schemas para respuestas de KAWII Matrix API.

Solo sobreviven los schemas que sirven al módulo 04b (única matriz viva tras
el cleanup en cascada).
"""

from typing import Any
from pydantic import BaseModel


class ActionGroupsSummary(BaseModel):
    urgente_comprar: int
    reponer: int
    saludable: int
    exceso: int
    liquidar: int
    descatalogar: int
    evaluar: int
    otro: int


class ActionGroupsResponse(BaseModel):
    module: str
    label_column: str
    summary: ActionGroupsSummary
    groups: dict[str, list[dict[str, Any]]]
