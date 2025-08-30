"""
Celery tasks y utilidades de alertas para el MVP (estricto a RF-01/02/03)

Incluye:
- recompute_alerts(): genera alertas de QUIEBRE_STOCK y VENCIMIENTO.
- Tareas Celery que llaman a los flujos mínimos.

Dependencias: DataRepository (Supabase) y PharmaceuticalForecastModel (XGBoost).
"""

from __future__ import annotations

from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, timedelta, date, timezone
from typing import Dict, Any, List, Optional

import pandas as pd

from src.database import DataRepository
from src.forecasting.xgboost_model import PharmaceuticalForecastModel

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Utilidades de negocio (MVP)
# ---------------------------------------------------------------------------
def _evaluate_stock_risk(db: DataRepository) -> int:
    """
    Crea alertas de tipo QUIEBRE_STOCK usando:
      - v_demanda_futura_7_14_28  (yhat_7d, yhat_14d, yhat_28d)
      - v_inventario_latest        (unidades_stock)

    Severidad:
      - ALTA  si stock < yhat_7d
      - MEDIA si stock < yhat_14d
      - BAJA  si stock < yhat_28d
    """
    inv_df = db.get_current_inventory()        # sku, fecha, unidades_stock, stock_seguridad
    dem_df = db.get_future_demand_agg()        # sku, yhat_7d, yhat_14d, yhat_28d
    if inv_df.empty or dem_df.empty:
        return 0

    inv_df = inv_df[['sku', 'unidades_stock']].copy()
    merged = dem_df.merge(inv_df, on='sku', how='left')
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

        # Evitar duplicados abiertos para el mismo SKU/tipo/severidad
        exists = db.get_active_alerts(sku=sku, tipo_alerta="QUIEBRE_STOCK", severidad=severity)
        if not exists.empty:
            continue

        desc = (f"Riesgo de quiebre (sev={severity}). Stock={stock:.0f} vs "
                f"Demanda 7d={y7:.0f}, 14d={y14:.0f}, 28d={y28:.0f}.")
        if db.create_alert(sku=sku, tipo_alerta="QUIEBRE_STOCK", severidad=severity,
                           descripcion=desc, fecha_objetivo=date.today()):
            created += 1
    return created


def _evaluate_expiration_risk(db: DataRepository, days_ahead: int = 30) -> int:
    """
    Crea alertas de tipo VENCIMIENTO para lotes con fecha <= hoy+days_ahead.

    Severidad:
      - ALTA  si <= 7 días
      - MEDIA si <= 14 días
      - BAJA  si <= 30 días
    """
    lotes = db.get_expiring_batches(days_ahead=days_ahead)
    if lotes.empty:
        return 0

    # Tomamos por SKU el lote más próximo a vencer
    lotes = lotes.sort_values(['sku', 'fecha_caducidad'])
    first_per_sku = lotes.groupby('sku').head(1)

    created = 0
    for _, r in first_per_sku.iterrows():
        dias = int(r.get('dias_hasta_vencimiento', 30))
        sev = "ALTA" if dias <= 7 else ("MEDIA" if dias <= 14 else "BAJA")

        sku = r['sku']
        lote_id = r.get('lote_id')
        # Evitar duplicados por lote
        already = db.client.table("alertas").select("id").eq("resuelta", False).eq("lote_id", lote_id).execute().data or []
        if already:
            continue

        desc = f"Lote {lote_id} vence en {dias} días (sev={sev})."
        if db.create_alert(sku=sku, tipo_alerta="VENCIMIENTO", severidad=sev,
                           descripcion=desc,
                           fecha_objetivo=r['fecha_caducidad'].date() if pd.notna(r['fecha_caducidad']) else None,
                           lote_id=lote_id):
            created += 1
    return created


def recompute_alerts(max_days_expiry: int = 30) -> dict:
    """
    Recalcula alertas mínimas del MVP:
      - QUIEBRE_STOCK (según demanda futura vs stock actual)
      - VENCIMIENTO   (lotes <= max_days_expiry)
    """
    db = DataRepository()
    out = {"quiebre": 0, "vencimiento": 0}

    try:
        out["quiebre"] = _evaluate_stock_risk(db)
    except Exception as e:
        logger.exception(f"recompute_alerts.quiebre error: {e}")

    try:
        out["vencimiento"] = _evaluate_expiration_risk(db, days_ahead=max_days_expiry)
    except Exception as e:
        logger.exception(f"recompute_alerts.vencimiento error: {e}")

    logger.info(f"Alertas creadas: {out}")
    return out


# ---------------------------------------------------------------------------
# Tareas Celery (si tienes worker en Fly)
# ---------------------------------------------------------------------------
@shared_task(name="src.tasks.generate_forecast_task")
def generate_forecast_task() -> Dict[str, Any]:
    """Genera forecasts 7/14/28 y guarda resultados/metricas (RF-01)."""
    try:
        db = DataRepository()
        model = PharmaceuticalForecastModel()
        sales = db.get_sales_data()
        if sales.empty:
            return {"status": "no-data", "message": "No sales", "results": []}

        results: List[Dict[str, Any]] = []
        for horizon in [7, 14, 28]:
            f_df, m_df, summary = model.train_and_forecast_all(sales_df=sales, skus=None,
                                                               horizon_days=horizon, save_models=False)
            run_id = db.save_forecast_run("xgboost", "1.0.0", horizon,
                                          getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
                                          {"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
                                          skus_procesados=int(summary.get("total_skus", 0)))
            if not f_df.empty:
                db.save_forecasts(run_id, f_df)
            if not m_df.empty:
                db.save_metrics(run_id, m_df)
            db.update_forecast_run(run_id, True, int(summary.get("total_skus", 0)),
                                   {"avg_mape": summary.get("avg_mape")})
            results.append({"horizon": horizon, "run_id": run_id,
                            "skus_processed": int(summary.get("total_skus", 0)),
                            "avg_mape": summary.get("avg_mape"),
                            "timestamp": datetime.now(timezone.utc).isoformat()})

        # Recalcula alertas tras nuevos forecasts
        alerts = recompute_alerts()
        return {"status": "success", "results": results, "alerts": alerts,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("generate_forecast_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@shared_task(name="src.tasks.check_stock_alerts_task")
def check_stock_alerts_task() -> Dict[str, Any]:
    """Solo reevaluación de QUIEBRE_STOCK."""
    try:
        db = DataRepository()
        created = _evaluate_stock_risk(db)
        return {"status": "success", "alerts_created": int(created),
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("check_stock_alerts_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@shared_task(name="src.tasks.check_expiration_alerts_task")
def check_expiration_alerts_task(days_ahead: int = 30) -> Dict[str, Any]:
    """Solo reevaluación de VENCIMIENTO."""
    try:
        db = DataRepository()
        created = _evaluate_expiration_risk(db, days_ahead=days_ahead)
        return {"status": "success", "alerts_created": int(created),
                "checked_until": (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("check_expiration_alerts_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@shared_task(name="src.tasks.update_model_metrics_task")
def update_model_metrics_task() -> Dict[str, Any]:
    """Lee KPIs del último run (vista v_kpi_modelo)."""
    try:
        db = DataRepository()
        kpis = db.get_model_kpis()
        return {"status": "success", "metrics": kpis, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("update_model_metrics_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@shared_task(name="src.tasks.cleanup_old_data_task")
def cleanup_old_data_task() -> Dict[str, Any]:
    """Intenta ejecutar la RPC cleanup_old_runs() si está publicada."""
    try:
        db = DataRepository()
        try:
            db.client.rpc("cleanup_old_runs", {}).execute()
            msg = "cleanup_old_runs RPC executed"
        except Exception:
            msg = "cleanup_old_runs RPC not available"
        return {"status": "success", "message": msg, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("cleanup_old_data_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


@shared_task(name="src.tasks.retrain_model_task")
def retrain_model_task() -> Dict[str, Any]:
    """Re-entrenamiento minimalista -> forecast 28d."""
    try:
        db = DataRepository()
        model = PharmaceuticalForecastModel()
        sales = db.get_sales_data()
        if sales.empty:
            return {"status": "no-data", "message": "No sales",
                    "timestamp": datetime.now(timezone.utc).isoformat()}

        f_df, m_df, summary = model.train_and_forecast_all(sales_df=sales, skus=None,
                                                           horizon_days=28, save_models=False)
        run_id = db.save_forecast_run("xgboost", "1.0.0", 28,
                                      getattr(db.settings, "TRAINING_WINDOW_DAYS", 90),
                                      {"lags": [1, 7, 14, 28], "rolling": [7, 14, 28]},
                                      skus_procesados=int(summary.get("total_skus", 0)))
        if not f_df.empty:
            db.save_forecasts(run_id, f_df)
        if not m_df.empty:
            db.save_metrics(run_id, m_df)
        db.update_forecast_run(run_id, True, int(summary.get("total_skus", 0)),
                               {"avg_mape": summary.get("avg_mape")})

        # Recalcular alertas tras reentrenar
        alerts = recompute_alerts()
        return {"status": "success", "run_id": run_id, "alerts": alerts,
                "skus_processed": int(summary.get("total_skus", 0)),
                "avg_mape": summary.get("avg_mape"),
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.exception("retrain_model_task failed")
        return {"status": "error", "message": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
