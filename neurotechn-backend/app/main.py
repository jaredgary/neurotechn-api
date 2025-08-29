import logging
import os
import uuid
from typing import Dict, Any
import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CRON_SECRET = os.getenv("CRON_SECRET")
if not CRON_SECRET:
    logger.warning("CRON_SECRET not set - cron endpoint will be insecure")

app = FastAPI(title="NeuroTecHN Pharmacy API", version="1.0.0")

# CORS para frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod: especificar dominios
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    try:
        # Test DB connection
        result = fetch_one("SELECT 1")
        return {
            "status": "healthy",
            "database": "connected" if result else "disconnected",
            "timestamp": pd.Timestamp.now().isoformat()
        }
    except:
        return {"status": "degraded", "database": "error"}

@app.post("/forecast", response_model=ForecastResp)
def forecast(req: ForecastReq, x_cron_secret: str = Header(None)):
    # Validación de autorización
    if not CRON_SECRET:
        logger.warning("Cron endpoint called but CRON_SECRET not configured")
    elif x_cron_secret != CRON_SECRET:
        logger.warning(f"Invalid cron secret attempted: {x_cron_secret}")
        raise HTTPException(401, "Invalid cron secret")
    
    logger.info("Starting forecast generation...")
    
    try:
        # Datos con validación
        ventas = fetch_df("""
            SELECT fecha, sku, unidades_vendidas as y
            FROM public.ventas_diarias
            WHERE fecha >= current_date - interval '90 days'
              AND unidades_vendidas >= 0
            ORDER BY sku, fecha
        """)
        
        if ventas.empty:
            logger.warning("No sales data found for forecast")
            return ForecastResp(status="no-data")
        
        logger.info(f"Processing {len(ventas)} sales records for {ventas['sku'].nunique()} SKUs")
        
        inv = fetch_df("""
            SELECT sku, unidades_stock, stock_seguridad
            FROM public.inventario_diario
            WHERE fecha = current_date
              AND unidades_stock >= 0
        """)
        
        lotes = fetch_df("""
            SELECT sku, lote_id, unidades, fecha_caducidad
            FROM public.lotes_caducidad
            WHERE fecha_caducidad BETWEEN current_date AND current_date + interval '90 days'
              AND unidades > 0
        """)
        
        # Machine Learning
        feat = build_features(ventas)
        if feat.empty:
            return ForecastResp(status="feature-error")
        
        run_id = str(uuid.uuid4())
        skus = ventas["sku"].unique().tolist()
        
        # Registrar ejecución
        execute("""
            INSERT INTO public.ejecuciones_modelo 
            (run_id, modelo, version, horizonte_dias, ventana_entrenamiento_dias, parametros)
            VALUES (%s, 'xgboost', '1.0.0', 28, 90, %s)
        """, (run_id, '{"method":"TimeSeriesSplit","lags":[1,7,14,28],"features":"engineered"}'))
        
        metrics_rows = []
        forecast_rows = []
        successful_skus = 0
        
        for sku in skus:
            try:
                # Métricas de backtesting
                m = backtest_metrics(feat, sku)
                if not any(np.isnan(list(m.values()))):
                    metrics_rows.append((run_id, sku, m["mape"], m["mae"], None, m["sesgo"]))
                
                # Pronóstico
                forecasts = fit_and_forecast_28d(feat, sku)
                if forecasts:
                    for (fdate, yhat) in forecasts:
                        forecast_rows.append((run_id, sku, fdate, yhat))
                    successful_skus += 1
                    
            except Exception as e:
                logger.error(f"Failed processing SKU {sku}: {e}")
                continue
        
        # Insertar resultados
        if metrics_rows:
            execute("""
                INSERT INTO public.metricas_backtesting 
                (run_id, sku, mape, mae, smape, sesgo)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, metrics_rows, many=True)
        
        if forecast_rows:
            execute("""
                INSERT INTO public.forecast_historico 
                (run_id, sku, fecha_objetivo, unidades_pronosticadas)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (run_id, sku, fecha_objetivo)
                DO UPDATE SET unidades_pronosticadas = EXCLUDED.unidades_pronosticadas
            """, forecast_rows, many=True)
        
        # Generar alertas
        try:
            forecasts_map = _to_map(forecast_rows)
            alerts = generate_alert_rows(inv, lotes, forecasts_map)
            insert_alerts(alerts)
            logger.info(f"Generated {len(alerts)} alerts")
        except Exception as e:
            logger.error(f"Alert generation failed: {e}")
        
        logger.info(f"Forecast completed: {successful_skus}/{len(skus)} SKUs processed")
        
        return ForecastResp(
            status="success", 
            run_id=run_id, 
            skus=successful_skus
        )
        
    except Exception as e:
        logger.error(f"Forecast endpoint failed: {e}")
        raise HTTPException(500, f"Internal error: {str(e)}")

# Resto de endpoints sin cambios...
def _to_map(forecast_rows):
    from collections import defaultdict
    d = defaultdict(list)
    for _, sku, fdate, yhat in forecast_rows:
        d[sku].append((fdate, float(yhat)))
    return d
