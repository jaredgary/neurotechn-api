# src/main.py
"""
FastAPI (MVP) con:
- /api/forecast (POST) + alias /forecast (POST)
- Re-cálculo de alertas tras forecast (RF-03)
- /api/alerts/recompute (POST)     -> fuerza evaluación de alertas
- /api/forecast/topn (GET)         -> EXPUESTO por api_extra.py para evitar duplicados
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Optional, List

import logging
import os
import threading

from fastapi import FastAPI, HTTPException, status, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---- Dependencias locales
from src.database import DataRepository
from src.config import get_settings
from src.tasks import recompute_alerts

# Modelo con fallback de import (según estructura del repo)
try:
    from src.forecasting.xgboost_model import PharmaceuticalForecastModel
except Exception:  # pragma: no cover
    from src.xgboost_model import PharmaceuticalForecastModel  # fallback

# Router extra (incluye /api/forecast/topn y /api/dashboard/summary si lo creaste)
from src.api_extra import router as extra_router

# ---- Redis (opcional)
try:
    import redis  # pip install redis
except Exception:  # pragma: no cover
    redis = None

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
# Concurrency Guard (Redis + fallback)
# -----------------------------------------------------------------------------
class ForecastConcurrencyGuard:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.lock_key = os.getenv("FORECAST_LOCK_KEY", "lock:forecast")
        self.lock_ttl = int(os.getenv("FORECAST_LOCK_TTL_SECONDS", "3600"))     # 1h
        self.lock_block = float(os.getenv("FORECAST_LOCK_BLOCK_SECONDS", "0"))  # no esperar

        self._redis_client: Optional["redis.Redis"] = None
        self._local_lock = threading.Lock()

        redis_url = os.getenv("REDIS_URL")
        if redis and redis_url:
            try:
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
                self._redis_client.ping()
                logger.info("Redis conectado para locking distribuido.")
            except Exception as e:
                logger.warning(f"No se pudo conectar a Redis ({e}). Usando lock local.")
                self._redis_client = None
        else:
            logger.info("REDIS_URL no configurado. Usando lock local.")

    @contextmanager
    def acquire(self):
        if self._redis_client is not None:
            lock = self._redis_client.lock(
                name=self.lock_key,
                timeout=self.lock_ttl,
                blocking_timeout=self.lock_block,
            )
            got = False
            try:
                got = lock.acquire(blocking=(self.lock_block is None or self.lock_block > 0.0))
                if not got:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail={"error": "forecast_already_running", "retry_after_seconds": 30})
                yield
            finally:
                if got:
                    try:
                        lock.release()
                    except Exception as e:
                        logger.warning(f"No se pudo liberar el lock de Redis: {e}")
            return

        got = self._local_lock.acquire(blocking=False)
        try:
            if not got:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail={"error": "forecast_already_running_local", "retry_after_seconds": 5})
            yield
        finally:
            if got:
                self._local_lock.release()


# -----------------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.db = DataRepository()
        app.state.forecaster = PharmaceuticalForecastModel()
        app.state.guard = ForecastConcurrencyGuard()
        logger.info("App ready: DB + Forecaster + Guard.")
        yield
    finally:
        pass


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Farmacias Siman - Sistema Predictivo de Inventario (MVP)",
    description="API para gestión predictiva de inventario farmacéutico con XGBoost",
    version="1.0.0",
    lifespan=lifespan,
)

# Registra router extra (/api/forecast/topn, /api/dashboard/summary, etc.)
app.include_router(extra_router, prefix="/api")

# CORS (si usas credenciales, usa orígenes explícitos; '*' + credentials no es válido)
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


# -----------------------------------------------------------------------------
# Root & Health
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "ok", "name": app.title, "version": app.version}


@app.get("/health")
def health_check():
    ok = app.state.db.test_connection()
    return {"status": "ok" if ok else "degraded", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/info")
def api_info():
    return {
        "name": app.title,
        "description": app.description,
        "version": app.version,
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "forecast": "/api/forecast (POST) + alias /forecast (POST)",
            "forecast_latest": "/api/forecast/latest (GET)",
            "forecast_topn": "/api/forecast/topn (GET) (en api_extra.py)",
            "alerts_list": "/api/alerts (GET)",
            "alerts_ack": "/api/alerts/{alert_id}/acknowledge (POST)",
            "alerts_recompute": "/api/alerts/recompute (POST)",
            "inventory_current": "/api/inventory/current (GET)",
            "metrics_model": "/api/metrics/model (GET)",
        },
    }


# -----------------------------------------------------------------------------
# Forecast
# -----------------------------------------------------------------------------
@app.post("/api/forecast")
def create_forecast(
    horizonte_dias: int = Query(7, ge=7, le=28, description="7, 14 o 28"),
    skus: Optional[List[str]] = Query(default=None, description="Lista de SKUs opcional"),
):
    """Genera pronóstico y persiste resultados/metricas. Protegido por lock de concurrencia."""
    if horizonte_dias not in (7, 14, 28):
        raise HTTPException(status_code=400, detail="Horizon must be 7, 14, or 28 days")

    db: DataRepository = app.state.db
    model: PharmaceuticalForecastModel = app.state.forecaster
    guard: ForecastConcurrencyGuard = app.state.guard

    with guard.acquire():
        try:
            sales_df = db.get_sales_data()
            forecasts_df, metrics_df, summary = model.train_and_forecast_all(
                sales_df=sales_df, skus=skus, horizon_days=horizonte_dias
            )

            run_id = db.save_forecast_run(
                modelo="xgboost",
                version=getattr(model, "VERSION", "1.0.0"),
                horizonte_dias=horizonte_dias,
                ventana_entrenamiento_dias=getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
                parametros={"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
                skus_procesados=int(summary.get("total_skus", 0)),
            )

            if not forecasts_df.empty:
                db.save_forecasts(run_id, forecasts_df)
            if not metrics_df.empty:
                db.save_metrics(run_id, metrics_df)

            db.update_forecast_run(
                run_id=run_id, exito=True,
                skus_procesados=int(summary.get("total_skus", 0)),
                metricas_globales={"avg_mape": summary.get("avg_mape")},
            )

            # Recalcular alertas (RF-03) inmediatamente tras un forecast válido
            alerts = {}
            try:
                alerts = recompute_alerts()
            except Exception as e:
                logger.exception(f"Recompute alerts failed: {e}")

            return {
                "status": "success",
                "run_id": run_id,
                "horizon_days": horizonte_dias,
                "skus_processed": int(summary.get("total_skus", 0)),
                "avg_mape": summary.get("avg_mape"),
                "alerts_created": alerts,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Forecast failed")
            try:
                if "run_id" in locals() and run_id:
                    db.update_forecast_run(
                        run_id=run_id, exito=False,
                        skus_procesados=int(summary.get("total_skus", 0)) if "summary" in locals() else 0,
                        mensaje_error=str(e),
                    )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(e))


# Alias para cron con secreto
@app.post("/forecast")
def forecast_alias(
    horizonte_dias: int = Query(7, ge=7, le=28),
    skus: Optional[List[str]] = Query(default=None),
    x_cron_secret: Optional[str] = Header(default=None),
):
    expected = _env("CRON_SECRET")
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret")
    return create_forecast(horizonte_dias=horizonte_dias, skus=skus)


@app.get("/api/forecast/latest")
def get_latest_forecast(sku: Optional[str] = None):
    """Último forecast (vista v_forecast_latest)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_latest_forecast(sku=sku)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to retrieve latest forecast")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Alerts
# -----------------------------------------------------------------------------
@app.get("/api/alerts")
def get_alerts(
    sku: Optional[str] = None,
    tipo_alerta: Optional[str] = None,
    severidad: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Alertas activas (resuelta=false)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_active_alerts(sku=sku, tipo_alerta=tipo_alerta, severidad=severidad,
                                  limit=limit, offset=offset)
        # Supabase .range(start,end) es 0-based e INCLUSIVA (usar offset, offset+limit-1).
        return {"items": df.to_dict(orient="records"), "limit": limit, "offset": offset, "total": len(df)}
    except Exception as e:
        logger.exception("Failed to retrieve alerts")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, comentario: Optional[str] = None):
    """Marca una alerta como resuelta (RPC ack_alert)."""
    try:
        db: DataRepository = app.state.db
        ok = db.acknowledge_alert(alert_id=alert_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
        return {"status": "success", "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to acknowledge alert")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/recompute")
def api_recompute_alerts():
    """Recalcula alertas de QUIEBRE_STOCK y VENCIMIENTO (RF-03)."""
    try:
        return recompute_alerts()
    except Exception as e:
        logger.exception("Failed to recompute alerts")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Inventory & Metrics
# -----------------------------------------------------------------------------
@app.get("/api/inventory/current")
def get_inventory_current(sku: Optional[str] = None):
    """Último inventario por SKU (últimos 7 días)."""
    try:
        df = db.get_current_inventory()
        if df.empty:
            return JSONResponse(content=[], status_code=200)

        # Nos aseguramos de exportar campos clave
        cols = [
            "fecha", "sku",
            "unidades_stock", "stock_seguridad",
            "nombre_producto", "atc_code", "lead_time_dias"
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = None

        # Serializar a JSON simple
        out = df[cols].to_dict(orient="records")
        return JSONResponse(content=out, status_code=200)

    except Exception:
        logger.exception("Failed to retrieve current inventory")
        raise HTTPException(status_code=500, detail="Error retrieving current inventory")


@app.get("/api/metrics/model")
def get_model_metrics():
    """KPIs del modelo (vista v_kpi_modelo)."""
    try:
        db: DataRepository = app.state.db
        return db.get_model_kpis()
    except Exception as e:
        logger.exception("Failed to retrieve model metrics")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.exception_handler(404)
def not_found_handler(request, exc):
    return JSONResponse(status_code=404,
                        content={"status": "not_found", "message": "The requested resource was not found."})


@app.exception_handler(500)
def internal_error_handler(request, exc):
    return JSONResponse(status_code=500,
                        content={"status": "error", "message": "Internal server error."})
