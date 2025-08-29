"""
Modelo XGBoost para pronóstico de demanda farmacéutica
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta, date
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib
from loguru import logger
import warnings
warnings.filterwarnings('ignore')

from config import get_settings, XGBOOST_PARAMS, FEATURE_CONFIG


class PharmaceuticalForecastModel:
    """Modelo XGBoost optimizado para pronóstico farmacéutico"""
    
    def __init__(self):
        self.settings = get_settings()
        self.model = None
        self.feature_columns = []
        self.scaler = None
        self.metrics = {}
        
    def create_features(self, df: pd.DataFrame, target_col: str = 'unidades_vendidas') -> pd.DataFrame:
        """
        Crear features para el modelo
        
        Args:
            df: DataFrame con columnas ['fecha', 'sku', target_col, ...]
            target_col: Columna objetivo
        
        Returns:
            DataFrame con features
        """
        df = df.copy()
        df = df.sort_values('fecha')
        
        # Ensure datetime
        df['fecha'] = pd.to_datetime(df['fecha'])
        
        # Calendar features
        df['day_of_week'] = df['fecha'].dt.dayofweek
        df['day_of_month'] = df['fecha'].dt.day
        df['week_of_year'] = df['fecha'].dt.isocalendar().week
        df['month'] = df['fecha'].dt.month
        df['quarter'] = df['fecha'].dt.quarter
        df['is_weekend'] = (df['fecha'].dt.dayofweek >= 5).astype(int)
        df['is_month_start'] = df['fecha'].dt.is_month_start.astype(int)
        df['is_month_end'] = df['fecha'].dt.is_month_end.astype(int)
        
        # Lag features
        for lag in FEATURE_CONFIG['lag_features']:
            df[f'lag_{lag}'] = df.groupby('sku')[target_col].shift(lag)
        
        # Rolling statistics
        for window in FEATURE_CONFIG['rolling_windows']:
            df[f'rolling_mean_{window}'] = df.groupby('sku')[target_col]\
                .transform(lambda x: x.rolling(window, min_periods=1).mean())
            df[f'rolling_std_{window}'] = df.groupby('sku')[target_col]\
                .transform(lambda x: x.rolling(window, min_periods=1).std())
            df[f'rolling_min_{window}'] = df.groupby('sku')[target_col]\
                .transform(lambda x: x.rolling(window, min_periods=1).min())
            df[f'rolling_max_{window}'] = df.groupby('sku')[target_col]\
                .transform(lambda x: x.rolling(window, min_periods=1).max())
        
        # Exponential weighted moving average
        df['ewm_mean'] = df.groupby('sku')[target_col]\
            .transform(lambda x: x.ewm(span=7, adjust=False).mean())
        
        # Trend features
        df['days_since_start'] = (df['fecha'] - df['fecha'].min()).dt.days
        
        # Promotional features (if available)
        if 'promo_flag' in df.columns:
            df['promo_lag_1'] = df.groupby('sku')['promo_flag'].shift(1)
            df['promo_next_1'] = df.groupby('sku')['promo_flag'].shift(-1)
            df['promo_rolling_mean'] = df.groupby('sku')['promo_flag']\
                .transform(lambda x: x.rolling(7, min_periods=1).mean())
        
        # Stock features (if available)
        if 'unidades_stock' in df.columns:
            df['stock_ratio'] = df[target_col] / (df['unidades_stock'] + 1)
            df['stock_lag_1'] = df.groupby('sku')['unidades_stock'].shift(1)
        
        # Handle missing values
        df = df.fillna(method='ffill').fillna(0)
        
        # Remove infinite values
        df = df.replace([np.inf, -np.inf], 0)
        
        return df
    
    def calculate_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """Calcular métricas de evaluación"""
        
        # Avoid division by zero
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        
        # Basic metrics
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        
        # MAPE (Mean Absolute Percentage Error)
        mask = y_true != 0
        if mask.sum() > 0:
            mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100
        else:
            mape = np.nan
        
        # SMAPE (Symmetric MAPE)
        denominator = (np.abs(y_true) + np.abs(y_pred)) / 2
        mask = denominator != 0
        if mask.sum() > 0:
            smape = np.mean(np.abs(y_true[mask] - y_pred[mask]) / denominator[mask]) * 100
        else:
            smape = np.nan
        
        # Bias
        bias = np.mean(y_pred - y_true)
        
        # R2 Score
        if len(y_true) > 1 and y_true.std() > 0:
            r2 = r2_score(y_true, y_pred)
        else:
            r2 = np.nan
        
        return {
            'mae': round(mae, 2),
            'rmse': round(rmse, 2),
            'mape': round(mape, 2) if not np.isnan(mape) else None,
            'smape': round(smape, 2) if not np.isnan(smape) else None,
            'sesgo': round(bias, 2),
            'r2_score': round(r2, 4) if not np.isnan(r2) else None,
            'n_observaciones': len(y_true)
        }
    
    def train_single_sku(
        self,
        df: pd.DataFrame,
        sku: str,
        target_col: str = 'unidades_vendidas',
        test_size: int = 7
    ) -> Tuple[Optional[xgb.XGBRegressor], Dict[str, Any]]:
        """
        Entrenar modelo para un SKU específico
        
        Args:
            df: DataFrame con datos históricos
            sku: SKU a entrenar
            target_col: Columna objetivo
            test_size: Días para validación
        
        Returns:
            Tuple (modelo, métricas)
        """
        try:
            # Filter data for SKU
            sku_df = df[df['sku'] == sku].copy()
            
            if len(sku_df) < self.settings.MIN_TRAINING_SAMPLES:
                logger.warning(f"Insufficient data for SKU {sku}: {len(sku_df)} samples")
                return None, {'error': 'Insufficient data'}
            
            # Create features
            sku_df = self.create_features(sku_df, target_col)
            
            # Define feature columns (exclude target and metadata)
            exclude_cols = ['fecha', 'sku', target_col, 'monto_total', 'canal']
            self.feature_columns = [col for col in sku_df.columns 
                                   if col not in exclude_cols]
            
            # Prepare data
            X = sku_df[self.feature_columns].values
            y = sku_df[target_col].values
            
            # Time series split for validation
            if test_size > 0 and len(sku_df) > test_size + 10:
                X_train = X[:-test_size]
                y_train = y[:-test_size]
                X_test = X[-test_size:]
                y_test = y[-test_size:]
            else:
                X_train, y_train = X, y
                X_test, y_test = X[-min(7, len(X)//4):], y[-min(7, len(y)//4):]
            
            # Train model
            model = xgb.XGBRegressor(**XGBOOST_PARAMS)
            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                verbose=False
            )
            
            # Predictions
            y_pred_train = model.predict(X_train)
            y_pred_test = model.predict(X_test)
            
            # Calculate metrics
            train_metrics = self.calculate_metrics(y_train, y_pred_train)
            test_metrics = self.calculate_metrics(y_test, y_pred_test)
            
            # Feature importance
            feature_importance = dict(zip(
                self.feature_columns,
                model.feature_importances_
            ))
            
            # Sort by importance
            feature_importance = dict(sorted(
                feature_importance.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10])  # Top 10 features
            
            metrics = {
                'sku': sku,
                'train_metrics': train_metrics,
                'test_metrics': test_metrics,
                'feature_importance': feature_importance,
                'n_samples': len(sku_df),
                'success': True
            }
            
            return model, metrics
            
        except Exception as e:
            logger.error(f"Error training model for SKU {sku}: {e}")
            return None, {'sku': sku, 'error': str(e), 'success': False}
    
    def forecast_single_sku(
        self,
        model: xgb.XGBRegressor,
        last_data: pd.DataFrame,
        sku: str,
        horizon_days: int = 28,
        target_col: str = 'unidades_vendidas'
    ) -> pd.DataFrame:
        """
        Generar pronóstico para un SKU
        
        Args:
            model: Modelo entrenado
            last_data: Últimos datos históricos
            sku: SKU a pronosticar
            horizon_days: Días a pronosticar
            target_col: Columna objetivo
        
        Returns:
            DataFrame con pronósticos
        """
        try:
            # Prepare base dataframe
            last_date = last_data['fecha'].max()
            future_dates = pd.date_range(
                start=last_date + timedelta(days=1),
                periods=horizon_days,
                freq='D'
            )
            
            forecasts = []
            
            # Use last known values as starting point
            current_df = last_data.copy()
            
            for future_date in future_dates:
                # Create new row
                new_row = pd.DataFrame({
                    'fecha': [future_date],
                    'sku': [sku],
                    target_col: [0]  # Placeholder
                })
                
                # Add other columns from last row
                for col in current_df.columns:
                    if col not in new_row.columns:
                        if col in ['promo_flag', 'es_feriado']:
                            new_row[col] = 0  # Default to no promo/holiday
                        elif col in ['canal']:
                            new_row[col] = current_df[col].iloc[-1]
                        else:
                            new_row[col] = current_df[col].iloc[-1]
                
                # Append to current data
                temp_df = pd.concat([current_df, new_row], ignore_index=True)
                
                # Create features
                temp_df = self.create_features(temp_df, target_col)
                
                # Get features for prediction
                X_pred = temp_df[self.feature_columns].iloc[-1:].values
                
                # Make prediction
                y_pred = model.predict(X_pred)[0]
                y_pred = max(0, y_pred)  # Ensure non-negative
                
                # Calculate prediction intervals (simplified)
                # In production, use proper prediction intervals
                std_estimate = current_df[target_col].std() if len(current_df) > 1 else y_pred * 0.2
                lower_bound = max(0, y_pred - 1.96 * std_estimate)
                upper_bound = y_pred + 1.96 * std_estimate
                
                # Calculate stockout probability (simplified)
                # Assumes normal distribution
                if std_estimate > 0:
                    from scipy import stats
                    stockout_prob = stats.norm.cdf(0, loc=y_pred, scale=std_estimate) * 100
                else:
                    stockout_prob = 0 if y_pred > 0 else 100
                
                forecasts.append({
                    'sku': sku,
                    'fecha_objetivo': future_date,
                    'unidades_pronosticadas': round(y_pred, 2),
                    'limite_inferior': round(lower_bound, 2),
                    'limite_superior': round(upper_bound, 2),
                    'probabilidad_quiebre': round(stockout_prob, 2)
                })
                
                # Update current_df with prediction for next iteration
                temp_df.loc[temp_df.index[-1], target_col] = y_pred
                current_df = temp_df.tail(30)  # Keep last 30 days for context
            
            return pd.DataFrame(forecasts)
            
        except Exception as e:
            logger.error(f"Error forecasting SKU {sku}: {e}")
            return pd.DataFrame()
    
    def train_and_forecast_all(
        self,
        sales_df: pd.DataFrame,
        skus: Optional[List[str]] = None,
        horizon_days: int = 28,
        save_models: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
        """
        Entrenar y pronosticar para múltiples SKUs
        
        Args:
            sales_df: DataFrame con datos de ventas
            skus: Lista de SKUs (None para todos)
            horizon_days: Días a pronosticar
            save_models: Si guardar modelos entrenados
        
        Returns:
            Tuple (forecasts_df, metrics_df, summary)
        """
        if skus is None:
            skus = sales_df['sku'].unique()
        
        all_forecasts = []
        all_metrics = []
        models = {}
        
        logger.info(f"Training models for {len(skus)} SKUs")
        
        for i, sku in enumerate(skus, 1):
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(skus)} SKUs processed")
            
            # Train model
            model, metrics = self.train_single_sku(
                sales_df,
                sku,
                test_size=min(7, len(sales_df[sales_df['sku'] == sku]) // 10)
            )
            
            if model is not None and metrics.get('success'):
                # Generate forecast
                last_data = sales_df[sales_df['sku'] == sku].tail(30)
                forecast_df = self.forecast_single_sku(
                    model,
                    last_data,
                    sku,
                    horizon_days
                )
                
                if not forecast_df.empty:
                    all_forecasts.append(forecast_df)
                
                # Store metrics
                test_metrics = metrics.get('test_metrics', {})
                all_metrics.append({
                    'sku': sku,
                    **test_metrics
                })
                
                # Store model
                if save_models:
                    models[sku] = model
            else:
                logger.warning(f"Failed to train model for SKU {sku}")
                all_metrics.append({
                    'sku': sku,
                    'error': metrics.get('error', 'Unknown error')
                })
        
        # Combine results
        forecasts_df = pd.concat(all_forecasts, ignore_index=True) if all_forecasts else pd.DataFrame()
        metrics_df = pd.DataFrame(all_metrics)
        
        # Calculate summary statistics
        if not metrics_df.empty and 'mape' in metrics_df.columns:
            valid_metrics = metrics_df.dropna(subset=['mape'])
            summary = {
                'total_skus': len(skus),
                'successful_models': len(valid_metrics),
                'failed_models': len(skus) - len(valid_metrics),
                'avg_mape': valid_metrics['mape'].mean() if not valid_metrics.empty else None,
                'median_mape': valid_metrics['mape'].median() if not valid_metrics.empty else None,
                'skus_below_target': len(valid_metrics[valid_metrics['mape'] < self.settings.TARGET_MAPE]),
                'pct_below_target': len(valid_metrics[valid_metrics['mape'] < self.settings.TARGET_MAPE]) / len(valid_metrics) * 100 if not valid_metrics.empty else 0
            }
        else:
            summary = {
                'total_skus': len(skus),
                'successful_models': 0,
                'failed_models': len(skus),
                'error': 'No valid metrics calculated'
            }
        
        # Save models if requested
        if save_models and models:
            self.save_models(models)
        
        logger.info(f"Training complete. Summary: {summary}")
        
        return forecasts_df, metrics_df, summary
    
    def save_models(self, models: Dict[str, xgb.XGBRegressor], path: str = 'models/'):
        """Guardar modelos entrenados"""
        import os
        os.makedirs(path, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        for sku, model in models.items():
            filename = f"{path}/model_{sku}_{timestamp}.pkl"
            joblib.dump(model, filename)
            logger.info(f"Model saved: {filename}")
        
        # Save metadata
        metadata = {
            'timestamp': timestamp,
            'skus': list(models.keys()),
            'model_type': 'xgboost',
            'version': self.settings.MODEL_VERSION
        }
        
        joblib.dump(metadata, f"{path}/metadata_{timestamp}.pkl")
    
    def load_model(self, sku: str, path: str = 'models/') -> Optional[xgb.XGBRegressor]:
        """Cargar modelo guardado"""
        import os
        import glob
        
        # Find latest model for SKU
        pattern = f"{path}/model_{sku}_*.pkl"
        files = glob.glob(pattern)
        
        if not files:
            logger.warning(f"No model found for SKU {sku}")
            return None
        
        # Get most recent file
        latest_file = max(files, key=os.path.getctime)
        
        try:
            model = joblib.load(latest_file)
            logger.info(f"Model loaded: {latest_file}")
            return model
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return None
    
    def cross_validate(
        self,
        df: pd.DataFrame,
        sku: str,
        n_splits: int = 3,
        target_col: str = 'unidades_vendidas'
    ) -> Dict[str, Any]:
        """
        Validación cruzada temporal para un SKU
        
        Args:
            df: DataFrame con datos
            sku: SKU a validar
            n_splits: Número de splits
            target_col: Columna objetivo
        
        Returns:
            Diccionario con métricas de CV
        """
        try:
            # Filter data for SKU
            sku_df = df[df['sku'] == sku].copy()
            
            if len(sku_df) < self.settings.MIN_TRAINING_SAMPLES:
                return {'error': 'Insufficient data for cross-validation'}
            
            # Create features
            sku_df = self.create_features(sku_df, target_col)
            
            # Prepare data
            X = sku_df[self.feature_columns].values
            y = sku_df[target_col].values
            
            # Time series split
            tscv = TimeSeriesSplit(n_splits=n_splits)
            
            cv_metrics = []
            
            for train_idx, test_idx in tscv.split(X):
                X_train, X_test = X[train_idx], X[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]
                
                # Train model
                model = xgb.XGBRegressor(**XGBOOST_PARAMS)
                model.fit(X_train, y_train, verbose=False)
                
                # Predict
                y_pred = model.predict(X_test)
                
                # Calculate metrics
                fold_metrics = self.calculate_metrics(y_test, y_pred)
                cv_metrics.append(fold_metrics)
            
            # Average metrics across folds
            avg_metrics = {}
            for key in cv_metrics[0].keys():
                values = [m[key] for m in cv_metrics if m.get(key) is not None]
                if values:
                    avg_metrics[f'cv_mean_{key}'] = np.mean(values)
                    avg_metrics[f'cv_std_{key}'] = np.std(values)
            
            return {
                'sku': sku,
                'n_splits': n_splits,
                **avg_metrics,
                'fold_metrics': cv_metrics
            }
            
        except Exception as e:
            logger.error(f"Error in cross-validation for SKU {sku}: {e}")
            return {'sku': sku, 'error': str(e)}