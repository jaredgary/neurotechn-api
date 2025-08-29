from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, conlist

SERVICE_NAME = "NeuroTecHN API"
API_VERSION = "0.1.0"


# -------- Lazy imports to avoid hard failures on module import --------

def _pd():  # noqa: D401
    import pandas as pd  # type: ignore
    return pd


def _np():  # noqa: D401
    import numpy as np  # type: ignore
    return np


def _XGBRegressor():  # noqa: D401
    from xgboost import XGBRegressor  # type: ignore
    return XGBRegressor


def _mean_absolute_error():  # noqa: D401
    from sklearn.metrics import mean_absolute_error  # type: ignore
    return mean_absolute_error


try:
    # supabase-py v2
    from supabase import Client, create_client  # type: ignore
except Exception:  # pragma: no cover
    Client = Any  # type: ignore

    def create_client(url: str, key: str) -> Any:  # type: ignore
        raise RuntimeError("Supabase client not available. Install 'supabase'.")


# -------- Logging with secret redaction --------
class SecretsRedactor(logging.Filter):
    def __init__(self, secrets: List[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = str(record.getMessage())
            for secret in self._secrets:
                if secret and secret in msg:
                    msg = msg.replace(secret, "***REDACTED***")
            record.msg = msg
        except Exception:
            pass
        return True


def configure_logger() -> logging.Logger:
    load_dotenv(override=False)
    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    redactor = SecretsRedactor([
        os.getenv("SUPABASE_SERVICE_KEY", ""),
        os.getenv("CRON_TOKEN", ""),
    ])
    handler.addFilter(redactor)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


logger = configure_logger()


# -------- Env & client helpers --------

def get_env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    load_dotenv(override=False)
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise HTTPException(status_code=500, detail=f"Missing required env var: {name}")
    return value or ""


def parse_horizons(env_value: str) -> List[int]:
    if not env_value:
        return [14]
    try:
        return [int(x.strip()) for x in env_value.split(",") if x.strip()]
    except Exception:
        return [14]


def get_client() -> Client:
    url = get_env("SUPABASE_URL", required=True)
    key = get_env("SUPABASE_SERVICE_KEY", required=True)
    try:
        client = create_client(url, key)
        return client
    except Exception as exc:
        logger.error("Failed to create Supabase client: %s", exc)
        raise HTTPException(status_code=500, detail="supabase_client_error")


# -------- Pydantic schemas --------

class TrainRequest(BaseModel):
    horizontes: Optional[conlist(int, min_items=1)] = Field(default=None)


class MetricasHorizonte(BaseModel):
    mape: Optional[float]
    smape: float
    mae: float
    sesgo: float


class TrainResponse(BaseModel):
    run_id: str
    metricas: Dict[str, MetricasHorizonte]
    skus_entrenados: int


class ForecastRequest(BaseModel):
    horizonte: Optional[int] = Field(default=None)


class ForecastResponse(BaseModel):
    run_id: str
    pronosticos_insertados: int
    alertas_creadas: int


# -------- Data access --------

from typing import Iterable


def fetch_data(client: Client) -> Dict[str, Any]:
    pd = _pd()
    today_utc = datetime.now(timezone.utc).date()
    start_date = today_utc - timedelta(days=90)

    def to_df(records: List[Dict[str, Any]]) -> Any:
        return pd.DataFrame.from_records(records or [])

    try:
        ventas = client.table("ventas_diarias").select("*").gte("fecha", str(start_date)).execute().data  # type: ignore[attr-defined]
        inventario = client.table("inventario_diario").select("*").execute().data  # type: ignore[attr-defined]
        sku_atc = client.table("sku_atc").select("*").execute().data  # type: ignore[attr-defined]
        lotes = client.table("lotes_caducidad").select("*").gte("fecha_caducidad", str(today_utc - timedelta(days=180))).execute().data  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("DB fetch error: %s", exc)
        raise HTTPException(status_code=500, detail="db_fetch_error")

    ventas_df = to_df(ventas)
    inventario_df = to_df(inventario)
    sku_atc_df = to_df(sku_atc)
    lotes_df = to_df(lotes)

    if not ventas_df.empty:
        ventas_df["fecha"] = pd.to_datetime(ventas_df["fecha"]).dt.tz_localize(None).dt.date
        if "unidades" not in ventas_df.columns:
            candidate = next((c for c in ["cantidad", "qty", "units"] if c in ventas_df.columns), None)
            ventas_df["unidades"] = ventas_df.get(candidate, 0)
    if not inventario_df.empty:
        inventario_df["fecha"] = pd.to_datetime(inventario_df["fecha"]).dt.tz_localize(None).dt.date
    if not lotes_df.empty:
        lotes_df["fecha_caducidad"] = pd.to_datetime(lotes_df["fecha_caducidad"]).dt.tz_localize(None).dt.date

    return {
        "ventas_diarias": ventas_df,
        "inventario_diario": inventario_df,
        "sku_atc": sku_atc_df,
        "lotes_caducidad": lotes_df,
    }


# -------- Feature engineering --------


def _week_of_month(dt: date) -> int:
    first_day = dt.replace(day=1)
    return (dt.day + first_day.weekday()) // 7 + 1


def feature_engineering(ventas: Any) -> Any:
    pd = _pd()
    if ventas.empty:
        return ventas
    df = ventas.copy()
    if "fecha" not in df:
        raise HTTPException(status_code=400, detail="ventas_missing_fecha")
    if "sku_id" not in df:
        raise HTTPException(status_code=400, detail="ventas_missing_sku_id")
    if "unidades" not in df:
        df["unidades"] = 0

    df["fecha"] = pd.to_datetime(df["fecha"]).dt.tz_localize(None).dt.date
    df["dow"] = pd.to_datetime(df["fecha"]).dt.dayofweek
    df["day_of_year"] = pd.to_datetime(df["fecha"]).dt.day_of_year
    df["week_of_month"] = pd.to_datetime(df["fecha"]).dt.date.map(_week_of_month)

    if "promo_flag" not in df:
        df["promo_flag"] = 0
    if "canal" in df:
        canal_dummies = pd.get_dummies(df["canal"], prefix="canal")
        df = pd.concat([df.drop(columns=["canal"]), canal_dummies], axis=1)

    df = df.sort_values(["sku_id", "fecha"])  # type: ignore[index]
    df["lag_1"] = df.groupby("sku_id")["unidades"].shift(1)
    df["lag_7"] = df.groupby("sku_id")["unidades"].shift(7)
    df["roll_mean_7"] = df.groupby("sku_id")["unidades"].rolling(window=7, min_periods=1).mean().reset_index(level=0, drop=True)
    df["roll_mean_14"] = df.groupby("sku_id")["unidades"].rolling(window=14, min_periods=1).mean().reset_index(level=0, drop=True)

    df[["lag_1", "lag_7", "roll_mean_7", "roll_mean_14"]] = df[["lag_1", "lag_7", "roll_mean_7", "roll_mean_14"]].fillna(0.0)
    return df


# -------- Segmentation --------


def segment_skus(ventas_90d: Any, sku_atc: Any) -> Tuple[set, Dict[str, str]]:
    dense_threshold = 50
    totals = ventas_90d.groupby("sku_id")["unidades"].sum()
    dense_skus: set = set(totals[totals >= dense_threshold].index.astype(str))
    sku_to_atc: Dict[str, str] = {}
    if not sku_atc.empty:
        if "sku_id" in sku_atc.columns and "atc" in sku_atc.columns:
            sku_to_atc = {str(r["sku_id"]): str(r["atc"]) for _, r in sku_atc.iterrows()}
        else:
            atc_col = next((c for c in sku_atc.columns if c.lower().startswith("atc")), None)
            if atc_col and "sku_id" in sku_atc.columns:
                sku_to_atc = {str(r["sku_id"]): str(r[atc_col]) for _, r in sku_atc.iterrows()}
    return dense_skus, sku_to_atc


# -------- Model training & CV --------


def _smape(y_true: Any, y_pred: Any) -> float:
    np = _np()
    denom = (np.abs(y_true) + np.abs(y_pred))
    return float(np.mean(2.0 * np.abs(y_pred - y_true) / np.where(denom == 0, 1.0, denom)))


def _mape_safe(y_true: Any, y_pred: Any) -> Optional[float]:
    np = _np()
    mask = y_true > 0
    if not np.any(mask):
        return None
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def tscv_evaluate(df_feat: Any, horizons: List[int]) -> Dict[int, MetricasHorizonte]:
    XGBRegressor = _XGBRegressor()
    mean_absolute_error = _mean_absolute_error()
    if df_feat.empty:
        return {h: MetricasHorizonte(mape=None, smape=0.0, mae=0.0, sesgo=0.0) for h in horizons}

    features = [c for c in df_feat.columns if c not in {"unidades", "fecha", "sku_id"}]
    metrics: Dict[int, MetricasHorizonte] = {}

    results_by_h: Dict[int, List[Tuple[Any, Any]]] = {h: [] for h in horizons}
    for _, g in df_feat.groupby("sku_id"):
        g = g.sort_values("fecha")
        y = g["unidades"].values.astype(float)
        X = g[features].values.astype(float)
        n = len(g)
        min_train = max(21, int(n * 0.5))
        for h in horizons:
            folds = 0
            step = max(1, (n - h - min_train) // 3 or 1)
            for split in range(min_train, n - h, step):
                X_train, y_train = X[:split], y[:split]
                X_test, y_test = X[split: split + h], y[split: split + h]
                if len(X_test) < h or len(X_train) < 10:
                    continue
                model = XGBRegressor(
                    n_estimators=200,
                    max_depth=6,
                    learning_rate=0.1,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    reg_alpha=0.0,
                    reg_lambda=1.0,
                    objective="reg:squarederror",
                    n_jobs=2,
                    random_state=42,
                )
                model.fit(X_train, y_train)
                y_pred = model.predict(X_test)
                results_by_h[h].append((y_test, y_pred))
                folds += 1
            if folds == 0:
                continue

    for h, pairs in results_by_h.items():
        if not pairs:
            metrics[h] = MetricasHorizonte(mape=None, smape=0.0, mae=0.0, sesgo=0.0)
            continue
        y_true = _np().concatenate([p[0] for p in pairs])
        y_pred = _np().concatenate([p[1] for p in pairs])
        mae = float(mean_absolute_error(y_true, y_pred))
        smape = _smape(y_true, y_pred)
        mape = _mape_safe(y_true, y_pred)
        sesgo = float(_np().mean(y_pred - y_true))
        metrics[h] = MetricasHorizonte(mape=mape, smape=smape, mae=mae, sesgo=sesgo)

    return metrics


def train_model(df_feat: Any) -> Any:
    XGBRegressor = _XGBRegressor()
    if df_feat.empty:
        raise HTTPException(status_code=400, detail="no_data_for_training")
    features = [c for c in df_feat.columns if c not in {"unidades", "fecha", "sku_id"}]
    X = df_feat[features].values
    y = df_feat["unidades"].values
    model = XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.0,
        reg_lambda=1.0,
        objective="reg:squarederror",
        n_jobs=2,
        random_state=42,
    )
    model.fit(X, y)
    return model


# -------- Forecast helpers --------


def _build_future_features(history: Any, horizon: int) -> Any:
    pd = _pd()
    if history.empty:
        return history
    last_date = pd.to_datetime(history["fecha"]).max().date()
    all_rows: List[Dict[str, Any]] = []
    for sku, g in history.groupby("sku_id"):
        g = g.sort_values("fecha").copy()
        lag_buffer = list(g["unidades"].values.astype(float))
        for step in range(1, horizon + 1):
            target_date = last_date + timedelta(days=step)
            lag_1 = lag_buffer[-1] if lag_buffer else 0.0
            lag_7 = lag_buffer[-7] if len(lag_buffer) >= 7 else (lag_buffer[0] if lag_buffer else 0.0)
            roll_mean_7 = float(pd.Series(lag_buffer[-7:]).mean()) if lag_buffer else 0.0
            roll_mean_14 = float(pd.Series(lag_buffer[-14:]).mean()) if lag_buffer else 0.0
            row = {
                "sku_id": sku,
                "fecha": target_date,
                "dow": target_date.weekday(),
                "day_of_year": int(datetime(target_date.year, target_date.month, target_date.day).strftime("%j")),
                "week_of_month": _week_of_month(target_date),
                "promo_flag": 0,
                "lag_1": lag_1,
                "lag_7": lag_7,
                "roll_mean_7": roll_mean_7,
                "roll_mean_14": roll_mean_14,
            }
            for c in history.columns:
                if str(c).startswith("canal_"):
                    row[c] = int(history[c].iloc[-1])
            all_rows.append(row)
    future_df = pd.DataFrame(all_rows)
    return future_df


def forecast_horizon(model: Any, df_feat: Any, horizon: int) -> Any:
    pd = _pd()
    np = _np()
    if df_feat.empty:
        return pd.DataFrame(columns=["sku_id", "fecha_objetivo", "pronostico"])
    future = _build_future_features(df_feat, horizon)
    feature_cols = [c for c in future.columns if c not in {"fecha", "sku_id"}]
    preds = model.predict(future[feature_cols].values)
    preds = np.clip(preds, a_min=0.0, a_max=None)
    out = future[["sku_id", "fecha"]].copy()
    out.rename(columns={"fecha": "fecha_objetivo"}, inplace=True)
    out["pronostico"] = preds
    return out


# -------- Persistence --------


def persist_forecasts(client: Client, run_id: str, df: Any) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["run_id"] = run_id
    records = df.to_dict(orient="records")
    inserted = 0
    chunk = 1000
    for i in range(0, len(records), chunk):
        batch = records[i : i + chunk]
        try:
            client.table("forecast_historico").upsert(batch, on_conflict="run_id,sku_id,fecha_objetivo").execute()  # type: ignore[attr-defined]
            inserted += len(batch)
        except Exception as exc:
            logger.error("persist_forecasts error: %s", exc)
            raise HTTPException(status_code=500, detail="db_persist_forecasts_error")
    return inserted


# -------- Alerts --------


def compute_alerts(
    forecasts_by_h: Dict[int, Any],
    inventario: Any,
    sku_atc: Any,
    lotes: Any,
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()

    if not inventario.empty:
        inventario_sorted = inventario.sort_values(["sku_id", "fecha"])  # type: ignore[index]
        latest = inventario_sorted.groupby("sku_id").tail(1)
        stock_actual = {str(r["sku_id"]): float(r.get("stock", r.get("cantidad", 0.0))) for _, r in latest.iterrows()}
    else:
        stock_actual = {}

    lead_time_map: Dict[str, int] = {}
    safety_stock_map: Dict[str, float] = {}
    if not sku_atc.empty:
        for _, r in sku_atc.iterrows():
            sku = str(r.get("sku_id"))
            lead_time_map[sku] = int(r.get("lead_time_dias", 7) or 7)
            safety_stock_map[sku] = float(r.get("stock_seguridad", 0.0) or 0.0)

    for _, dfh in forecasts_by_h.items():
        if dfh.empty:
            continue
        dfh = dfh.copy()
        for sku, g in dfh.groupby("sku_id"):
            sku = str(sku)
            demand_cumsum = g.sort_values("fecha_objetivo")["pronostico"].cumsum()
            stock = stock_actual.get(sku, 0.0)
            safety = safety_stock_map.get(sku, 0.0)
            lead = lead_time_map.get(sku, 7)
            for idx, (fecha_obj, cumd) in enumerate(zip(g.sort_values("fecha_objetivo")["fecha_objetivo"], demand_cumsum), start=1):
                projected = stock - float(cumd)
                if projected < safety:
                    if idx <= lead:
                        severity = "ALTA"
                    elif idx <= 2 * lead:
                        severity = "MEDIA"
                    else:
                        severity = "BAJA"
                    alerts.append({
                        "tipo": "QUIEBRE_STOCK",
                        "sku_id": sku,
                        "fecha_objetivo": fecha_obj,
                        "severidad": severity,
                        "horizonte_dias": idx,
                    })
                    break

    if not lotes.empty:
        for _, r in lotes.iterrows():
            sku = str(r.get("sku_id"))
            fecha_cad = r.get("fecha_caducidad")
            if not isinstance(fecha_cad, (datetime, date)):
                continue
            fecha_cad = fecha_cad.date() if isinstance(fecha_cad, datetime) else fecha_cad
            days = (fecha_cad - today).days
            if days <= 30:
                if days <= 7:
                    severity = "ALTA"
                elif days <= 14:
                    severity = "MEDIA"
                else:
                    severity = "BAJA"
                alerts.append({
                    "tipo": "VENCIMIENTO",
                    "sku_id": sku,
                    "lote_id": r.get("lote_id"),
                    "fecha_objetivo": fecha_cad,
                    "severidad": severity,
                })

    return alerts


def persist_alerts(client: Client, run_id: str, alerts: List[Dict[str, Any]]) -> int:
    if not alerts:
        return 0
    rows = []
    for a in alerts:
        row = dict(a)
        row["run_id"] = run_id
        rows.append(row)
    inserted = 0
    chunk = 1000
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        try:
            client.table("alertas").upsert(batch, on_conflict="run_id,sku_id,fecha_objetivo,tipo,lote_id").execute()  # type: ignore[attr-defined]
            inserted += len(batch)
        except Exception as exc:
            logger.error("persist_alerts error: %s", exc)
            raise HTTPException(status_code=500, detail="db_persist_alerts_error")
    return inserted


# -------- FastAPI app --------

app = FastAPI(title=SERVICE_NAME, version=API_VERSION)


@app.get("/")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


def _insert_ejecucion(client: Client, kind: str, run_id: str, horizonte: Optional[int]) -> None:
    try:
        payload = {
            "run_id": run_id,
            "tipo": kind,
            "horizonte_dias": horizonte,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        client.table("ejecuciones_modelo").insert(payload).execute()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("insert ejecuciones_modelo error: %s", exc)
        raise HTTPException(status_code=500, detail="db_insert_ejecuciones_error")


@app.post("/train", response_model=TrainResponse)
def train_endpoint(body: TrainRequest = Body(default=None)) -> TrainResponse:
    client = get_client()
    run_id = str(uuid.uuid4())
    _insert_ejecucion(client, kind="train", run_id=run_id, horizonte=None)

    data = fetch_data(client)
    ventas = data["ventas_diarias"]
    if ventas.empty or ventas["fecha"].nunique() < 90:
        logger.warning("Insufficient sales history for training (need >=90 days)")
    df_feat = feature_engineering(ventas)

    env_h = parse_horizons(get_env("FORECAST_HORIZONS", default="7,14,28"))
    req_h = body.horizontes if body and body.horizontes else None
    horizons = sorted(set(req_h or env_h))

    metrics_by_h = tscv_evaluate(df_feat, horizons)

    model = train_model(df_feat)
    try:
        model.save_model("model.json")
    except Exception as exc:
        logger.error("Model persistence failed: %s", exc)
        raise HTTPException(status_code=400, detail="modelo no persistido (MVP)")

    metricas_out = {str(h): metrics_by_h[h] for h in horizons}
    skus_entrenados = int(df_feat["sku_id"].nunique()) if not df_feat.empty else 0
    try:
        rows = []
        for h in horizons:
            m = metrics_by_h[h]
            rows.append({
                "run_id": run_id,
                "horizonte_dias": h,
                "mape": m.mape,
                "smape": m.smape,
                "mae": m.mae,
                "sesgo": m.sesgo,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        if rows:
            client.table("metricas_backtesting").insert(rows).execute()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("Persist metricas_backtesting error: %s", exc)

    return TrainResponse(run_id=run_id, metricas=metricas_out, skus_entrenados=skus_entrenados)


def _authorize_cron(auth_header: Optional[str]) -> None:
    allow_insecure = get_env("ALLOW_INSECURE_CRON", default="false").lower() == "true"
    if allow_insecure:
        return
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer")
    token = auth_header.split(" ", 1)[1].strip()
    if token != get_env("CRON_TOKEN", required=True):
        raise HTTPException(status_code=401, detail="invalid_token")


@app.post("/forecast", response_model=ForecastResponse)
def forecast_endpoint(
    body: ForecastRequest = Body(default=None),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> ForecastResponse:
    _authorize_cron(authorization)
    client = get_client()
    requested_h = body.horizonte if body and body.horizonte else None
    env_h = parse_horizons(get_env("FORECAST_HORIZONS", default="7,14,28"))
    horizons = sorted(set([requested_h] if requested_h else env_h))

    run_id = str(uuid.uuid4())
    _insert_ejecucion(client, kind="forecast", run_id=run_id, horizonte=max(horizons) if horizons else None)

    data = fetch_data(client)
    ventas = data["ventas_diarias"]
    inventario = data["inventario_diario"]
    sku_atc = data["sku_atc"]
    lotes = data["lotes_caducidad"]

    df_feat = feature_engineering(ventas)
    if not os.path.exists("model.json"):
        raise HTTPException(status_code=412, detail="modelo no disponible, ejecute /train")
    model = _XGBRegressor()()
    model.load_model("model.json")

    dense_skus, sku_to_atc = segment_skus(ventas_90d=ventas, sku_atc=sku_atc)

    forecasts_by_h: Dict[int, Any] = {}
    for h in horizons:
        f_df = forecast_horizon(model, df_feat, h)
        if sku_to_atc:
            pd = _pd()
            ventas_last_28 = ventas.copy()
            start_28 = (datetime.now(timezone.utc).date() - timedelta(days=28))
            ventas_last_28 = ventas_last_28[ventas_last_28["fecha"] >= start_28] if not ventas.empty else pd.DataFrame(columns=["sku_id", "unidades"])  # type: ignore[index]

            ventas_last_28 = ventas_last_28.copy()
            ventas_last_28["atc"] = ventas_last_28["sku_id"].map(lambda s: sku_to_atc.get(str(s), ""))
            shares_series = ventas_last_28.groupby(["sku_id", "atc"])['unidades'].sum()
            share_map: Dict[Tuple[str, str], float] = {}
            if isinstance(shares_series, pd.Series):
                total_by_atc: Dict[str, float] = {}
                for (sku, atc), val in shares_series.items():
                    total_by_atc[atc] = total_by_atc.get(atc, 0.0) + float(val)
                for (sku, atc), val in shares_series.items():
                    denom = total_by_atc.get(atc, 0.0)
                    share_map[(str(sku), str(atc))] = float(val) / denom if denom > 0 else 0.0

            f_df = f_df.copy()
            f_df["atc"] = f_df["sku_id"].map(lambda s: sku_to_atc.get(str(s), ""))
            atc_forecast = f_df.groupby(["atc", "fecha_objetivo"], dropna=False)["pronostico"].sum().reset_index()

            def distribute(row: Any) -> float:
                sku = str(row["sku_id"])  # type: ignore[index]
                if sku in dense_skus:
                    return float(row["pronostico"])  # keep own prediction
                atc = sku_to_atc.get(sku, "")
                total_atc = float(atc_forecast.loc[(atc_forecast["atc"] == atc) & (atc_forecast["fecha_objetivo"] == row["fecha_objetivo"]), "pronostico"].sum())
                share = share_map.get((sku, atc), 0.0)
                if share == 0.0:
                    members = [s for s, a in sku_to_atc.items() if a == atc]
                    share = 1.0 / max(1, len(members))
                return total_atc * share

            f_df["pronostico"] = f_df.apply(distribute, axis=1)

        forecasts_by_h[h] = f_df[["sku_id", "fecha_objetivo", "pronostico"]]

    inserted_total = 0
    for _, dfh in forecasts_by_h.items():
        inserted_total += persist_forecasts(client, run_id, dfh)

    alerts = compute_alerts(forecasts_by_h, inventario, sku_atc, lotes)
    alerts_created = persist_alerts(client, run_id, alerts)

    return ForecastResponse(run_id=run_id, pronosticos_insertados=inserted_total, alertas_creadas=alerts_created)
