"""
Modelos Pydantic para Alertas
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class NivelRiesgo(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class EstadoAlerta(str, Enum):
    PENDIENTE = "pendiente"
    ATENDIDA = "atendida"
    DESCARTADA = "descartada"


class Alerta(BaseModel):
    """Modelo de Alerta"""
    id: int
    sku: str
    fecha_generacion: datetime
    nivel_riesgo: NivelRiesgo
    dias_hasta_stockout: int
    score_urgencia: float = Field(..., ge=0, le=1)
    cantidad_recomendada: int
    fecha_limite_pedido: Optional[datetime] = None
    factores_explicativos: Optional[dict] = None
    estado: EstadoAlerta = EstadoAlerta.PENDIENTE
    accion_tomada: Optional[str] = None
    atendida_por: Optional[str] = None
    fecha_atencion: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlertaCreate(BaseModel):
    """Modelo para crear alerta"""
    sku: str
    nivel_riesgo: NivelRiesgo
    dias_hasta_stockout: int
    score_urgencia: float = Field(..., ge=0, le=1)
    cantidad_recomendada: int
    fecha_limite_pedido: Optional[datetime] = None
    factores_explicativos: Optional[dict] = None


class AlertaUpdate(BaseModel):
    """Modelo para actualizar alerta"""
    estado: Optional[EstadoAlerta] = None
    accion_tomada: Optional[str] = None
    atendida_por: Optional[str] = None


class AlertaResponse(BaseModel):
    """Respuesta con alerta + info del medicamento"""
    alerta: Alerta
    medicamento: dict
    inventario_actual: Optional[dict] = None