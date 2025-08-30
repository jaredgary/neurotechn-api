# src/main.py
"""
FastAPI app (MVP) con control de concurrencia para /api/forecast mediante Redis Lock.
- Si REDIS_URL está definido, usa un lock distribuido (recomendado en producción).
- Si no, hace fallback a un lock en memoria (solo protege dentro del mismo proceso).
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any, Dict, Optional, List

import logging
import os
import threading

from fastapi import FastAPI, HTTPException, status, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---- Dependencias locales
from src.database import DataRepository
from src.forecasting.xgboost_model import PharmaceuticalForecastModel
from src.config import get_settings

# ---- Redis (opcional pero recomendado)
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
    """
    Candado de ejecución para /api/forecast.
    - Con Redis: lock distribuido "lock:forecast" con TTL.
    - Fallback: threading.Lock() (solo mismo proceso).
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        # Parámetros del lock (configurables por ENV)
        self.lock_key = os.getenv("FORECAST_LOCK_KEY", "lock:forecast")
        self.lock_ttl = int(os.getenv("FORECAST_LOCK_TTL_SECONDS", "3600"))  # 1h
        self.lock_block = float(os.getenv("FORECAST_LOCK_BLOCK_SECONDS", "0"))  # no esperar

        # Cliente Redis si REDIS_URL está presente y redis está instalado
        self._redis_client: Optional["redis.Redis"] = None
        self._local_lock = threading.Lock()

        redis_url = os.getenv("REDIS_URL")
        if redis and redis_url:
            try:
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
                # Prueba rápida de conexión
                self._redis_client.ping()
                logger.info("ForecastConcurrencyGuard: Redis conectado para locking distribuido.")
            except Exception as e:
                logger.warning(f"ForecastConcurrencyGuard: no se pudo conectar a Redis ({e}). "
                               f"Usando lock local (NO distribuido).")
                self._redis_client = None
        else:
            logger.info("ForecastConcurrencyGuard: REDIS_URL no configurado. "
                        "Usando lock local (NO distribuido).")

    @contextmanager
    def acquire(self):
        """
        Context manager del lock. Si no puede adquirirlo:
        - Con Redis: lanza HTTP 409
        - Fallback: intenta threading.Lock, si ocupado lanza HTTP 409
        """
        # Redis lock
        if self._redis_client is not None:
            lock = self._redis_client.lock(
                name=self.lock_key,
                timeout=self.lock_ttl,             # el lock se libera solo si el proceso muere
                blocking_timeout=self.lock_block,  # 0 => no esperar
            )
            got = False
            try:
                got = lock.acquire(blocking=(self.lock_block is None or self.lock_block > 0.0))
                if not got:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "forecast_already_running", "retry_after_seconds": 30},
                    )
                yield
            finally:
                if got:
                    try:
                        lock.release()
                    except Exception as e:
                        logger.warning(f"No se pudo liberar el lock de Redis (posible expirado): {e}")
            return

        # Fallback local
        got = self._local_lock.acquire(blocking=False)
        try:
            if not got:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "forecast_already_running_local", "retry_after_seconds": 5},
                )
            yield
        finally:
            if got:
                self._local_lock.release()


# -----------------------------------------------------------------------------
# Lifespan: inicializa dependencias
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.db = DataRepository()  # repositorio Supabase
        app.state.forecaster = PharmaceuticalForecastModel()
        app.state.guard = ForecastConcurrencyGuard()
        logger.info("App ready: DB + Forecaster + ConcurrencyGuard inicializados.")
        yield
    finally:
        # Aquí podrías cerrar conexiones si fuese necesario
        pass


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Farmacias Siman - Sistema Predictivo de Inventario (MVP)",
    description="API para gestión predictiva de inventario farmacéutico con XGBoost",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS desde ENV en prod; "*" en dev
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
            "redoc": "/redoc",
            "forecast": "/api/forecast (POST) + alias /forecast (POST)",
            "forecast_latest": "/api/forecast/latest (GET)",
            "alerts_list": "/api/alerts (GET)",
            "alerts_ack": "/api/alerts/{alert_id}/acknowledge (POST)",
            "inventory_current": "/api/inventory/current (GET)",
            "metrics_model": "/api/metrics/model (GET)",
        },
    }


# -----------------------------------------------------------------------------
# Forecast (con control de concurrencia)
# -----------------------------------------------------------------------------
@app.post("/api/forecast")
def create_forecast(
    horizonte_dias: int = Query(7, ge=7, le=28, description="7, 14 o 28"),
    skus: Optional[List[str]] = Query(default=None, description="Lista de SKUs opcional"),
):
    """
    Genera pronóstico para los SKUs dados y guarda resultados/métricas en Supabase.
    Concurrencia: protegido por Redis Lock (o lock local si no hay Redis).
    """
    if horizonte_dias not in (7, 14, 28):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Horizon must be 7, 14, or 28 days",
        )

    db: DataRepository = app.state.db
    model: PharmaceuticalForecastModel = app.state.forecaster
    guard: ForecastConcurrencyGuard = app.state.guard

    with guard.acquire():  # <- AQUÍ se controla la concurrencia
        try:
            # 1) Datos de venta (últimos N días según settings)
            sales_df = db.get_sales_data(start_date=None, end_date=None, sku=None)

            # 2) Entrenar + pronosticar
            forecasts_df, metrics_df, summary = model.train_and_forecast_all(
                sales_df=sales_df, skus=skus, horizon_days=horizonte_dias
            )

            # 3) Registrar ejecución
            run_id = db.save_forecast_run(
                modelo="xgboost",
                version=getattr(model, "VERSION", "1.0.0"),
                horizonte_dias=horizonte_dias,
                ventana_entrenamiento_dias=getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
                parametros={"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
                skus_procesados=int(summary.get("total_skus", 0)),
            )

            # 4) Persistir resultados
            if not forecasts_df.empty:
                db.save_forecasts(run_id, forecasts_df)
            if not metrics_df.empty:
                db.save_metrics(run_id, metrics_df)

            # 5) Actualizar notas/resumen del run
            db.update_forecast_run(
                run_id=run_id,
                exito=True,
                skus_procesados=int(summary.get("total_skus", 0)),
                metricas_globales={"avg_mape": summary.get("avg_mape")},
            )

            return {
                "status": "success",
                "run_id": run_id,
                "horizon_days": horizonte_dias,
                "skus_processed": int(summary.get("total_skus", 0)),
                "avg_mape": summary.get("avg_mape"),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Forecast failed")
            # Deja traza en ejecuciones_modelo si alcanzaste a crear run_id
            try:
                if "run_id" in locals() and run_id:
                    db.update_forecast_run(
                        run_id=run_id,
                        exito=False,
                        skus_procesados=int(summary.get("total_skus", 0)) if "summary" in locals() else 0,
                        mensaje_error=str(e),
                    )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )


# Alias para pg_cron/pg_net (valida header secreto y reutiliza la lógica anterior)
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
        df = db.get_active_alerts(sku=sku, tipo_alerta=tipo_alerta, severidad=severidad, limit=limit, offset=offset)
        return {"items": df.to_dict(orient="records"), "limit": limit, "offset": offset, "total": len(df)}
    except Exception as e:
        logger.exception("Failed to retrieve alerts")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, comentario: Optional[str] = None):
    """Marca una alerta como resuelta (usa RPC ack_alert)."""
    try:
        db: DataRepository = app.state.db
        ok = db.acknowledge_alert(alert_id=alert_id)  # si habilitas comentario, adapta db.acknowledge_alert
        if not ok:
            raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
        return {"status": "success", "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to acknowledge alert")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Inventory & Metrics
# -----------------------------------------------------------------------------
@app.get("/api/inventory/current")
def get_inventory_current(sku: Optional[str] = None):
    """Último inventario por SKU (últimos 7 días)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_current_inventory(sku=sku)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to retrieve inventory")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metrics/model")
def get_model_metrics():
    """KPIs del modelo (vista v_kpi_modelo)."""
    try:
        db: DataRepository = app.state.db
        df = db.get_model_kpis()
        return df.to_dict(orient="records")
    except Exception as e:
        logger.exception("Failed to retrieve model metrics")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.exception_handler(404)
def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"status": "not_found", "message": "The requested resource was not found."},
    )


@app.exception_handler(500)
def internal_error_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error."},
    )