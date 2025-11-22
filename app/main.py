"""
Aplicación principal FastAPI
Sistema de Alertas Predictivas - Farmacias Siman

Autor: Gary González Zepeda
Fecha: 2025-11-22
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

# Configurar logging
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
    logger.info("🚀 Iniciando aplicación...")
    logger.info(f"   Versión: {settings.APP_VERSION}")
    logger.info(f"   Entorno: {'DEBUG' if settings.DEBUG else 'PRODUCTION'}")
    logger.info(f"   Supabase: {settings.SUPABASE_URL}")
    
    # Verificar conexión a Supabase
    try:
        result = supabase_client.table('catalogo_medicamentos').select('count', count='exact').limit(1).execute()
        logger.info(f"   ✓ Conexión a Supabase exitosa")
    except Exception as e:
        logger.error(f"   ✗ Error conectando a Supabase: {str(e)}")
    
    yield
    
    # Shutdown
    logger.info("👋 Cerrando aplicación...")


# Crear aplicación FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    description="API para sistema de alertas predictivas de inventario farmacéutico",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
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


# Middleware de logging de requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware para logging de todas las requests
    """
    start_time = time.time()
    
    # Log request
    logger.info(f"→ {request.method} {request.url.path}")
    
    # Procesar request
    response = await call_next(request)
    
    # Calcular tiempo de procesamiento
    process_time = time.time() - start_time
    
    # Log response
    logger.info(
        f"← {request.method} {request.url.path} "
        f"status={response.status_code} "
        f"time={process_time:.3f}s"
    )
    
    # Agregar headers de timing
    response.headers["X-Process-Time"] = str(process_time)
    
    return response


# =====================================================================
# EXCEPTION HANDLERS
# =====================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Maneja errores de validación de Pydantic
    """
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
    """
    Maneja excepciones no capturadas
    """
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
# ROUTES
# =====================================================================

@app.get("/", tags=["root"])
async def root():
    """
    Endpoint raíz
    """
    return {
        "success": True,
        "data": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "timestamp": datetime.now().isoformat()
        }
    }


@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check para monitoreo
    """
    try:
        # Verificar conexión a Supabase
        result = supabase_client.table('catalogo_medicamentos').select('count', count='exact').limit(1).execute()
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        db_status = "unhealthy"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "data": {
                    "status": "unhealthy",
                    "database": db_status,
                    "timestamp": datetime.now().isoformat()
                }
            }
        )
    
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "database": db_status,
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