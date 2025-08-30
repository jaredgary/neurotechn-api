# src/api_extra.py
from __future__ import annotations

from typing import Optional, Dict, Any, List

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from src.database import get_db

router = APIRouter(tags=["extra"])


def _df_records(df: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


@router.get("/forecast/topn")
def api_topn_demand(
    h: int = Query(28, ge=7, le=28, description="Horizonte: 7, 14 o 28 días"),
    n: int = Query(10, ge=1, le=50, description="Top-N SKUs"),
):
    """
    Top-N por demanda acumulada a h días desde la vista v_demanda_futura_7_14_28.
    Devuelve UNA fila por SKU (sin duplicados diarios).
    """
    try:
        db = get_db()
        agg = db.get_future_demand_agg()  # columnas: sku, yhat_7d, yhat_14d, yhat_28d
        if agg.empty:
            return {"items": []}

        col = f"yhat_{h}d"
        if col not in agg.columns:
            raise HTTPException(status_code=400, detail=f"Horizonte no disponible: {col}")

        skus = db.get_active_skus()[["sku", "nombre_producto"]]
        out = (
            agg.merge(skus, on="sku", how="left")
               .sort_values(col, ascending=False)
               .head(n)[["sku", "nombre_producto", "yhat_7d", "yhat_14d", "yhat_28d"]]
        )
        return {"items": _df_records(out)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/summary")
def api_dashboard_summary():
    """
    Resumen mínimo para Dashboard:
      - KPIs de modelo (v_kpi_modelo)
      - Conteo de alertas abiertas por severidad (v_alert_counts)
      - SKUs procesados (conteo de v_demanda_futura_7_14_28)
      - Stockouts (conteo de v_riesgo_quiebre_7d donde riesgo=true)
    """
    try:
        db = get_db()

        # KPIs
        kpis = db.get_model_kpis() or {}

        # Alertas (vista)
        try:
            ac = (db.client.table("v_alert_counts").select("*").execute().data or [{}])[0]
            alerts_total = int(ac.get("total") or 0)
            alerts_breakdown = {
                "criticas": int(ac.get("criticas") or 0),
                "medias": int(ac.get("medias") or 0),
                "bajas": int(ac.get("bajas") or 0),
            }
        except Exception:
            alerts_total, alerts_breakdown = 0, {"criticas": 0, "medias": 0, "bajas": 0}

        # SKUs procesados (vista demanda agregada)
        try:
            skus_procesados = len(db.client.table("v_demanda_futura_7_14_28").select("sku").execute().data or [])
        except Exception:
            skus_procesados = 0

        # Stockouts (vista riesgo quiebre)
        try:
            stockouts_total = len(
                db.client.table("v_riesgo_quiebre_7d").select("sku").eq("riesgo", True).execute().data or []
            )
        except Exception:
            stockouts_total = 0

        return {
            "kpis": kpis,
            "alerts_total": alerts_total,
            "alerts_breakdown": alerts_breakdown,
            "stockouts_total": stockouts_total,
            "skus_procesados": skus_procesados,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
