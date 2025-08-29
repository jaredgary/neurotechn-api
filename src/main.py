"""
Main FastAPI application for Farmacias Siman MVP - Predictive Inventory Management System
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime
from typing import Dict, Any

# Import local modules
from src.config import settings
from src.database import DatabaseManager
from src.forecasting.xgboost_model import XGBoostForecaster

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Farmacias Siman MVP API...")
    app.state.db = DatabaseManager()
    app.state.forecaster = XGBoostForecaster()
    logger.info("API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down API...")
    if hasattr(app.state, 'db'):
        await app.state.db.close()
    logger.info("API shutdown complete")

# Create FastAPI instance
app = FastAPI(
    title="Farmacias Siman - Sistema Predictivo de Inventario",
    description="API para gestión predictiva de inventario farmacéutico con XGBoost",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Farmacias Siman MVP API",
        "version": "1.0.0",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat()
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    try:
        # Check database connection
        db_status = "healthy"
        if hasattr(app.state, 'db'):
            db_status = await app.state.db.health_check()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "api": "healthy",
                "database": db_status,
                "model": "healthy" if hasattr(app.state, 'forecaster') else "not_initialized"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unhealthy"
        )

# API Info endpoint
@app.get("/api/info")
async def api_info():
    """Get API information and available endpoints"""
    return {
        "name": app.title,
        "description": app.description,
        "version": app.version,
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "forecast": "/api/forecast",
            "alerts": "/api/alerts",
            "inventory": "/api/inventory",
            "metrics": "/api/metrics"
        }
    }

# Forecast endpoints
@app.post("/api/forecast")
async def create_forecast(
    horizonte_dias: int = 7,
    skus: list[str] = None
):
    """
    Generate forecast for specified SKUs and horizon
    
    Args:
        horizonte_dias: Forecast horizon in days (7, 14, or 28)
        skus: List of SKUs to forecast (optional, all if not specified)
    """
    try:
        if horizonte_dias not in [7, 14, 28]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Horizon must be 7, 14, or 28 days"
            )
        
        # Generate forecast using the model
        if hasattr(app.state, 'forecaster'):
            result = await app.state.forecaster.generate_forecast(
                horizon=horizonte_dias,
                skus=skus
            )
            return {
                "status": "success",
                "horizon_days": horizonte_dias,
                "skus_processed": len(result.get("forecasts", [])),
                "run_id": result.get("run_id"),
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Forecasting model not initialized"
            )
            
    except Exception as e:
        logger.error(f"Forecast generation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast generation failed: {str(e)}"
        )

@app.get("/api/forecast/latest")
async def get_latest_forecast():
    """Get the latest forecast run results"""
    try:
        if hasattr(app.state, 'db'):
            result = await app.state.db.get_latest_forecast()
            return result
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve latest forecast: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Alert endpoints
@app.get("/api/alerts")
async def get_alerts(
    estado: str = "PENDIENTE",
    severidad: str = None
):
    """
    Get alerts filtered by status and severity
    
    Args:
        estado: Alert status (PENDIENTE, EN_REVISION, RESUELTA, DESCARTADA)
        severidad: Alert severity (BAJA, MEDIA, ALTA, CRITICA)
    """
    try:
        if hasattr(app.state, 'db'):
            alerts = await app.state.db.get_alerts(
                estado=estado,
                severidad=severidad
            )
            return {
                "status": "success",
                "count": len(alerts),
                "alerts": alerts
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve alerts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    comentario: str = None
):
    """Acknowledge an alert and update its status"""
    try:
        if hasattr(app.state, 'db'):
            result = await app.state.db.acknowledge_alert(
                alert_id=alert_id,
                comentario=comentario
            )
            return {
                "status": "success",
                "alert_id": alert_id,
                "message": "Alert acknowledged successfully"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to acknowledge alert: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Inventory endpoints
@app.get("/api/inventory/status")
async def get_inventory_status():
    """Get current inventory status"""
    try:
        if hasattr(app.state, 'db'):
            status = await app.state.db.get_inventory_status()
            return {
                "status": "success",
                "inventory": status,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve inventory status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/api/inventory/critical")
async def get_critical_inventory():
    """Get critical inventory items (low stock or expiring soon)"""
    try:
        if hasattr(app.state, 'db'):
            critical_items = await app.state.db.get_critical_inventory()
            return {
                "status": "success",
                "count": len(critical_items),
                "critical_items": critical_items
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve critical inventory: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Metrics endpoints
@app.get("/api/metrics/model")
async def get_model_metrics():
    """Get model performance metrics"""
    try:
        if hasattr(app.state, 'db'):
            metrics = await app.state.db.get_model_metrics()
            return {
                "status": "success",
                "metrics": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve model metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/api/metrics/kpis")
async def get_kpis():
    """Get key performance indicators"""
    try:
        if hasattr(app.state, 'db'):
            kpis = await app.state.db.get_kpis()
            return {
                "status": "success",
                "kpis": kpis,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not connected"
            )
    except Exception as e:
        logger.error(f"Failed to retrieve KPIs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "status": "error",
            "message": "Endpoint not found",
            "path": str(request.url)
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error occurred"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )