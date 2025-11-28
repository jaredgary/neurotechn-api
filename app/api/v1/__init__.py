"""
API V1 - Módulos disponibles
Sistema de Alertas Predictivas - Farmacias Siman
"""

from app.api.v1 import (
    dashboard,
    alertas,
    inventarios,
    medicamentos,
    predicciones,
    ventas,
    backtest,
    evaluacion_alertas,
    sistema
)

__all__ = [
    "dashboard",
    "alertas",
    "inventarios",
    "medicamentos",
    "predicciones",
    "ventas",
    "backtest",
    "evaluacion_alertas",
    "sistema"
]
