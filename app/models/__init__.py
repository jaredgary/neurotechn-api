"""
Modelos Pydantic - Farmacias Siman
Sistema de Alertas Predictivas

Todos los modelos con validaciones y documentación
"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum


# =====================================================================
# ENUMS
# =====================================================================

class CategoriaABC(str, Enum):
    """Categoría ABC de medicamentos (Pareto)"""
    A = "A"  # Alto valor (17 SKUs)
    B = "B"  # Medio valor (61 SKUs)
    C = "C"  # Bajo valor (42 SKUs)


class NivelRiesgo(str, Enum):
    """Nivel de riesgo de alerta"""
    CRITICAL = "CRITICAL"  # 0 alertas en OE4
    HIGH = "HIGH"          # 109 alertas (45.4%)
    MEDIUM = "MEDIUM"      # 131 alertas (54.6%)


class EstadoAlerta(str, Enum):
    """Estado de una alerta"""
    PENDIENTE = "pendiente"
    ATENDIDA = "atendida"
    DESCARTADA = "descartada"


class RolUsuario(str, Enum):
    """Roles de usuario del sistema"""
    ADMIN = "admin"
    FARMACIA = "farmacia"
    READONLY = "readonly"


class HorizontePrediccion(int, Enum):
    """Horizontes de predicción válidos"""
    CORTO = 7
    OPTIMO = 14  # Horizonte óptimo según OE2
    LARGO = 28


# =====================================================================
# MODELOS BASE
# =====================================================================

class BaseResponse(BaseModel):
    """Respuesta base de la API"""
    success: bool = True
    message: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Respuesta paginada"""
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    """Respuesta de error"""
    success: bool = False
    error: Dict[str, Any]


# =====================================================================
# MEDICAMENTO (120 SKUs - MED001 a MED120)
# =====================================================================

class MedicamentoBase(BaseModel):
    """Datos básicos de medicamento"""
    sku: str = Field(..., description="SKU único (MED001-MED120)")
    nombre_comercial: str = Field(..., max_length=200)
    nombre_generico: str = Field(..., max_length=200)
    
    model_config = ConfigDict(from_attributes=True)


class MedicamentoCompleto(MedicamentoBase):
    """Medicamento con todos los campos del catálogo"""
    codigo_atc: Optional[str] = Field(None, description="Código ATC")
    grupo_terapeutico: str = Field(..., description="Uno de 25 grupos")
    presentacion: str
    concentracion: str
    demanda_base: float = Field(..., ge=0)
    variabilidad: float = Field(..., ge=0, le=1)
    categoria_abc: CategoriaABC
    prob_quiebre: float = Field(..., ge=0, le=1)
    lead_time_dias: int = Field(..., ge=1, le=30, description="3-7 días típico")
    stock_seguridad: int = Field(..., ge=0)
    lote_minimo: int = Field(..., ge=1)
    es_esencial: bool = Field(default=True, description="105 de 120 son esenciales")
    requiere_receta: bool = Field(default=False)
    proveedor: str
    precio_unitario_lps: float = Field(..., ge=0)
    fecha_creacion: Optional[datetime] = None


class MedicamentoConInventario(MedicamentoCompleto):
    """Medicamento con información de inventario actual"""
    inventario: Optional[Dict[str, Any]] = None
    ultima_prediccion: Optional[Dict[str, Any]] = None
    alertas_activas: Optional[List[Dict[str, Any]]] = None


# =====================================================================
# VENTA DIARIA (10,800 registros)
# =====================================================================

class VentaDiaria(BaseModel):
    """Registro de venta diaria"""
    id: Optional[int] = None
    fecha: date = Field(..., description="2025-08-02 a 2025-10-30")
    sku: str
    demanda: int = Field(..., ge=0, description="430 registros con demanda=0")
    
    model_config = ConfigDict(from_attributes=True)


class VentaDiariaEstadisticas(BaseModel):
    """Estadísticas de ventas"""
    total_registros: int
    demanda_total: int
    demanda_promedio: float
    demanda_maxima: int
    demanda_minima: int
    dias_sin_demanda: int


# =====================================================================
# INVENTARIO
# =====================================================================

class InventarioBase(BaseModel):
    """Inventario base"""
    sku: str
    stock_actual: int = Field(..., ge=0)
    
    model_config = ConfigDict(from_attributes=True)


class InventarioActual(InventarioBase):
    """Inventario actual con proyecciones"""
    stock_proyectado_7d: Optional[float] = None
    stock_proyectado_14d: Optional[float] = None
    stock_proyectado_28d: Optional[float] = None
    fecha_vencimiento: Optional[date] = None
    lote: Optional[str] = None
    fecha_ultima_actualizacion: Optional[datetime] = None


class InventarioUpdate(BaseModel):
    """Datos para actualizar inventario"""
    stock_actual: Optional[int] = Field(None, ge=0)
    fecha_vencimiento: Optional[date] = None
    lote: Optional[str] = None


class InventarioConMedicamento(InventarioActual):
    """Inventario con información del medicamento"""
    catalogo_medicamentos: Optional[MedicamentoBase] = None


# =====================================================================
# PREDICCIÓN ML
# =====================================================================

class PrediccionBase(BaseModel):
    """Predicción base"""
    sku: str
    horizonte_dias: int = Field(..., description="7, 14 (óptimo), o 28 días")
    demanda_predicha: float = Field(..., ge=0)
    
    model_config = ConfigDict(from_attributes=True)


class PrediccionCompleta(PrediccionBase):
    """Predicción con métricas"""
    id: Optional[int] = None
    fecha_prediccion: datetime
    mae: Optional[float] = Field(None, description="MAE promedio: 379.69")
    mape: Optional[float] = Field(None, description="MAPE promedio: 3.85%")
    sesgo: Optional[float] = None
    confianza: Optional[float] = Field(None, ge=0, le=1)
    factores_principales: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class PrediccionCreate(BaseModel):
    """Datos para crear predicción"""
    sku: str
    horizonte_dias: int = Field(..., ge=7, le=28)
    demanda_predicha: float = Field(..., ge=0)
    fecha_prediccion: date
    mae: Optional[float] = None
    mape: Optional[float] = None
    sesgo: Optional[float] = None
    confianza: Optional[float] = Field(None, ge=0, le=1)


# =====================================================================
# ALERTA
# =====================================================================

class AlertaBase(BaseModel):
    """Alerta base"""
    sku: str
    nivel_riesgo: NivelRiesgo
    dias_hasta_stockout: int = Field(..., ge=0)
    score_urgencia: float = Field(..., ge=0, le=1, description="Promedio: 0.74")
    
    model_config = ConfigDict(from_attributes=True)


class AlertaCompleta(AlertaBase):
    """Alerta con todos los campos"""
    id: int
    fecha_generacion: datetime
    cantidad_recomendada: int = Field(..., ge=0)
    fecha_limite_pedido: Optional[datetime] = None
    factores_explicativos: Optional[Dict[str, Any]] = None
    estado: EstadoAlerta = EstadoAlerta.PENDIENTE
    accion_tomada: Optional[str] = None
    atendida_por: Optional[str] = None
    fecha_atencion: Optional[datetime] = None
    created_at: datetime


class AlertaCreate(BaseModel):
    """Datos para crear alerta"""
    sku: str
    nivel_riesgo: NivelRiesgo
    dias_hasta_stockout: int = Field(..., ge=0)
    score_urgencia: float = Field(..., ge=0, le=1)
    cantidad_recomendada: int = Field(..., ge=0)
    fecha_limite_pedido: Optional[datetime] = None
    factores_explicativos: Optional[Dict[str, Any]] = None


class AlertaUpdate(BaseModel):
    """Datos para actualizar alerta"""
    estado: Optional[EstadoAlerta] = None
    accion_tomada: Optional[str] = Field(None, max_length=500)
    atendida_por: Optional[str] = Field(None, max_length=100)


class AtenderAlertaRequest(BaseModel):
    """Request para atender alerta (RF-005)"""
    accion_tomada: str = Field(..., max_length=500, description="Descripción de la acción")
    atendida_por: str = Field(..., max_length=100, description="Nombre del responsable")


class DescartarAlertaRequest(BaseModel):
    """Request para descartar alerta"""
    motivo: Optional[str] = Field(None, max_length=500)


# =====================================================================
# BACKTEST (360 registros - OE2)
# =====================================================================

class BacktestResult(BaseModel):
    """Resultado de backtesting walk-forward"""
    id: Optional[int] = None
    sku: str
    algorithm: str = "XGBoost"
    horizon: int = Field(..., description="7, 14, o 28 días")
    mae: float = Field(..., ge=0, description="Promedio: 379.69")
    mape: float = Field(..., ge=0, description="Promedio: 3.85%")
    bias: Optional[float] = None
    n_predictions: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# EVALUACIÓN DE ALERTAS (240 registros - OE4)
# =====================================================================

class EvaluacionAlerta(BaseModel):
    """Resultado de evaluación de alerta"""
    sku: str
    category: Optional[str] = None
    alert_date: Optional[date] = None
    prediction_horizon: int = Field(..., description="7 o 14 días")
    is_actionable: bool = Field(..., description="71.7% son accionables")
    risk_level: NivelRiesgo
    days_until_stockout: int = Field(..., description="Promedio: 8.6 días")
    urgency_score: float = Field(..., ge=0, le=1, description="Promedio: 0.74")
    priority_level: Optional[str] = None
    recommended_order_qty: float = Field(..., ge=0, description="Promedio: 96.1 unidades")
    order_by_date: Optional[date] = None
    current_stock: int = Field(..., ge=0)
    predicted_stock: Optional[float] = None
    safety_stock: int = Field(..., ge=0)
    lead_time: int = Field(..., ge=1)
    prediction_confidence: float = Field(..., ge=0, le=1, description="100% cumplen mínimo")
    meets_lead_time: bool = Field(..., description="89.2% cumplen")
    below_safety_threshold: bool = Field(..., description="77.9% bajo umbral")
    meets_confidence: bool = Field(..., description="100% cumplen")
    meets_min_order: bool = Field(..., description="100% cumplen")
    
    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# CALIDAD DE DATOS (FD-001 a FD-004)
# =====================================================================

class CalidadDatosLog(BaseModel):
    """Log de validación de calidad de datos"""
    id: Optional[int] = None
    codigo_fuente: str = Field(..., description="FD-001 a FD-004")
    nombre_fuente: str
    disponibilidad_pct: float = Field(..., ge=0, le=100)
    completitud_pct: float = Field(..., ge=0, le=100)
    registros_validados: int
    registros_errores: int
    fecha_validacion: datetime
    detalles: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# USUARIO
# =====================================================================

class UsuarioBase(BaseModel):
    """Usuario base"""
    email: str
    nombre: str
    rol: RolUsuario = RolUsuario.READONLY
    
    model_config = ConfigDict(from_attributes=True)


class Usuario(UsuarioBase):
    """Usuario completo"""
    id: int
    activo: bool = True
    created_at: datetime
    ultimo_acceso: Optional[datetime] = None


# =====================================================================
# DASHBOARD
# =====================================================================

class DashboardStats(BaseModel):
    """Estadísticas del dashboard"""
    alertas_pendientes: int
    alertas_criticas: int
    alertas_high: int
    skus_en_riesgo: int
    esenciales_en_riesgo: int
    total_medicamentos: int = 120
    fecha_actualizacion: datetime


class ResumenAlertas(BaseModel):
    """Resumen de alertas para dashboard"""
    alertas: List[Dict[str, Any]]
    total: int


class PerformanceML(BaseModel):
    """Métricas de performance del modelo ML"""
    metricas_ml: Dict[str, Any]
    horizonte_optimo: str = "14d"
    utilidad_alertas: Dict[str, Any]
    viabilidad_sistema: int = 89
