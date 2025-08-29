from __future__ import annotations
import os
import uuid
from typing import Dict, List, Tuple

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException

from .db import fetch_df, execute, fetch_one
from .ml import build_features, backtest_metrics, fit_and_forecast_28d
from .alerts import generate_alert_rows, insert_alerts
from .schema import ForecastReq, ForecastResp, AckReq


load_dotenv()
CRON_SECRET = os.getenv("CRON_SECRET")

app = FastAPI(title="NeuroTecHN API", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/forecast", response_model=ForecastResp)
def forecast(req: ForecastReq, x_cron_secret: str = Header(None)):
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")

    ventas = fetch_df(
        """
        select fecha, sku, unidades_vendidas as y
        from public.ventas_diarias
        where fecha >= current_date - interval '90 days'
        order by sku, fecha;
    """
    )
    if ventas.empty:
        return ForecastResp(status="no-data")

    inv = fetch_df(
        """
        select fecha, sku, unidades_stock, stock_seguridad
        from public.inventario_diario
        where fecha = current_date;
    """
    )
    lotes = fetch_df(
        """
        select sku, lote_id, unidades, fecha_caducidad
        from public.lotes_caducidad
        where fecha_caducidad <= current_date + interval '90 days';
    """
    )

    feat = build_features(ventas)
    run_id = str(uuid.uuid4())
    skus = ventas["sku"].unique().tolist()

    # Registrar corrida
    execute(
        """
      insert into public.ejecuciones_modelo (run_id, modelo, version, horizonte_dias, ventana_entrenamiento_dias, parametros)
      values (%s,'xgboost','0.1.0',28,90,'{"lags":[1,7,14,28],"roll":[7,14,28]}')
    """,
        (run_id,),
    )

    metrics_rows = []
    forecast_rows: List[Tuple[str, str, pd.Timestamp, float]] = []

    for sku in skus:
        m = backtest_metrics(feat, sku)
        metrics_rows.append((run_id, sku, m["mape"], m["mae"], None, m["sesgo"]))
        items = fit_and_forecast_28d(feat, sku)
        for (fdate, yhat) in items:
            forecast_rows.append((run_id, sku, fdate, yhat))

    if metrics_rows:
        execute(
            """
          insert into public.metricas_backtesting (run_id, sku, mape, mae, smape, sesgo)
          values (%s,%s,%s,%s,%s,%s)
        """,
            metrics_rows,
            many=True,
        )

    if forecast_rows:
        execute(
            """
          insert into public.forecast_historico (run_id, sku, fecha_objetivo, unidades_pronosticadas)
          values (%s,%s,%s,%s)
          on conflict (run_id, sku, fecha_objetivo)
          do update set unidades_pronosticadas = excluded.unidades_pronosticadas
        """,
            forecast_rows,
            many=True,
        )

    # Alertas
    alerts = generate_alert_rows(inv, lotes, _to_map(forecast_rows))
    insert_alerts(alerts)

    return ForecastResp(status="ok", run_id=run_id, skus=len(skus))


def _to_map(forecast_rows):
    from collections import defaultdict

    d = defaultdict(list)
    for _, sku, fdate, yhat in forecast_rows:
        d[sku].append((fdate, float(yhat)))
    return d


@app.get("/alerts/open")
def open_alerts():
    df = fetch_df(
        """
      select a.*
      from public.alertas a
      where a.resuelta = false
      order by a.ts_creacion desc
      limit 200;
    """
    )
    return df.to_dict(orient="records")


@app.get("/kpi/model")
def kpi_model():
    row = fetch_one("select * from public.v_kpi_modelo;")
    if not row:
        return {}
    # columnas: run_id, ts_ejecucion, mape_prom, mae_prom, sesgo_prom
    return {
        "run_id": row[0],
        "ts_ejecucion": row[1],
        "mape_prom": float(row[2]),
        "mae_prom": float(row[3]),
        "sesgo_prom": float(row[4]),
    }


@app.post("/alerts/ack")
def ack_alert(req: AckReq):
    execute("select public.ack_alert(%s);", (req.id,))
    return {"status": "acknowledged", "id": req.id}

