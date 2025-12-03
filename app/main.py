"""
PharmaPredict API - Backend FastAPI
Sistema Predictivo de Inventario Farmacéutico
Versión: 2.1.0 (SaaS Genérico)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown events."""
    # Startup
    print(f"🚀 Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"📊 Environment: {settings.ENVIRONMENT}")
    print(f"🔗 API Base URL: {settings.API_V1_STR}")
    yield
    # Shutdown
    print(f"👋 Shutting down {settings.PROJECT_NAME}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API para el Sistema Predictivo de Inventario Farmacéutico",
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ============================================================
# CORS Configuration - CRÍTICO para conexión Frontend-Backend
# ============================================================
# Lista de orígenes permitidos
allowed_origins = [
    # Producción Fly.io
    "https://farmacias-siman-frontend.fly.dev",
    "https://farmacias-siman-api.fly.dev",
    # Desarrollo local
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    # Cualquier subdominio de fly.dev (para staging)
    "https://*.fly.dev",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Permite GET, POST, PUT, DELETE, OPTIONS, etc.
    allow_headers=["*"],  # Permite todos los headers
    expose_headers=["*"],
    max_age=600,  # Cache preflight requests por 10 minutos
)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "api_version": "v1",
        "cors_enabled": True,
        "allowed_origins": allowed_origins,
    }
