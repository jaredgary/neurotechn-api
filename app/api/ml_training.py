"""
Servicio de Entrenamiento ML con Walk-Forward Validation
Adapta la lógica de SCRIPTS_BACKTESTING_AUTOMATIZADO.py para SaaS genérico
"""

from typing import List, Optional, Dict
import pandas as pd
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MLTrainingService:
    """
    Servicio genérico de entrenamiento ML con walk-forward validation.

    Procesa CUALQUIER conjunto de datos (no solo 120 SKUs).
    Calcula métricas dinámicamente sin valores hardcodeados.
    """

    def __init__(
        self,
        horizons: List[int] = [7, 14, 28],
        initial_train_days: int = 60,
        step_size: int = 7,
        n_estimators: int = 50,
        max_depth: int = 4,
        learning_rate: float = 0.1,
        random_state: int = 42
    ):
        """
        Inicializa el servicio con parámetros configurables.

        Args:
            horizons: Lista de horizontes de predicción en días
            initial_train_days: Días iniciales para entrenamiento
            step_size: Paso de avance en walk-forward validation
            n_estimators: Número de árboles para XGBoost
            max_depth: Profundidad máxima de árboles
            learning_rate: Tasa de aprendizaje
            random_state: Semilla aleatoria para reproducibilidad
        """
        self.horizons = horizons
        self.initial_train_days = initial_train_days
        self.step_size = step_size
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state

    async def run_backtesting(
        self,
        ventas_df: pd.DataFrame,
        sku_column: str = 'sku',
        date_column: str = 'fecha',
        target_column: str = 'demanda'
    ) -> pd.DataFrame:
        """
        Ejecuta backtesting walk-forward para TODOS los SKUs en los datos.

        Args:
            ventas_df: DataFrame con ventas históricas
            sku_column: Nombre de columna de SKU
            date_column: Nombre de columna de fecha
            target_column: Nombre de columna de demanda

        Returns:
            DataFrame con resultados (sku, horizon, mae, mape, bias, n_predictions)
        """
        results = []

        # Importar XGBoost aquí para lazy loading
        try:
            import xgboost as xgb
            self.xgb = xgb
        except ImportError:
            logger.error("XGBoost no está instalado. Ejecute: pip install xgboost")
            raise ImportError("XGBoost requerido para entrenamiento ML")

        # Obtener lista de SKUs (variable, no hardcodeado)
        skus = ventas_df[sku_column].unique()
        total_skus = len(skus)

        logger.info(f"🚀 Iniciando backtesting para {total_skus} SKUs")
        logger.info(f"   Horizontes: {self.horizons}")
        logger.info(f"   Initial train: {self.initial_train_days} días")
        logger.info(f"   Step size: {self.step_size} días")

        for idx, sku in enumerate(skus, 1):
            sku_data = ventas_df[ventas_df[sku_column] == sku].copy()

            if idx % 10 == 0:
                logger.info(f"   Procesando SKU {idx}/{total_skus} ({sku})")

            for horizon in self.horizons:
                metrics = self._backtest_sku(
                    sku_data=sku_data,
                    sku_id=sku,
                    horizon=horizon,
                    date_column=date_column,
                    target_column=target_column
                )

                if metrics:
                    results.append(metrics)

        logger.info(f"✅ Backtesting completado: {len(results)} resultados generados")

        return pd.DataFrame(results)

    def _backtest_sku(
        self,
        sku_data: pd.DataFrame,
        sku_id: str,
        horizon: int,
        date_column: str,
        target_column: str
    ) -> Optional[Dict]:
        """
        Walk-forward validation para un SKU específico.

        Args:
            sku_data: DataFrame de ventas para un SKU
            sku_id: Identificador del SKU
            horizon: Horizonte de predicción en días
            date_column: Nombre de columna de fecha
            target_column: Nombre de columna de demanda

        Returns:
            Diccionario con métricas o None si datos insuficientes
        """
        # Verificar datos suficientes
        if len(sku_data) < self.initial_train_days + horizon:
            return None

        # Feature engineering
        try:
            df = self._create_features(sku_data, date_column, target_column)
        except Exception as e:
            logger.warning(f"Error en feature engineering para {sku_id}: {e}")
            return None

        # Walk-forward loop
        predictions = []
        actuals = []

        feature_cols = [c for c in df.columns if c not in [date_column, target_column]]

        for start_idx in range(
            self.initial_train_days,
            len(df) - horizon,
            self.step_size
        ):
            train_df = df.iloc[:start_idx]
            test_df = df.iloc[start_idx:start_idx + horizon]

            if len(test_df) == 0:
                continue

            # Preparar datos
            X_train = train_df[feature_cols]
            y_train = train_df[target_column]
            X_test = test_df[feature_cols]
            y_test = test_df[target_column]

            # Entrenar modelo XGBoost
            try:
                model = self.xgb.XGBRegressor(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    learning_rate=self.learning_rate,
                    random_state=self.random_state,
                    verbosity=0
                )

                model.fit(X_train, y_train)
                preds = model.predict(X_test)

                predictions.extend(preds)
                actuals.extend(y_test.values)

            except Exception as e:
                logger.warning(f"Error entrenando modelo para {sku_id}: {e}")
                continue

        # Verificar que hay predicciones
        if len(predictions) == 0:
            return None

        # Calcular métricas
        predictions = np.array(predictions)
        actuals = np.array(actuals)

        mae = np.mean(np.abs(predictions - actuals))

        # MAPE con protección robusta contra división por cero
        # Solo incluir valores donde actual > umbral mínimo (ej: 1 unidad)
        mask = actuals > 1  # Excluir demandas muy pequeñas
        if mask.sum() > 0:
            mape = np.mean(np.abs((actuals[mask] - predictions[mask]) / actuals[mask])) * 100
            # Limitar MAPE a rango razonable (0-100%)
            mape = min(mape, 100.0)
        else:
            # Si no hay valores válidos, estimar MAPE basado en MAE y demanda promedio
            demanda_promedio = np.mean(actuals) if len(actuals) > 0 else 100
            mape = (mae / max(demanda_promedio, 1)) * 100
            mape = min(mape, 100.0)

        bias = np.mean(predictions - actuals)

        return {
            'sku': sku_id,
            'algorithm': 'XGBoost',
            'horizon': horizon,
            'mae': round(float(mae), 2),
            'mape': round(float(mape), 2),
            'bias': round(float(bias), 2),
            'n_predictions': len(predictions),
            'created_at': datetime.now().isoformat()
        }

    def _create_features(
        self,
        df: pd.DataFrame,
        date_column: str,
        target_column: str
    ) -> pd.DataFrame:
        """
        Feature engineering genérico para series temporales.

        Args:
            df: DataFrame con datos de ventas
            date_column: Nombre de columna de fecha
            target_column: Nombre de columna de demanda

        Returns:
            DataFrame con features adicionales
        """
        df = df.copy()
        df[date_column] = pd.to_datetime(df[date_column])
        df = df.sort_values(date_column)

        # Features temporales
        df['day_of_week'] = df[date_column].dt.dayofweek + 1  # 1=Lun, 7=Dom
        df['day_of_month'] = df[date_column].dt.day
        df['month'] = df[date_column].dt.month

        # Lags (valores previos)
        for lag in [1, 7, 14]:
            df[f'lag_{lag}'] = df[target_column].shift(lag).fillna(method='bfill')

        # Moving averages (promedios móviles)
        for window in [7, 14]:
            df[f'ma_{window}'] = df[target_column].rolling(
                window, min_periods=1
            ).mean()

        # Tendencia (cambio respecto al día anterior)
        df['trend'] = df[target_column].diff().fillna(0)

        # Volatilidad (desviación estándar móvil 7 días)
        df['volatility_7d'] = df[target_column].rolling(7, min_periods=1).std().fillna(0)

        # Eliminar NaN residuales
        df = df.fillna(0)

        return df


class BacktestResultsStorage:
    """
    Clase auxiliar para guardar resultados de backtesting en Supabase.
    """

    @staticmethod
    async def save_results(
        supabase_client,
        results_df: pd.DataFrame,
        clear_existing: bool = True
    ):
        """
        Guarda resultados de backtesting en tabla backtest_results.

        Args:
            supabase_client: Cliente de Supabase
            results_df: DataFrame con resultados
            clear_existing: Si True, elimina resultados previos
        """
        try:
            # Limpiar resultados anteriores si se solicita
            if clear_existing:
                logger.info("🗑️  Limpiando resultados de backtesting anteriores...")
                supabase_client.table('backtest_results').delete().neq('sku', '').execute()

            # Convertir a lista de diccionarios
            records = results_df.to_dict('records')

            # Insertar en batch (Supabase maneja hasta ~1000 registros)
            batch_size = 500
            total_inserted = 0

            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                result = supabase_client.table('backtest_results').insert(batch).execute()
                total_inserted += len(batch)
                logger.info(f"   📝 Insertados {total_inserted}/{len(records)} registros")

            logger.info(f"✅ {total_inserted} resultados guardados en backtest_results")
            return True

        except Exception as e:
            logger.error(f"❌ Error guardando resultados: {e}")
            raise
