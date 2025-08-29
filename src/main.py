"""
Main FastAPI application for Farmacias Siman MVP - Predictive Inventory Management System
"""

from fastapi import FastAPI, HTTPException, status, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List

# Local modules
from src.database import DataRepository
from src.forecasting.xgboost_model import PharmaceuticalForecastModel

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("neurotechn-api")

# -----------------------------------------------------------------------------
# Lifespan (startup/shutdown)
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NeuroTecHN API...")
    app.state.db: DataRepository = DataRepository()
    app.state.forecaster: PharmaceuticalForecastModel = PharmaceuticalForecastModel()
    logger.info("API started successfully")
    yield
    logger.info("Shutting down API... (nothing to close)")
    logger.info("API shutdown complete")

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Farmacias Siman - Sistema Predictivo de Inventario (MVP)",
    description="API para gestión predictiva de inventario farmacéutico con XGBoost",
    version="1.0.0",
    lifespan=lifespan
)

# CORS (ajusta dominios en producción)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # <-- RESTRINGE en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    return v

# -----------------------------------------------------------------------------
# Root & Health
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "name": "Farmacias Siman MVP API",
        "version": app.version,
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
    }

@app.get("/health")
def health_check():
    try:
        db_ok = app.state.db.db.test_connection()
        return {
            "status": "healthy" if db_ok else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "api": "healthy",
                "database": "healthy" if db_ok else "unreachable",
                "model": "healthy"
            }
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unhealthy: {e}"
        )

# -----------------------------------------------------------------------------
# API Info
# -----------------------------------------------------------------------------
@app.get("/api/info")
def api_info():
    return {
        "name": app.title,
        "description": app.description,
        "version": app.version,
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "forecast": "/api/forecast (POST) + alias /forecast (POST)",
            "forecast_latest": "/api/forecast/latest (GET)",
            "alerts_list": "/api/alerts (GET)",
            "alerts_ack": "/api/alerts/{alert_id}/acknowledge (POST)",
            "inventory_current": "/api/inventory/current (GET)",
            "metrics_model": "/api/metrics/model (GET)"
        }
    }

# -----------------------------------------------------------------------------
# Forecast
# -----------------------------------------------------------------------------
@app.post("/api/forecast")
def create_forecast(
    horizonte_dias: int = Query(7, ge=7, le=28, description="7, 14 o 28"),
    skus: Optional[List[str]] = Query(default=None, description="Lista de SKUs opcional")
):
    """
    Genera pronóstico para los SKUs dados y guarda resultados/ métricas en Supabase.
    """
    try:
        if horizonte_dias not in [7, 14, 28]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Horizon must be 7, 14, or 28 days"
            )

        db: DataRepository = app.state.db
        model: PharmaceuticalForecastModel = app.state.forecaster

        # 1) ventas últimos TRAINING_WINDOW_DAYS
        sales = db.get_sales_data()
        if sales.empty:
            return {"status": "no-data", "message": "No sales in last window"}

        # Si se especifican SKUs, filtramos
        if skus:
            sales = sales[sales["sku"].isin(skus)]
            if sales.empty:
                return {"status": "no-data", "message": "No sales for provided SKUs"}

        # 2) entrenar y pronosticar
        forecasts_df, metrics_df, summary = model.train_and_forecast_all(
            sales_df=sales,
            skus=skus,
            horizon_days=horizonte_dias,
            save_models=False
        )

        # 3) registrar ejecución y persistir
        run_id = db.save_forecast_run(
            modelo="xgboost",
            version="1.0.0",
            horizonte_dias=horizonte_dias,
            ventana_entrenamiento_dias=getattr(app.state.db.settings, "TRAINING_WINDOW_DAYS", 90),
            parametros={"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
            skus_procesados=int(summary.get("total_skus", 0))
        )

        if not forecasts_df.empty:
            db.save_forecasts(run_id, forecasts_df)
        if not metrics_df.empty:
            db.save_metrics(run_id, metrics_df)

        # 4) actualizar notas del run
        db.update_forecast_run(
            run_id=run_id,
            exito=True,
            skus_procesados=int(summary.get("total_skus", 0)),
            metricas_globales={"avg_mape": summary.get("avg_mape")}
        )

        return {
            "status": "success",
            "run_id": run_id,
            "horizon_days": horizonte_dias,
            "skus_processed": int(summary.get("total_skus", 0)),
            "avg_mape": summary.get("avg_mape"),
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Forecast generation failed")
        # intenta etiquetar el run si ya existe (best-effort)
        try:
            if "run_id" in locals():
                app.state.db.update_forecast_run(
                    run_id=run_id, exito=False, skus_procesados=0, mensaje_error=str(e)
                )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast generation failed: {e}"
        )

# Alias para pg_cron/pg_net (usa header secreto)
@app.post("/forecast")
def forecast_alias(
    horizonte_dias: int = Query(7, ge=7, le=28),
    skus: Optional[List[str]] = Query(default=None),
    x_cron_secret: Optional[str] = Header(default=None)
):
    expected = _env("CRON_SECRET")
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret")
    return create_forecast(horizonte_dias=horizonte_dias, skus=skus)

@app.get("/api/forecast/latest")
def get_latest_forecast(sku: Optional[str] = None):
    """Devuelve pronósticos del último run (vista v_forecast_latest)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_latest_forecast(sku=sku)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to retrieve latest forecast")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# -----------------------------------------------------------------------------
# Alerts
# -----------------------------------------------------------------------------
@app.get("/api/alerts")
def get_alerts(
    sku: Optional[str] = None,
    tipo_alerta: Optional[str] = None,
    severidad: Optional[str] = None
):
    """
    Devuelve alertas activas (resuelta=false). Filtrable por sku/tipo_alerta/severidad.
    """
    try:
        db: DataRepository = app.state.db
        df = db.get_active_alerts(sku=sku, tipo_alerta=tipo_alerta, severidad=severidad)
        return {
            "status": "success",
            "count": int(len(df)),
            "alerts": df.to_dict(orient="records")
        }
    except Exception as e:
        logger.exception("Failed to retrieve alerts")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, comentario: Optional[str] = None):
    """Marca una alerta como resuelta (RPC ack_alert(p_id uuid))."""
    try:
        db: DataRepository = app.state.db
        ok = db.acknowledge_alert(alert_id=alert_id, comentario=comentario)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to acknowledge alert")
        return {"status": "success", "alert_id": alert_id, "message": "Alert acknowledged successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to acknowledge alert")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# -----------------------------------------------------------------------------
# Inventory
# -----------------------------------------------------------------------------
@app.get("/api/inventory/current")
def get_inventory_current(sku: Optional[str] = None):
    """Último registro de inventario por SKU (ultimos 7 días)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_current_inventory(sku=sku)
        return {
            "status": "success",
            "count": int(len(df)),
            "inventory": df.to_dict(orient="records"),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.exception("Failed to retrieve current inventory")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# -----------------------------------------------------------------------------
# Metrics / KPIs
# -----------------------------------------------------------------------------
@app.get("/api/metrics/model")
def get_model_metrics():
    """KPIs del modelo desde la vista v_kpi_modelo."""
    try:
        db: DataRepository = app.state.db
        kpi = db.get_model_kpis()
        return {
            "status": "success",
            "metrics": kpi,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.exception("Failed to retrieve model metrics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.exception_handler(404)
def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "status": "error",
            "message": "Endpoint not found",
            "path": str(request.url)
        }
    )

@app.exception_handler(500)
def internal_error_handler(request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error occurred"
        }
    )

# -----------------------------------------------------------------------------
# Dev runner
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
