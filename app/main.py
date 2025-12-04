"""
Aplicación principal FastAPI
Sistema Predictivo de Inventario Farmacéutico

Versión: 2.1.0 - SaaS Genérico con Cálculo Dinámico
Autor: Gary González Zepeda
Fecha: 2025-12-04

PRINCIPIO FUNDAMENTAL:
"CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"
Todas las métricas se calculan dinámicamente de los datos cargados.

CORRECCIÓN CORS: Headers explícitos en exception handlers
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


# ==========================================================
# CORS ORIGINS - Lista explícita (wildcards NO funcionan)
# ==========================================================
CORS_ORIGINS = [
    # Desarrollo local
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    # Producción Fly.io
    "https://farmacias-siman-frontend.fly.dev",
    "https://farmacias-siman-api.fly.dev",
    "https://farmacias-siman.fly.dev",
]


def add_cors_headers(response: JSONResponse, request: Request) -> JSONResponse:
    """
    Agrega headers CORS a una respuesta.
    Necesario para exception handlers que bypassean el middleware.
    """
    origin = request.headers.get("origin", "")
    
    # Verificar si el origen está permitido
    if origin in CORS_ORIGINS or "*" in CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Expose-Headers"] = "*"
    
    return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle de la aplicación
    Se ejecuta al iniciar y al cerrar
    """
    # Startup
    logger.info("=" * 60)
    logger.info("🚀 Iniciando Sistema Predictivo de Inventario")
    logger.info("=" * 60)
    logger.info(f"   Versión: {settings.APP_VERSION}")
    logger.info(f"   Entorno: {'DEBUG' if settings.DEBUG else 'PRODUCTION'}")
    logger.info(f"   CORS Origins: {len(CORS_ORIGINS)} dominios configurados")
    logger.info("-" * 60)

    # Verificar conexión a Supabase
    try:
        catalogo = supabase_client.table('catalogo_medicamentos').select('count', count='exact').execute()
        ventas = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
        logger.info(f"   ✅ Conexión a Supabase exitosa")
        logger.info(f"   📊 SKUs cargados: {catalogo.count}")
        logger.info(f"   📈 Registros ventas: {ventas.count}")
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
## Sistema Predictivo de Inventario Farmacéutico - SaaS Genérico

API REST para gestión predictiva de inventarios con Machine Learning.

### Principio Fundamental:
**"CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"**

### Autor
Gary González Zepeda - Maestría GTI, UNITEC Honduras
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# =====================================================================
# MIDDLEWARE - ORDEN CRÍTICO
# =====================================================================

# 1. CORS PRIMERO - Debe ser el primer middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# 2. Compresión GZIP después
app.add_middleware(GZipMiddleware, minimum_size=1000)


# =====================================================================
# MIDDLEWARE HTTP - Logging y timing
# =====================================================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware para logging de requests"""
    start_time = time.time()
    
    # Procesar request
    response = await call_next(request)
    
    # Calcular tiempo
    process_time_ms = (time.time() - start_time) * 1000
    
    # Log
    logger.info(
        f"{request.method} {request.url.path} "
        f"status={response.status_code} "
        f"time={process_time_ms:.0f}ms"
    )
    
    # Headers de timing
    response.headers["X-Process-Time"] = f"{process_time_ms:.0f}ms"
    response.headers["X-API-Version"] = settings.APP_VERSION
    
    return response


# =====================================================================
# EXCEPTION HANDLERS - Con CORS headers
# =====================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Maneja errores de validación con CORS headers"""
    logger.error(f"Error de validación: {exc.errors()}")
    
    response = JSONResponse(
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
    
    # CRÍTICO: Agregar headers CORS
    return add_cors_headers(response, request)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Maneja excepciones no capturadas con CORS headers"""
    logger.error(f"Error no manejado: {str(exc)}", exc_info=True)
    
    response = JSONResponse(
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
    
    # CRÍTICO: Agregar headers CORS
    return add_cors_headers(response, request)


# =====================================================================
# ROUTES BASE
# =====================================================================

@app.get("/", tags=["root"])
async def root():
    """Endpoint raíz"""
    try:
        catalogo = supabase_client.table('catalogo_medicamentos').select('count', count='exact').execute()
        ventas = supabase_client.table('ventas_diarias').select('count', count='exact').execute()

        return {
            "success": True,
            "data": {
                "name": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "status": "running",
                "cors_enabled": True,
                "cors_origins_count": len(CORS_ORIGINS),
                "sistema": {
                    "skus_cargados": catalogo.count,
                    "registros_ventas": ventas.count,
                },
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error en root: {e}")
        return {
            "success": True,
            "data": {
                "name": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "status": "running",
                "cors_enabled": True,
                "timestamp": datetime.now().isoformat()
            }
        }


@app.get("/health", tags=["health"])
async def health_check():
    """Health check"""
    checks = {"api": "healthy", "database": "unknown"}
    
    try:
        result = supabase_client.table('catalogo_medicamentos').select('count', count='exact').limit(1).execute()
        checks["database"] = "healthy"
        checks["medicamentos_count"] = result.count
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        checks["database"] = "unhealthy"
        checks["error"] = str(e)
    
    return {
        "success": True,
        "data": {
            "status": "healthy" if checks["database"] == "healthy" else "degraded",
            "checks": checks,
            "version": settings.APP_VERSION,
            "cors_origins": CORS_ORIGINS,
            "timestamp": datetime.now().isoformat()
        }
    }


# =====================================================================
# INCLUIR ROUTERS
# =====================================================================
app.include_router(
    api_router,
    prefix=settings.API_V1_PREFIX
)


# =====================================================================
# MAIN (desarrollo local)
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
