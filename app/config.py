"""
Configuración del Backend - Sistema Predictivo de Inventario Farmacéutico
Versión: 2.0 - SaaS Genérico con Cálculo Dinámico

PRINCIPIO FUNDAMENTAL:
"CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"

Solo se hardcodean umbrales de negocio configurables.
Las métricas ML (MAE, MAPE), alertas accionables, etc. se calculan dinámicamente.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    """
    Configuración centralizada del sistema SaaS.

    ✅ SÍ HARDCODEAR: Umbrales de negocio (configurables por empresa)
    ❌ NUNCA HARDCODEAR: Métricas calculadas (MAE, MAPE, total SKUs, etc.)
    """

    # ==========================================================
    # INFORMACIÓN DE LA APLICACIÓN
    # ==========================================================
    APP_NAME: str = "Sistema Predictivo de Inventario Farmacéutico"
    APP_VERSION: str = "2.0.0"
    APP_DESCRIPTION: str = "API SaaS genérica para gestión predictiva de inventarios farmacéuticos"
    API_V1_PREFIX: str = "/api/v1"

    # ==========================================================
    # SUPABASE (Conexión a base de datos)
    # ==========================================================
    SUPABASE_URL: str
    SUPABASE_KEY: str              # anon/public key para cliente
    SUPABASE_SERVICE_KEY: str      # service_role key para operaciones admin

    # ==========================================================
    # CORS (Orígenes permitidos para peticiones cross-origin)
    # ==========================================================
    CORS_ORIGINS: List[str] = [
        # Desarrollo local
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        # Producción
        "https://farmacias-siman-frontend.fly.dev",
        "https://farmacias-siman-api.fly.dev",
        "https://farmacias-siman.fly.dev"
    ]

    # ==========================================================
    # SERVIDOR
    # ==========================================================
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ==========================================================
    # UMBRALES DE NEGOCIO (Configurables - SÍ hardcodear)
    # ==========================================================

    # Configuración de Alertas
    LEAD_TIME_BUFFER_DAYS: int = 2  # Días adicionales al lead time para anticipación
    SAFETY_STOCK_THRESHOLD: float = 1.0  # Multiplicador de stock de seguridad
    MIN_CONFIDENCE_THRESHOLD: float = 0.70  # Confianza mínima para que alerta sea accionable

    # Clasificación de riesgo (umbrales en días)
    RISK_CRITICAL_DAYS: int = 7   # <7 días hasta stockout = CRITICAL
    RISK_HIGH_DAYS: int = 10      # <10 días = HIGH, ≥10 días = MEDIUM

    # Horizontes de predicción soportados
    PREDICTION_HORIZONS: List[int] = [7, 14, 28]  # días
    ALERT_HORIZONS: List[int] = [7, 14]  # horizontes para evaluación de alertas

    # Walk-forward validation para ML
    INITIAL_TRAIN_DAYS: int = 60  # días iniciales de entrenamiento
    STEP_SIZE_DAYS: int = 7  # paso de avance en walk-forward

    # SLOs (Service Level Objectives - Objetivos, NO métricas)
    SLO_DISPONIBILIDAD_PCT: float = 99.0  # % de disponibilidad mensual objetivo
    SLO_LATENCIA_TABLERO_MS: int = 5000  # <5 segundos para dashboard
    SLO_LATENCIA_ALERTAS_MS: int = 3000  # <3 segundos para alertas
    ERROR_BUDGET_HORAS: float = 7.2  # horas de downtime permitidas/mes

    # Configuración de modelos ML
    XGBOOST_N_ESTIMATORS: int = 50
    XGBOOST_MAX_DEPTH: int = 4
    XGBOOST_LEARNING_RATE: float = 0.1
    XGBOOST_RANDOM_STATE: int = 42

    # Ventanas para features de series temporales
    LAG_FEATURES: List[int] = [1, 7, 14]  # lags en días
    MOVING_AVG_WINDOWS: List[int] = [7, 14]  # ventanas de MA en días

    # ==========================================================
    # NOTA IMPORTANTE
    # ==========================================================
    # Las siguientes métricas NO están aquí porque se calculan dinámicamente:
    # - TOTAL_SKUS: Se cuenta de catalogo_medicamentos
    # - XGBOOST_MAE_PROMEDIO: Se calcula de backtest_results
    # - ALERTAS_ACCIONABLES_PCT: Se calcula de alert_evaluation_results
    # - VIABILIDAD_GLOBAL: Se calcula de múltiples fuentes
    #
    # Todas las métricas se obtienen mediante endpoints dedicados que
    # consultan y agregan datos de las tablas correspondientes.
    # ==========================================================

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Singleton para configuración (cacheada)"""
    return Settings()


# Instancia global
settings = get_settings()
