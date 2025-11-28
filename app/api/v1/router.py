"""
Router Principal de API V1
Sistema de Alertas Predictivas - Farmacias Siman

Total de endpoints: 45
- Dashboard: 6
- Alertas: 7
- Inventarios: 7
- Medicamentos: 7
- Predicciones: 5
- Ventas: 5 (NUEVO)
- Backtest: 4 (NUEVO)
- Evaluación Alertas: 6 (NUEVO)
- Sistema: 3 (NUEVO)
"""

from fastapi import APIRouter

# Importar routers de módulos
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

api_router = APIRouter()


# =====================================================================
# DASHBOARD (RF-003: Tablero consolidado)
# =====================================================================
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["Dashboard"]
)


# =====================================================================
# ALERTAS (RF-001, RF-002, RF-005)
# =====================================================================
api_router.include_router(
    alertas.router,
    prefix="/alertas",
    tags=["Alertas"]
)


# =====================================================================
# INVENTARIOS (RF-003)
# =====================================================================
api_router.include_router(
    inventarios.router,
    prefix="/inventarios",
    tags=["Inventarios"]
)


# =====================================================================
# MEDICAMENTOS (Catálogo - 120 SKUs)
# =====================================================================
api_router.include_router(
    medicamentos.router,
    prefix="/medicamentos",
    tags=["Medicamentos"]
)


# =====================================================================
# PREDICCIONES (RF-001, RF-004)
# =====================================================================
api_router.include_router(
    predicciones.router,
    prefix="/predicciones",
    tags=["Predicciones ML"]
)


# =====================================================================
# VENTAS DIARIAS (10,800 registros - NUEVO)
# =====================================================================
api_router.include_router(
    ventas.router,
    prefix="/ventas",
    tags=["Ventas Diarias"]
)


# =====================================================================
# BACKTESTING (OE2 - 360 registros - NUEVO)
# =====================================================================
api_router.include_router(
    backtest.router,
    prefix="/backtest",
    tags=["Backtesting ML"]
)


# =====================================================================
# EVALUACIÓN DE ALERTAS (OE4 - 240 registros - NUEVO)
# =====================================================================
api_router.include_router(
    evaluacion_alertas.router,
    prefix="/evaluacion-alertas",
    tags=["Evaluación Alertas"]
)


# =====================================================================
# SISTEMA (Calidad datos, Viabilidad, Métricas Tesis - NUEVO)
# =====================================================================
api_router.include_router(
    sistema.router,
    prefix="/sistema",
    tags=["Sistema"]
)
