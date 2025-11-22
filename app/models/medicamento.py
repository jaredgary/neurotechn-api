"""
Modelos Pydantic para Medicamentos
"""

from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional
from enum import Enum


class CategoriaABC(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Medicamento(BaseModel):
    """Modelo de Medicamento (Catálogo)"""
    sku: str
    nombre_comercial: str
    nombre_generico: Optional[str] = None
    codigo_atc: Optional[str] = None
    grupo_terapeutico: Optional[str] = None
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    demanda_base: Optional[float] = None
    variabilidad: Optional[float] = None
    categoria_abc: Optional[CategoriaABC] = None
    prob_quiebre: Optional[float] = Field(None, ge=0, le=1)
    lead_time_dias: int = Field(..., ge=3, le=7)
    stock_seguridad: int = Field(..., ge=0)
    lote_minimo: int = Field(..., gt=0)
    es_esencial: bool = False
    requiere_receta: bool = False
    proveedor: Optional[str] = None
    precio_unitario_lps: Optional[float] = Field(None, gt=0)
    fecha_creacion: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MedicamentoResponse(BaseModel):
    """Respuesta completa con métricas"""
    medicamento: Medicamento
    inventario_actual: Optional[dict] = None
    ultima_prediccion: Optional[dict] = None
    alertas_activas: int = 0