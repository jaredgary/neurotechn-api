"""
Aplicación principal FastAPI
Sistema de Alertas Predictivas - Farmacias Siman

Versión: 1.1.0 - Auditoría completada
Autor: Gary González Zepeda
Fecha: 2025-11-27

Métricas verificadas:
- 120 SKUs (MED001-MED120)
- 10,800 registros de ventas
- XGBoost MAE: 379.69, MAPE: 3.85%
- 71.7% alertas accionables
- Viabilidad: 89/100 (ALTAMENTE VIABLE)
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging
import time
from datetime import datetime

from app.config import settings
from app.api.v1.router import api_router
from app.database import supabase_client

# Configurar logging estructurado
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle de la aplicación
    Se ejecuta al iniciar y al cerrar
    """
    # Startup
    logger.info("=" * 60)
    logger.info("🚀 Iniciando Sistema Predictivo - Farmacias Siman")
    logger.info("=" * 60)
    logger.info(f"   Versión: {settings.APP_VERSION}")
    logger.info(f"   Entorno: {'DEBUG' if settings.DEBUG else 'PRODUCTION'}")
    logger.info(f"   Supabase: {settings.SUPABASE_URL[:50]}...")
    logger.info("-" * 60)
    logger.info("📊 Métricas del Proyecto (Verificadas):")
    logger.info(f"   Total SKUs: {settings.TOTAL_SKUS}")
    logger.info(f"   Registros ventas: {settings.TOTAL_REGISTROS_VENTAS}")
    logger.info(f"   XGBoost MAE: {settings.XGBOOST_MAE_PROMEDIO}")
    logger.info(f"   XGBoost MAPE: {settings.XGBOOST_MAPE_PROMEDIO}%")
    logger.info(f"   Horizonte óptimo: {settings.HORIZONTE_OPTIMO} días")
    logger.info(f"   Alertas accionables: {settings.ALERTAS_ACCIONABLES_PCT}%")
    logger.info(f"   Viabilidad global: {settings.VIABILIDAD_GLOBAL}/100")
    logger.info("-" * 60)
    
    # Verificar conexión a Supabase
    try:
        result = supabase_client.table('catalogo_medicamentos').select('count', count='exact').limit(1).execute()
        logger.info(f"   ✅ Conexión a Supabase exitosa ({result.count} medicamentos)")
    except Exception as e:
        logger.error(f"   ❌ Error conectando a Supabase: {str(e)}")
    
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("👋 Cerrando aplicación...")


# Crear aplicación FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    description="""
## Sistema de Alertas Predictivas para Inventario Farmacéutico

API REST para el sistema de información con capacidades predictivas de Farmacias Siman.

### Características principales:
- **Dashboard**: Estadísticas en tiempo real y resumen ejecutivo
- **Alertas**: Gestión de alertas de agotamiento con priorización
- **Inventarios**: Control de stock actual y proyectado
- **Predicciones**: Pronósticos de demanda con XGBoost
- **Medicamentos**: Catálogo de 120 SKUs
- **Ventas**: Histórico de 10,800 registros (90 días)
- **Backtesting**: Validación de modelo ML (360 registros)
- **Evaluación**: Métricas de utilidad de alertas (240 registros)

### Métricas del Proyecto (OE2/OE4):
- **MAE promedio**: 379.69 unidades
- **MAPE promedio**: 3.85%
- **Alertas accionables**: 71.7%
- **Viabilidad**: 89/100 (ALTAMENTE VIABLE)

### Autor
Gary González Zepeda - Maestría GTI, UNITEC Honduras
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Dashboard", "description": "Estadísticas y resumen ejecutivo (RF-003)"},
        {"name": "Alertas", "description": "Gestión de alertas predictivas (RF-001, RF-002, RF-005)"},
        {"name": "Inventarios", "description": "Control de inventarios (RF-003)"},
        {"name": "Medicamentos", "description": "Catálogo de 120 SKUs"},
        {"name": "Predicciones ML", "description": "Pronósticos con XGBoost (RF-001, RF-004)"},
        {"name": "Ventas Diarias", "description": "Histórico de ventas (10,800 registros)"},
        {"name": "Backtesting ML", "description": "Validación walk-forward (OE2)"},
        {"name": "Evaluación Alertas", "description": "Métricas de utilidad (OE4)"},
        {"name": "Sistema", "description": "Calidad de datos y viabilidad"}
    ]
)


# =====================================================================
# MIDDLEWARE
# =====================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compresión GZIP
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Middleware de logging y timing
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware para logging de todas las requests
    Incluye tiempo de respuesta para monitoreo de SLOs
    """
    start_time = time.time()
    
    # Log request
    logger.info(f"→ {request.method} {request.url.path}")
    
    # Procesar request
    response = await call_next(request)
    
    # Calcular tiempo de procesamiento
    process_time = time.time() - start_time
    process_time_ms = process_time * 1000
    
    # Log response con tiempo
    log_level = logging.WARNING if process_time_ms > settings.SLO_LATENCIA_TABLERO_MS else logging.INFO
    logger.log(
        log_level,
        f"← {request.method} {request.url.path} "
        f"status={response.status_code} "
        f"time={process_time_ms:.0f}ms"
    )
    
    # Agregar headers de timing
    response.headers["X-Process-Time"] = f"{process_time_ms:.0f}ms"
    response.headers["X-API-Version"] = settings.APP_VERSION
    
    return response


# =====================================================================
# EXCEPTION HANDLERS
# =====================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Maneja errores de validación de Pydantic"""
    logger.error(f"Error de validación: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Error en los datos enviados",
                "details": exc.errors()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Maneja excepciones no capturadas"""
    logger.error(f"Error no manejado: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Error interno del servidor",
                "details": str(exc) if settings.DEBUG else None
            }
        }
    )


# =====================================================================
# ROUTES BASE
# =====================================================================

@app.get("/", tags=["root"])
async def root():
    """
    Endpoint raíz con información del sistema
    """
    return {
        "success": True,
        "data": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "redoc": "/redoc",
            "metricas_proyecto": {
                "total_skus": settings.TOTAL_SKUS,
                "xgboost_mae": settings.XGBOOST_MAE_PROMEDIO,
                "xgboost_mape": f"{settings.XGBOOST_MAPE_PROMEDIO}%",
                "alertas_accionables": f"{settings.ALERTAS_ACCIONABLES_PCT}%",
                "viabilidad": f"{settings.VIABILIDAD_GLOBAL}/100"
            },
            "timestamp": datetime.now().isoformat()
        }
    }


@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check para monitoreo (RNF-003: ≥99% disponibilidad)
    """
    checks = {
        "api": "healthy",
        "database": "unknown"
    }
    
    try:
        # Verificar conexión a Supabase
        result = supabase_client.table('catalogo_medicamentos').select('count', count='exact').limit(1).execute()
        checks["database"] = "healthy"
        checks["medicamentos_count"] = result.count
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        checks["database"] = "unhealthy"
        checks["error"] = str(e)
        
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "data": {
                    "status": "unhealthy",
                    "checks": checks,
                    "timestamp": datetime.now().isoformat()
                }
            }
        )
    
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "checks": checks,
            "version": settings.APP_VERSION,
            "slo_disponibilidad": f"≥{settings.SLO_DISPONIBILIDAD_PCT}%",
            "timestamp": datetime.now().isoformat()
        }
    }


# Incluir routers de API v1
app.include_router(
    api_router,
    prefix=settings.API_V1_PREFIX
)


# =====================================================================
# MAIN (para desarrollo local)
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
