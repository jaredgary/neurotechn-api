"""
Configuración de la aplicación
Variables de entorno y constantes
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Configuración de la aplicación desde variables de entorno"""
    
    # Información de la aplicación
    APP_NAME: str = "Farmacias Siman - Sistema Predictivo"
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str  # anon/public key para cliente
    SUPABASE_SERVICE_KEY: str  # service_role key para operaciones admin
    
    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://farmacias-siman-frontend.fly.dev"  # Ajustar según dominio real
    ]
    
    # Configuración del servidor
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    # Constantes del proyecto
    TOTAL_SKUS: int = 120
    HORIZONTE_OPTIMO: int = 14  # días
    FECHA_INICIO_DATOS: str = "2025-08-02"
    FECHA_FIN_DATOS: str = "2025-10-30"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    Obtiene configuración singleton (cacheada)
    
    Returns:
        Settings: Instancia de configuración
    """
    return Settings()


# Instancia global de configuración
settings = get_settings()