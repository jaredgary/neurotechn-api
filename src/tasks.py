"""
Celery tasks for background processing (MVP-aligned)
- Usa DataRepository (sin métodos async)
- Usa PharmaceuticalForecastModel.train_and_forecast_all
- Genera/gestiona alertas usando tablas/vistas reales del esquema
"""

from __future__ import annotations

from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional

import pandas as pd

from src.database import DataRepository
from src.forecasting.xgboost_model import PharmaceuticalForecastModel

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers de negocio para alertas
# ---------------------------------------------------------------------------
def _evaluate_stock_risk(db: DataRepository) -> int:
    """
    Crea alertas de tipo QUIEBRE_STOCK usando v_demanda_futura_7_14_28 e inventario actual.
    Severidad:
      - ALTA  si stock < yhat_7d
      - MEDIA si stock < yhat_14d
      - BAJA  si stock < yhat_28d
    Retorna: número de alertas creadas.
    """
    inv_df = db.get_current_inventory()        # sku, fecha, unidades_stock, stock_seguridad
    dem_df = db.get_future_demand_agg()        # sku, yhat_7d, yhat_14d, yhat_28d

    if inv_df.empty or dem_df.empty:
        logger.info("No inventory or demand data to evaluate stock risk.")
        return 0

    inv_df = inv_df[['sku', 'unidades_stock', 'stock_seguridad']].copy()
    if 'stock_seguridad' not in inv_df:
        inv_df['stock_seguridad'] = 0

    merged = pd.merge(dem_df, inv_df, on='sku', how='left')
    merged['unidades_stock'] = merged['unidades_stock'].fillna(0)

    created = 0
    for _, r in merged.iterrows():
        sku = r['sku']
        stock = float(r['unidades_stock'] or 0)
        y7 = float(r.get('yhat_7d') or 0.0)
        y14 = float(r.get('yhat_14d') or 0.0)
        y28 = float(r.get('yhat_28d') or 0.0)

        severity: Optional[str] = None
        if stock < y7:
            severity = "ALTA"
        elif stock < y14:
            severity = "MEDIA"
        elif stock < y28:
            severity = "BAJA"

        if not severity:
            continue

        # evitar duplicados activos para el mismo SKU/tipo/severidad
        existing = db.get_active_alerts(sku=sku, tipo_alerta="QUIEBRE_STOCK", severidad=severity)
        if not existing.empty:
            continue

        descripcion = (
            f"Riesgo de quiebre (sev={severity}). Stock={stock:.0f} vs "
            f"Demanda 7d={y7:.0f}, 14d={y14:.0f}, 28d={y28:.0f}."
        )
        ok = db.create_alert(
            sku=sku,
            tipo_alerta="QUIEBRE_STOCK",
            severidad=severity,
            descripcion=descripcion,
            fecha_objetivo=date.today()
        )
        if ok:
            created += 1

    return created


def _evaluate_expiration_risk(db: DataRepository, days_ahead: int = 30) -> int:
    """
    Crea alertas de tipo VENCIMIENTO para lotes que caducan en <= days_ahead.
    Severidad:
      - ALTA  si <= 7 días
      - MEDIA si <= 14 días
      - BAJA  si <= 30 días
    Retorna: número de alertas creadas.
    """
    lotes = db.get_expiring_batches(days_ahead=days_ahead)
    if lotes.empty:
        logger.info("No expiring batches found.")
        return 0

    created = 0
    # Por SKU, tomamos el lote más próximo a caducar
    lotes = lotes.sort_values(['sku', 'fecha_caducidad'])
    first_per_sku = lotes.groupby('sku').head(1)

    for _, r in first_per_sku.iterrows():
        dias = int(r.get('dias_hasta_vencimiento', 30))
        if dias <= 7:
            sev = "ALTA"
        elif dias <= 14:
            sev = "MEDIA"
        else:
            sev = "BAJA"

        sku = r['sku']
        lote_id = r.get('lote_id')
        descripcion = f"Lote próximo a vencer en {dias} días (sev={sev}). Lote={lote_id}."

        existing = db.get_active_alerts(sku=sku, tipo_alerta="VENCIMIENTO", severidad=sev)
        if not existing.empty:
            continue

        ok = db.create_alert(
            sku=sku,
            tipo_alerta="VENCIMIENTO",
            severidad=sev,
            descripcion=descripcion,
            fecha_objetivo=r['fecha_caducidad'].date() if pd.notna(r['fecha_caducidad']) else None,
            lote_id=lote_id
        )
        if ok:
            created += 1

    return created


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------
@shared_task(name="src.tasks.generate_forecast_task")
def generate_forecast_task() -> Dict[str, Any]:
    """
    Genera pronóstico para todos los SKUs en horizontes 7/14/28 y guarda resultados.
    (Equivalente a invocar el endpoint /api/forecast tres veces.)
    """
    try:
        logger.info("Starting forecast generation task")

        db = DataRepository()
        model = PharmaceuticalForecastModel()

        # Ventas base (últimos TRAINING_WINDOW_DAYS)
        sales = db.get_sales_data()
        if sales.empty:
            logger.warning("No sales available in the training window")
            return {"status": "no-data", "message": "No sales data", "results": []}

        results: List[Dict[str, Any]] = []
        for horizon in [7, 14, 28]:
            logger.info(f"Training/forecasting for horizon {horizon} days")

            forecasts_df, metrics_df, summary = model.train_and_forecast_all(
                sales_df=sales,
                skus=None,  # todos
                horizon_days=horizon,
                save_models=False
            )

            run_id = db.save_forecast_run(
                modelo="xgboost",
                version="1.0.0",
                horizonte_dias=horizon,
                ventana_entrenamiento_dias=getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
                parametros={"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
                skus_procesados=int(summary.get("total_skus", 0))
            )

            if not forecasts_df.empty:
                db.save_forecasts(run_id, forecasts_df)
            if not metrics_df.empty:
                db.save_metrics(run_id, metrics_df)

            db.update_forecast_run(
                run_id=run_id,
                exito=True,
                skus_procesados=int(summary.get("total_skus", 0)),
                metricas_globales={"avg_mape": summary.get("avg_mape")}
            )

            results.append({
                "horizon": horizon,
                "run_id": run_id,
                "skus_processed": int(summary.get("total_skus", 0)),
                "avg_mape": summary.get("avg_mape"),
                "timestamp": datetime.utcnow().isoformat()
            })

        logger.info("Forecast generation task completed")
        return {"status": "success", "results": results, "timestamp": datetime.utcnow().isoformat()}

    except Exception as e:
        logger.exception("Forecast generation failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}


@shared_task(name="src.tasks.check_stock_alerts_task")
def check_stock_alerts_task() -> Dict[str, Any]:
    """
    Evalúa y crea alertas de riesgo de quiebre de stock (QUIEBRE_STOCK).
    """
    try:
        logger.info("Starting stock alerts evaluation")
        db = DataRepository()
        created = _evaluate_stock_risk(db)
        logger.info(f"Stock alerts created: {created}")
        return {"status": "success", "alerts_created": int(created), "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.exception("Stock alerts evaluation failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}


@shared_task(name="src.tasks.check_expiration_alerts_task")
def check_expiration_alerts_task(days_ahead: int = 30) -> Dict[str, Any]:
    """
    Evalúa y crea alertas por vencimiento de productos (VENCIMIENTO).
    """
    try:
        logger.info(f"Starting expiration alerts evaluation (<= {days_ahead} days)")
        db = DataRepository()
        created = _evaluate_expiration_risk(db, days_ahead=days_ahead)
        logger.info(f"Expiration alerts created: {created}")
        return {
            "status": "success",
            "alerts_created": int(created),
            "checked_until": (datetime.utcnow() + timedelta(days=days_ahead)).isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.exception("Expiration alerts evaluation failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}


@shared_task(name="src.tasks.update_model_metrics_task")
def update_model_metrics_task() -> Dict[str, Any]:
    """
    Devuelve (y registra en logs) los KPIs del último run desde v_kpi_modelo.
    (No recalcula métricas: ya se guardan en metricas_backtesting al guardar cada run.)
    """
    try:
        logger.info("Fetching model KPIs from view v_kpi_modelo")
        db = DataRepository()
        kpis = db.get_model_kpis()  # dict con mape_prom, mae_prom, sesgo_prom
        logger.info(f"KPIs: {kpis}")
        return {"status": "success", "metrics": kpis, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.exception("Model metrics retrieval failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}


@shared_task(name="src.tasks.cleanup_old_data_task")
def cleanup_old_data_task() -> Dict[str, Any]:
    """
    Lanza el cleanup semanal definido en la función SQL cleanup_old_runs() (si está expuesta como RPC).
    Nota: En tu capa de datos ya programaste el cron; esto es utility manual.
    """
    try:
        logger.info("Triggering cleanup_old_runs() via RPC (if available)")
        db = DataRepository()
        try:
            # Si la función SQL 'cleanup_old_runs' está en schema public y el service_role tiene permiso,
            # Supabase la expone como RPC.
            db.db.service_client.rpc("cleanup_old_runs", {}).execute()
            status_msg = "cleanup_old_runs RPC executed"
        except Exception:
            status_msg = "cleanup_old_runs RPC not available or not exposed"
        return {"status": "success", "message": status_msg, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.exception("Cleanup task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}


@shared_task(name="src.tasks.retrain_model_task")
def retrain_model_task(force: bool = False) -> Dict[str, Any]:
    """
    Para MVP, se comporta como generate_forecast_task con horizonte 28 días.
    """
    try:
        logger.info("Starting retrain_model_task (MVP -> forecast 28d)")
        db = DataRepository()
        model = PharmaceuticalForecastModel()

        sales = db.get_sales_data()
        if sales.empty:
            return {"status": "no-data", "message": "No sales data", "timestamp": datetime.utcnow().isoformat()}

        forecasts_df, metrics_df, summary = model.train_and_forecast_all(
            sales_df=sales, skus=None, horizon_days=28, save_models=False
        )

        run_id = db.save_forecast_run(
            modelo="xgboost",
            version="1.0.0",
            horizonte_dias=28,
            ventana_entrenamiento_dias=getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
            parametros={"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
            skus_procesados=int(summary.get("total_skus", 0))
        )

        if not forecasts_df.empty:
            db.save_forecasts(run_id, forecasts_df)
        if not metrics_df.empty:
            db.save_metrics(run_id, metrics_df)

        db.update_forecast_run(
            run_id=run_id,
            exito=True,
            skus_procesados=int(summary.get("total_skus", 0)),
            metricas_globales={"avg_mape": summary.get("avg_mape")}
        )

        return {
            "status": "success",
            "run_id": run_id,
            "horizon": 28,
            "skus_processed": int(summary.get("total_skus", 0)),
            "avg_mape": summary.get("avg_mape"),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.exception("Retrain task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.utcnow().isoformat()}
