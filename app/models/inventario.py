"""
Modelos Pydantic para Inventarios
"""

from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional


class Inventario(BaseModel):
    """Modelo de Inventario"""
    id: int
    sku: str
    stock_actual: int = Field(..., ge=0)
    fecha_ultima_actualizacion: datetime
    stock_proyectado_7d: Optional[int] = None
    stock_proyectado_14d: Optional[int] = None
    stock_proyectado_28d: Optional[int] = None
    fecha_vencimiento: Optional[date] = None
    lote: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventarioUpdate(BaseModel):
    """Modelo para actualizar inventario"""
    stock_actual: Optional[int] = Field(None, ge=0)
    fecha_vencimiento: Optional[date] = None
    lote: Optional[str] = None


class InventarioResponse(BaseModel):
    """Respuesta con inventario + info del medicamento"""
    inventario: Inventario
    medicamento: dict
    alertas_activas: int = 0