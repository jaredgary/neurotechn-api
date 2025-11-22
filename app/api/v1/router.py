"""
Router principal de API V1
"""

from fastapi import APIRouter
from app.api.v1 import (
    alertas,
    inventarios,
    predicciones,
    dashboard,
    medicamentos
)

api_router = APIRouter()

# Incluir routers de módulos
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["dashboard"]
)

api_router.include_router(
    alertas.router,
    prefix="/alertas",
    tags=["alertas"]
)

api_router.include_router(
    inventarios.router,
    prefix="/inventarios",
    tags=["inventarios"]
)

api_router.include_router(
    predicciones.router,
    prefix="/predicciones",
    tags=["predicciones"]
)

api_router.include_router(
    medicamentos.router,
    prefix="/medicamentos",
    tags=["medicamentos"]
)