"""
Modelos Pydantic para Predicciones
"""

from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional
from enum import Enum


class HorizontePrediccion(int, Enum):
    SIETE_DIAS = 7
    CATORCE_DIAS = 14
    VEINTIOCHO_DIAS = 28


class Prediccion(BaseModel):
    """Modelo de Predicción"""
    id: int
    sku: str
    fecha_prediccion: date
    horizonte_dias: HorizontePrediccion
    demanda_proyectada: float = Field(..., ge=0)
    intervalo_confianza_lower: Optional[float] = None
    intervalo_confianza_upper: Optional[float] = None
    confianza: float = Field(..., ge=0, le=1)
    mae: Optional[float] = None
    mape: Optional[float] = None
    sesgo: Optional[float] = None
    modelo_version: str = "1.0.0"
    created_at: datetime

    class Config:
        from_attributes = True


class PrediccionCreate(BaseModel):
    """Modelo para crear predicción"""
    sku: str
    fecha_prediccion: date
    horizonte_dias: HorizontePrediccion
    demanda_proyectada: float = Field(..., ge=0)
    intervalo_confianza_lower: Optional[float] = None
    intervalo_confianza_upper: Optional[float] = None
    confianza: float = Field(..., ge=0, le=1)
    mae: Optional[float] = None
    mape: Optional[float] = None
    sesgo: Optional[float] = None