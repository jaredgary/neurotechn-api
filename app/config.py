"""
Configuración del Backend - Farmacias Siman
Versión: 1.1.0 - Con métricas verificadas de tesis

MÉTRICAS VERIFICADAS CONTRA ARCHIVOS FUENTE:
- benchmarking_results_20251023_073621.csv
- alert_evaluation_results.csv
- utility_report.txt
- MARCO_DE_EVALUACIÓN_DE_VIABILIDAD.pdf
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    """Configuración centralizada con métricas de tesis verificadas"""
    
    # ==========================================================
    # INFORMACIÓN DE LA APLICACIÓN
    # ==========================================================
    APP_NAME: str = "Farmacias Siman - Sistema Predictivo"
    APP_VERSION: str = "1.1.0"
    APP_DESCRIPTION: str = "API para sistema de alertas predictivas de inventario farmacéutico"
    API_V1_PREFIX: str = "/api/v1"
    
    # ==========================================================
    # SUPABASE
    # ==========================================================
    SUPABASE_URL: str
    SUPABASE_KEY: str              # anon/public key para cliente
    SUPABASE_SERVICE_KEY: str      # service_role key para operaciones admin
    
    # ==========================================================
    # CORS
    # ==========================================================
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
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
    # ALCANCE DEL PROYECTO (OE1 - VERIFICADO)
    # Fuente: datos_farmacias_siman.csv, catalogo_medicamentos.csv
    # ==========================================================
    TOTAL_SKUS: int = 120                    # MED001-MED120
    TOTAL_REGISTROS_VENTAS: int = 10800      # 120 SKUs × 90 días
    PERIODO_INICIO: str = "2025-08-02"
    PERIODO_FIN: str = "2025-10-30"
    TOTAL_DIAS: int = 90
    GRUPOS_TERAPEUTICOS: int = 25            # Códigos ATC
    MEDICAMENTOS_ESENCIALES: int = 105       # 87.5% del catálogo
    DEMANDAS_CERO: int = 430                 # 3.98% de registros
    
    # Distribución ABC (verificada contra catalogo_medicamentos.csv)
    CATEGORIA_A: int = 17                    # Alto valor
    CATEGORIA_B: int = 61                    # Medio valor
    CATEGORIA_C: int = 42                    # Bajo valor
    
    # ==========================================================
    # MÉTRICAS ML - XGBoost (OE2 - VERIFICADO)
    # Fuente: benchmarking_results_20251023_073621.csv
    # ==========================================================
    
    # Promedios de 3 horizontes (7d, 14d, 28d)
    XGBOOST_MAE_PROMEDIO: float = 379.69     # unidades (NO redondear a 380)
    XGBOOST_MAPE_PROMEDIO: float = 3.85      # porcentaje
    XGBOOST_SESGO_PROMEDIO: float = -191.20  # unidades
    XGBOOST_TIEMPO_ENTRENAMIENTO: float = 0.08  # segundos (0.076 redondeado)
    
    # Por horizonte específico
    XGBOOST_MAE_7D: float = 428.37
    XGBOOST_MAE_14D: float = 394.28
    XGBOOST_MAE_28D: float = 316.41
    
    XGBOOST_MAPE_7D: float = 4.40
    XGBOOST_MAPE_14D: float = 4.01
    XGBOOST_MAPE_28D: float = 3.14
    
    # Horizonte óptimo
    HORIZONTE_OPTIMO: int = 14               # días (mejor balance precisión-anticipación)
    
    # Scoring del algoritmo (OE2)
    XGBOOST_SCORING: int = 97                # puntos de 100 (1º lugar)
    
    # Backtesting
    TOTAL_BACKTEST_RECORDS: int = 360        # 120 SKUs × 3 horizontes
    
    # ==========================================================
    # MÉTRICAS DE ALERTAS (OE4 - VERIFICADO)
    # Fuente: alert_evaluation_results.csv, utility_report.txt
    # ==========================================================
    TOTAL_ALERTAS_EVALUADAS: int = 240       # 120 SKUs × 2 horizontes (7d, 14d)
    ALERTAS_ACCIONABLES: int = 172           # 71.7%
    ALERTAS_ACCIONABLES_PCT: float = 71.7
    
    # Cumplimiento de criterios
    CUMPLE_LEAD_TIME: int = 214              # 89.2%
    BAJO_UMBRAL_SEGURIDAD: int = 187         # 77.9%
    CUMPLE_CONFIANZA_MINIMA: int = 240       # 100%
    CUMPLE_PEDIDO_MINIMO: int = 240          # 100%
    
    # Por horizonte de predicción
    ACCIONABLES_7D: int = 52                 # 43.3%
    ACCIONABLES_14D: int = 120               # 100%
    
    # Distribución por nivel de riesgo
    RIESGO_MEDIUM: int = 131                 # 54.6%
    RIESGO_HIGH: int = 109                   # 45.4%
    RIESGO_CRITICAL: int = 0                 # 0%
    
    # Métricas operacionales (utility_report.txt)
    DIAS_PROMEDIO_STOCKOUT: float = 8.6
    SCORE_URGENCIA_PROMEDIO: float = 0.74
    CANTIDAD_PROMEDIO_RECOMENDADA: float = 96.1   # unidades
    TOTAL_RECOMENDADO_ORDENAR: int = 23072        # unidades (NO 23,073)
    
    # ==========================================================
    # SLOs (OE3 - RNF-002, RNF-003)
    # Fuente: CHECKLIST_WELLARCHITECTED_GCP.pdf, Tabla 43 tesis
    # ==========================================================
    SLO_DISPONIBILIDAD_PCT: float = 99.0     # mensual
    SLO_LATENCIA_TABLERO_MS: int = 5000      # <5s (RNF-002)
    SLO_LATENCIA_ALERTAS_MS: int = 3000      # <3s
    ERROR_BUDGET_HORAS: float = 7.2          # horas/mes
    
    # Well-Architected (CORREGIDO)
    WELL_ARCHITECTED_TOTAL: int = 30         # ítems
    WELL_ARCHITECTED_CUMPLIDOS: int = 21     # 70% (NO 24/80%)
    
    # ==========================================================
    # VIABILIDAD GLOBAL (OE4 - VERIFICADO)
    # Fuente: MARCO_DE_EVALUACIÓN_DE_VIABILIDAD.pdf
    # ==========================================================
    VIABILIDAD_GLOBAL: int = 89              # puntos de 100
    VIABILIDAD_TECNICA_PCT: int = 94
    VIABILIDAD_OPERATIVA_PCT: int = 87
    VIABILIDAD_ECONOMICA_PCT: int = 86
    
    # Clasificación
    CLASIFICACION_VIABILIDAD: str = "ALTAMENTE VIABLE"  # 85-100 pts
    
    # ==========================================================
    # ENCUESTA (OE1 - n=3 participantes)
    # Fuente: Encuesta.xlsx
    # ==========================================================
    PARTICIPANTES_ENCUESTA: int = 3
    DISPONIBILIDAD_DATOS_PROMEDIO: float = 83.3  # G1: [80,80,90]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Singleton para configuración (cacheada)"""
    return Settings()


# Instancia global
settings = get_settings()
