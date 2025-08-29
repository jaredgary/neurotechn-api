def fit_and_forecast_28d(df_feat: pd.DataFrame, sku: str) -> List[Tuple[dt.date, float]]:
    data = df_feat[df_feat["sku"]==sku].dropna()
    if len(data) < 30:
        return []
    
    X = data.drop(columns=["y","fecha","sku"])
    y = data["y"].astype(float)
    
    # Validación de datos
    if y.sum() == 0:  # SKU sin ventas históricas
        return []
    
    model = XGBRegressor(
        n_estimators=600, learning_rate=0.05, max_depth=6,
        subsample=0.9, colsample_bytree=0.9, random_state=42
    )
    
    try:
        model.fit(X, y)
    except Exception as e:
        logger.warning(f"XGBoost fit failed for SKU {sku}: {e}")
        return []
    
    last_date = pd.to_datetime(data["fecha"].max()).date()
    tmp = data.copy()
    out = []
    
    for d in range(1, 29):
        target = last_date + dt.timedelta(days=d)
        row = tmp.iloc[-1:].drop(columns=["y","fecha","sku"])
        
        yhat = float(model.predict(row)[0])
        yhat = max(0.0, yhat)  # CRÍTICO: No forecasts negativos
        
        out.append((target, yhat))
        
        # Update rolling features para próximo día
        new = tmp.iloc[-1:].copy()
        new["fecha"] = pd.Timestamp(target)
        new["y"] = yhat
        tmp = pd.concat([tmp, new], ignore_index=True)
    
    return out
