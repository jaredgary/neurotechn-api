"""
Configuración central del sistema MVP Farmacias Siman
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional, List
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Configuración del sistema usando variables de entorno"""
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Permitir campos extra en .env
    )
    
    # Supabase Configuration
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: Optional[str] = None
    
    # API Configuration
    API_VERSION: str = "1.0.0"
    API_TITLE: str = "Farmacias Siman - Sistema Predictivo de Inventario"
    API_DESCRIPTION: str = "API para gestión predictiva de inventario farmacéutico"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = False
    
    # Model Configuration
    MODEL_VERSION: str = "1.0.0"
    MODEL_NAME: str = "xgboost"
    FORECAST_HORIZONS: str = "7,14,28"
    TRAINING_WINDOW_DAYS: int = 90
    MIN_TRAINING_SAMPLES: int = 30
    
    # XGBoost Parameters
    XGBOOST_N_ESTIMATORS: int = 100
    XGBOOST_MAX_DEPTH: int = 6
    XGBOOST_LEARNING_RATE: float = 0.1
    XGBOOST_SUBSAMPLE: float = 0.8
    XGBOOST_COLSAMPLE_BYTREE: float = 0.8
    XGBOOST_RANDOM_STATE: int = 42
    
    # Performance Targets
    TARGET_MAPE: float = 30.0  # Maximum acceptable MAPE
    TARGET_DASHBOARD_UPDATE_MINUTES: int = 15
    TARGET_AVAILABILITY: float = 99.5
    
    # Alert Configuration
    ALERT_CHECK_INTERVAL_HOURS: int = 4
    ALERT_STOCK_CRITICAL_THRESHOLD: float = 0.2  # 20% of safety stock
    ALERT_EXPIRY_DAYS_CRITICAL: int = 7
    ALERT_EXPIRY_DAYS_WARNING: int = 30
    
    # Data Quality Thresholds
    MIN_DATA_COMPLETENESS: float = 0.8  # 80% minimum data completeness
    MAX_OUTLIER_PERCENTAGE: float = 0.05  # 5% maximum outliers
    
    # Caching
    CACHE_TTL_SECONDS: int = 300  # 5 minutes
    CACHE_ENABLED: bool = True
    
    # Monitoring
    SENTRY_DSN: Optional[str] = None
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    ENABLE_METRICS: bool = True
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Database
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30
    
    # Feature Flags
    ENABLE_ADVANCED_FEATURES: bool = False
    ENABLE_DEEP_LEARNING: bool = False
    ENABLE_AUTO_RETRAINING: bool = True
    
    # Business Rules
    ESSENTIAL_MEDICINE_MULTIPLIER: float = 1.5  # Priority multiplier for essential meds
    MAX_LEAD_TIME_DAYS: int = 30
    DEFAULT_SAFETY_STOCK_DAYS: int = 7


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


def get_forecast_horizons() -> List[int]:
    """Parse forecast horizons from comma-separated string"""
    horizons_str = get_settings().FORECAST_HORIZONS
    return [int(h.strip()) for h in horizons_str.split(",")]


def get_xgboost_params() -> dict:
    """Get XGBoost parameters from settings"""
    settings = get_settings()
    return {
        "objective": "reg:squarederror",
        "n_estimators": settings.XGBOOST_N_ESTIMATORS,
        "max_depth": settings.XGBOOST_MAX_DEPTH,
        "learning_rate": settings.XGBOOST_LEARNING_RATE,
        "subsample": settings.XGBOOST_SUBSAMPLE,
        "colsample_bytree": settings.XGBOOST_COLSAMPLE_BYTREE,
        "random_state": settings.XGBOOST_RANDOM_STATE,
        "n_jobs": -1,
        "verbosity": 0
    }


# Configuraciones estáticas (no dependen de settings)
FEATURE_CONFIG = {
    "lag_features": [1, 3, 7, 14, 28],  # Lag days to create
    "rolling_windows": [3, 7, 14, 28],  # Rolling statistics windows
    "calendar_features": [
        "day_of_week",
        "day_of_month", 
        "week_of_year",
        "month",
        "quarter",
        "is_weekend",
        "is_holiday"
    ],
    "statistical_features": [
        "mean",
        "std",
        "min",
        "max",
        "median",
        "skew",
        "kurt"
    ]
}

# Alert priority scoring weights
ALERT_PRIORITY_WEIGHTS = {
    "severity": {  # Debe coincidir con tu enum severidad_alerta
        "ALTA": 30,
        "MEDIA": 20,
        "BAJA": 10
    },
    "type": {      # Debe coincidir con tu enum tipo_alerta
        "QUIEBRE_STOCK": 20,
        "VENCIMIENTO": 15
    },
    "essential_medicine": 20,
    "time_pending": {
        "over_24h": 10,
        "over_12h": 5,
        "under_12h": 0
    }
}

# Dashboard update intervals (seconds)
DASHBOARD_REFRESH_INTERVALS = {
    "executive": 300,      # 5 minutes
    "inventory": 180,      # 3 minutes
    "alerts": 60,          # 1 minute
    "forecast": 900,       # 15 minutes
    "expiry": 600         # 10 minutes
}

# Data quality rules
DATA_QUALITY_RULES = {
    "sales": {
        "min_value": 0,
        "max_value": 10000,
        "required_fields": ["fecha", "sku", "unidades_vendidas"],
        "date_range": "90_days"
    },
    "inventory": {
        "min_value": 0,
        "max_value": 100000,
        "required_fields": ["fecha", "sku", "unidades_stock", "stock_seguridad"],
        "consistency_check": True
    },
    "forecast": {
        "min_value": 0,
        "max_value": 50000,
        "confidence_interval": 0.95,
        "max_horizon_days": 28
    }
}

# API Rate Limiting
RATE_LIMIT_CONFIG = {
    "default": "100/minute",
    "forecast": "10/hour",
    "bulk_operations": "5/hour",
    "reports": "20/hour"
}

# Función helper para logging config (evita llamadas circulares)
def get_logging_config() -> dict:
    """Get logging configuration"""
    settings = get_settings()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
            "json": {
                "format": '{"time": "%(asctime)s", "name": "%(name)s", "level": "%(levelname)s", "message": "%(message)s"}'
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json" if settings.LOG_FORMAT == "json" else "default",
                "level": settings.LOG_LEVEL
            }
        },
        "root": {
            "level": settings.LOG_LEVEL,
            "handlers": ["console"]
        }
    }

# Alias para compatibilidad (usar get_xgboost_params() en su lugar)
XGBOOST_PARAMS = {
    "objective": "reg:squarederror",
    "n_estimators": 100,
    "max_depth": 6,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "verbosity": 0
}