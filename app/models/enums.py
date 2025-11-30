"""
Enums centralizados para el sistema
Versión 2.0 - SaaS Genérico
"""

from enum import Enum


class RiskLevel(str, Enum):
    """
    Niveles de riesgo para alertas.

    IMPORTANTE: Solo hay 3 niveles (NO LOW).
    - CRITICAL: <7 días hasta stockout (configurable)
    - HIGH: <10 días hasta stockout (configurable)
    - MEDIUM: ≥10 días hasta stockout
    """
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class AlertStatus(str, Enum):
    """Estado de una alerta"""
    PENDIENTE = "pendiente"
    ATENDIDA = "atendida"
    DESCARTADA = "descartada"


class PriorityLevel(str, Enum):
    """Nivel de prioridad textual"""
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAJA = "BAJA"


class CategoriaABC(str, Enum):
    """Clasificación ABC de inventarios"""
    A = "A"  # Alto valor
    B = "B"  # Medio valor
    C = "C"  # Bajo valor
