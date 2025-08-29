from __future__ import annotations
import datetime as dt
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    # df: fecha, sku, y
    df = df.sort_values(["sku", "fecha"]).copy()
    for lag in (1, 7, 14, 28):
        df[f"lag_{lag}"] = df.groupby("sku")["y"].shift(lag)
    for win in (7, 14, 28):
        df[f"rollmean_{win}"] = (
            df.groupby("sku")["y"].shift(1).rolling(win).mean()
        )
        df[f"rollstd_{win}"] = (
            df.groupby("sku")["y"].shift(1).rolling(win).std()
        )
    df["dow"] = pd.to_datetime(df["fecha"]).dt.dayofweek
    return df


def backtest_metrics(df_feat: pd.DataFrame, sku: str) -> Dict[str, float]:
    data = df_feat[df_feat["sku"] == sku].dropna()
    if len(data) < 30:
        return {"mape": np.nan, "mae": np.nan, "sesgo": np.nan}
    X = data.drop(columns=["y", "fecha", "sku"])
    y = data["y"].astype(float)
    tscv = TimeSeriesSplit(n_splits=3)  # CV adecuada para series temporales
    preds, trues = [], []
    for tr_idx, te_idx in tscv.split(X):
        model = XGBRegressor(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
        )
        model.fit(
            X.iloc[tr_idx],
            y.iloc[tr_idx],
            eval_set=[(X.iloc[te_idx], y.iloc[te_idx])],
            verbose=False,
        )
        preds.extend(model.predict(X.iloc[te_idx]))
        trues.extend(y.iloc[te_idx].values)
    trues = np.array(trues)
    preds = np.array(preds)
    mae = float(mean_absolute_error(trues, preds))
    denom = np.clip(trues, 1e-6, None)
    mape = float(np.mean(np.abs((trues - preds) / denom)) * 100.0)
    sesgo = float(np.mean(preds - trues))
    return {"mape": mape, "mae": mae, "sesgo": sesgo}


def fit_and_forecast_28d(df_feat: pd.DataFrame, sku: str) -> List[Tuple[dt.date, float]]:
    data = df_feat[df_feat["sku"] == sku].dropna()
    if len(data) < 30:
        return []
    X = data.drop(columns=["y", "fecha", "sku"])
    y = data["y"].astype(float)
    model = XGBRegressor(
        n_estimators=600,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
    )
    model.fit(X, y)
    last_date = pd.to_datetime(data["fecha"].max()).date()
    tmp = data.copy()
    out: List[Tuple[dt.date, float]] = []
    for d in range(1, 29):
        target = last_date + dt.timedelta(days=d)
        row = tmp.iloc[-1:].drop(columns=["y", "fecha", "sku"])
        yhat = float(model.predict(row)[0])
        out.append((target, yhat))
        new = tmp.iloc[-1:].copy()
        new["fecha"] = pd.Timestamp(target)
        new["y"] = yhat
        tmp = pd.concat([tmp, new], ignore_index=True)
    return out

