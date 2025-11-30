"""
Sistema Predictivo de Inventario Farmacéutico - Backend FastAPI
Versión: 2.1.0 - SaaS Genérico con Cálculo Dinámico

PRINCIPIO FUNDAMENTAL:
"CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"

Características:
- SKUs variables según datos del cliente
- Registros de ventas variables según período cargado
- Métricas ML calculadas dinámicamente de backtest_results
- % alertas accionables calculado de alert_evaluation_results
- Viabilidad calculada de múltiples fuentes

El sistema escala automáticamente según los datos cargados.
"""

__version__ = "2.1.0"
__author__ = "Gary González Zepeda"
__email__ = "gary.gonzalez@unitec.edu"
__project__ = "Tesis GTI - UNITEC Honduras"
