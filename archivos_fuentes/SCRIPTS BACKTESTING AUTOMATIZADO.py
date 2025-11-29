# =============================================================================
# SCRIPTS BACKTESTING AUTOMATIZADO - VERSIÓN CORREGIDA COMPLETA
# =============================================================================
# Objetivo Específico 2: Definir Técnicas de IA
# Farmacias Siman - San Pedro Sula
# 
# CORRECCIÓN #7: Procesar 120 SKUs completos (no solo 10)
# =============================================================================

import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostRegressor
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Configuración visualización
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# =============================================================================
# CLASE PRINCIPAL: BACKTESTING AUTOMATIZADO
# =============================================================================

class BacktestingAnalyzer:
    """
    Analizador de backtesting detallado por SKU individual
    
    Complementa el protocolo walk-forward con análisis granular:
    - Métricas por SKU: MAE, MAPE, sesgo (según Tabla 17)
    - Comparación con baselines simples (naive, MA)
    - Visualizaciones de errores
    - Identificación de SKUs problemáticos
    - Análisis temporal de errores
    """
    
    def __init__(self, data, sku_column='sku', date_column='fecha', target_column='demanda'):
        """
        Inicializar analizador de backtesting
        
        Parameters:
        -----------
        data : pandas.DataFrame
            Datos históricos con SKU, fecha y demanda
        sku_column : str
            Nombre columna identificador SKU
        date_column : str
            Nombre columna fecha
        target_column : str
            Nombre columna objetivo (demanda/ventas)
        """
        self.data = data.copy()
        self.data[date_column] = pd.to_datetime(self.data[date_column])
        self.data = self.data.sort_values([sku_column, date_column]).reset_index(drop=True)
        
        self.sku_column = sku_column
        self.date_column = date_column
        self.target_column = target_column
        
        self.skus = self.data[sku_column].unique()
        self.horizons = [7, 14, 28]
        
        self.results = {}
        self.baseline_results = {}
        
        print(f"✓ Analizador inicializado")
        print(f"  - SKUs: {len(self.skus)}")
        print(f"  - Registros: {len(self.data)}")
        print(f"  - Período: {self.data[date_column].min().date()} a {self.data[date_column].max().date()}")
    
    def create_features_per_sku(self, sku_data):
        """
        Feature engineering por SKU individual
        
        FIX CRÍTICO: Siempre crear las columnas, incluso si son NaN
        Usar pandas 2.x compatible syntax para fillna
        
        Parameters:
        -----------
        sku_data : pandas.DataFrame
            Datos de un solo SKU
            
        Returns:
        --------
        features : pandas.DataFrame
            DataFrame con features temporales
        """
        df = sku_data.copy()
        
        # Variables temporales básicas
        df['day_of_week'] = df[self.date_column].dt.dayofweek + 1
        df['day_of_month'] = df[self.date_column].dt.day
        df['week_of_year'] = df[self.date_column].dt.isocalendar().week
        
        # FIX: SIEMPRE crear las columnas lag, sin condiciones
        # Incluso si el lag es mayor que len(df), pandas manejará con NaN
        lag_periods = [1, 7, 14]
        for lag in lag_periods:
            df[f'lag_{lag}'] = df[self.target_column].shift(lag)
        
        # FIX: SIEMPRE crear las medias móviles
        ma_windows = [7, 14]
        for window in ma_windows:
            df[f'ma_{window}'] = df[self.target_column].rolling(
                window=window, 
                min_periods=1
            ).mean()
        
        # Tendencia (diferencia de primer orden)
        df['trend'] = df[self.target_column].diff()
        
        # Desviación estándar móvil (volatilidad)
        df['std_7'] = df[self.target_column].rolling(
            window=7, 
            min_periods=1
        ).std()
        
        # FIX: Usar pandas 2.x compatible syntax para fillna
        # Reemplazar fillna(method='ffill') por ffill()
        for lag in lag_periods:
            df[f'lag_{lag}'] = df[f'lag_{lag}'].ffill().bfill()
        
        for window in ma_windows:
            df[f'ma_{window}'] = df[f'ma_{window}'].bfill()
        
        # Rellenar trend y std
        df['trend'] = df['trend'].fillna(0)
        df['std_7'] = df['std_7'].fillna(df[self.target_column].std() if len(df) > 0 else 0)
        
        # Reemplazar infinitos
        df = df.replace([np.inf, -np.inf], np.nan)
        
        # Rellenar cualquier NaN restante con 0
        df = df.fillna(0)
        
        return df
    
    def backtest_sku(self, sku_id, algorithm_name, horizon, train_size=60, step_size=7):
        """
        Backtesting walk-forward para un SKU específico
        
        Calcula métricas según Tabla 17:
        - MAE (Error Absoluto Medio)
        - MAPE (Error Porcentual Absoluto Medio)
        - Sesgo (error medio)
        
        Parameters:
        -----------
        sku_id : str
            Identificador del SKU
        algorithm_name : str
            Nombre del algoritmo ('XGBoost', 'LightGBM', 'CatBoost')
        horizon : int
            Horizonte de pronóstico (7, 14, 28 días)
        train_size : int
            Ventana inicial entrenamiento
        step_size : int
            Incremento por fold
            
        Returns:
        --------
        results : dict
            Métricas detalladas del backtesting
        """
        # Filtrar datos del SKU
        sku_data = self.data[self.data[self.sku_column] == sku_id].copy()
        
        if len(sku_data) < train_size + horizon:
            return None  # SKU con datos insuficientes
        
        # Configurar algoritmo
        if algorithm_name == 'XGBoost':
            model = xgb.XGBRegressor(
                n_estimators=50, 
                max_depth=4, 
                learning_rate=0.1, 
                random_state=42, 
                verbosity=0
            )
        elif algorithm_name == 'LightGBM':
            model = lgb.LGBMRegressor(
                n_estimators=50, 
                max_depth=4, 
                learning_rate=0.1, 
                random_state=42, 
                verbose=-1
            )
        elif algorithm_name == 'CatBoost':
            model = CatBoostRegressor(
                iterations=50, 
                depth=4, 
                learning_rate=0.1, 
                random_seed=42, 
                verbose=False
            )
        else:
            return None
        
        predictions = []
        actuals = []
        dates_pred = []
        
        min_date = sku_data[self.date_column].min()
        max_date = sku_data[self.date_column].max()
        
        # Walk-forward loop
        current_train_end = min_date + timedelta(days=train_size - 1)
        
        while current_train_end + timedelta(days=horizon) <= max_date:
            
            # Datos de entrenamiento: desde min_date hasta current_train_end
            train_data = sku_data[
                (sku_data[self.date_column] >= min_date) & 
                (sku_data[self.date_column] <= current_train_end)
            ].copy()
            
            # Datos de test: horizonte después del entrenamiento
            test_start = current_train_end + timedelta(days=1)
            test_end = test_start + timedelta(days=horizon - 1)
            
            test_data = sku_data[
                (sku_data[self.date_column] >= test_start) & 
                (sku_data[self.date_column] <= test_end)
            ].copy()
            
            # Saltar fold si test tiene menos registros que horizonte
            if len(test_data) < horizon:
                break
            
            # Feature engineering
            train_features = self.create_features_per_sku(train_data)
            test_features = self.create_features_per_sku(test_data)
            
            # Columnas de features (excluyendo target y fecha)
            feature_cols = [c for c in train_features.columns 
                          if c not in [self.sku_column, self.date_column, self.target_column]]
            
            # Entrenar modelo
            X_train = train_features[feature_cols]
            y_train = train_features[self.target_column]
            
            X_test = test_features[feature_cols]
            y_test = test_features[self.target_column]
            
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            
            # Guardar predicciones
            predictions.extend(y_pred.tolist())
            actuals.extend(y_test.tolist())
            dates_pred.extend(test_features[self.date_column].tolist())
            
            # Avanzar ventana
            current_train_end += timedelta(days=step_size)
        
        if len(predictions) == 0:
            return None
        
        # Calcular métricas
        predictions = np.array(predictions)
        actuals = np.array(actuals)
        
        mae = mean_absolute_error(actuals, predictions)
        mape = np.mean(np.abs((actuals - predictions) / (actuals + 1e-10))) * 100
        bias = np.mean(predictions - actuals)
        
        return {
            'sku': sku_id,
            'algorithm': algorithm_name,
            'horizon': horizon,
            'mae': mae,
            'mape': mape,
            'bias': bias,
            'n_predictions': len(predictions),
            'predictions': predictions,
            'actuals': actuals,
            'dates': dates_pred
        }
    
    def run_comprehensive_backtest(self, selected_algorithm='XGBoost', sample_skus=None):
        """
        Ejecutar backtesting comprehensivo por SKU
        
        Parameters:
        -----------
        selected_algorithm : str
            Algoritmo ganador del benchmarking walk-forward
        sample_skus : list
            Lista de SKUs a procesar (si None, procesa todos)
            
        Returns:
        --------
        results_df : pandas.DataFrame
            DataFrame con métricas por SKU y horizonte
        """
        if sample_skus is None:
            sample_skus = self.skus
        
        results_list = []
        
        print(f"\n{'='*70}")
        print(f"  BACKTESTING COMPREHENSIVO")
        print(f"{'='*70}")
        print(f"  Algoritmo: {selected_algorithm}")
        print(f"  SKUs a procesar: {len(sample_skus)}")
        print(f"  Horizontes: {self.horizons}")
        print(f"{'='*70}\n")
        
        total_iterations = len(sample_skus) * len(self.horizons)
        current_iteration = 0
        
        for sku_id in sample_skus:
            for horizon in self.horizons:
                current_iteration += 1
                progress = (current_iteration / total_iterations) * 100
                
                print(f"[{progress:5.1f}%] Procesando {sku_id} - Horizonte {horizon}d...", end=' ')
                
                result = self.backtest_sku(
                    sku_id=sku_id,
                    algorithm_name=selected_algorithm,
                    horizon=horizon,
                    train_size=60,
                    step_size=7
                )
                
                if result is not None:
                    results_list.append(result)
                    self.results[f"{sku_id}_{horizon}"] = result
                    print(f"✓ MAE={result['mae']:.2f}, MAPE={result['mape']:.1f}%")
                else:
                    print(f"⚠ Datos insuficientes")
        
        print(f"\n{'='*70}")
        print(f"  BACKTESTING COMPLETADO")
        print(f"{'='*70}")
        print(f"  Total registros generados: {len(results_list)}")
        print(f"  SKUs procesados exitosamente: {len(set([r['sku'] for r in results_list]))}")
        print(f"{'='*70}\n")
        
        # Convertir a DataFrame
        if len(results_list) > 0:
            results_df = pd.DataFrame([
                {k: v for k, v in r.items() if k not in ['predictions', 'actuals', 'dates']}
                for r in results_list
            ])
            return results_df
        else:
            return pd.DataFrame()
    
    def generate_summary_report(self):
        """
        Generar reporte resumen de resultados
        """
        if len(self.results) == 0:
            print("⚠ No hay resultados para reportar")
            return
        
        print("\n" + "="*70)
        print("  REPORTE RESUMEN - MÉTRICAS AGREGADAS")
        print("="*70)
        
        results_list = list(self.results.values())
        df = pd.DataFrame([
            {k: v for k, v in r.items() if k not in ['predictions', 'actuals', 'dates']}
            for r in results_list
        ])
        
        # Métricas por horizonte
        print("\n📊 MÉTRICAS POR HORIZONTE DE PREDICCIÓN:")
        print("-" * 70)
        
        for horizon in self.horizons:
            horizon_data = df[df['horizon'] == horizon]
            
            if len(horizon_data) > 0:
                print(f"\nHorizonte {horizon} días:")
                print(f"  - MAE promedio: {horizon_data['mae'].mean():.2f} unidades")
                print(f"  - MAPE promedio: {horizon_data['mape'].mean():.1f}%")
                print(f"  - Sesgo promedio: {horizon_data['bias'].mean():.2f} unidades")
                print(f"  - SKUs evaluados: {len(horizon_data)}")
        
        # Top 10 mejores SKUs (menor MAPE)
        print("\n🏆 TOP 10 SKUs CON MEJOR DESEMPEÑO (menor MAPE):")
        print("-" * 70)
        
        top_skus = df.nsmallest(10, 'mape')[['sku', 'horizon', 'mae', 'mape', 'bias']]
        for idx, row in top_skus.iterrows():
            print(f"  {row['sku']} (H={row['horizon']}d): MAE={row['mae']:.2f}, MAPE={row['mape']:.1f}%, Sesgo={row['bias']:.2f}")
        
        # Top 10 peores SKUs (mayor MAPE)
        print("\n⚠️  TOP 10 SKUs CON PEOR DESEMPEÑO (mayor MAPE):")
        print("-" * 70)
        
        worst_skus = df.nlargest(10, 'mape')[['sku', 'horizon', 'mae', 'mape', 'bias']]
        for idx, row in worst_skus.iterrows():
            print(f"  {row['sku']} (H={row['horizon']}d): MAE={row['mae']:.2f}, MAPE={row['mape']:.1f}%, Sesgo={row['bias']:.2f}")
        
        print("\n" + "="*70)
    
    def compare_with_baselines(self):
        """
        Comparar con métodos baseline simples
        """
        print("\n" + "="*70)
        print("  COMPARACIÓN CON BASELINES SIMPLES")
        print("="*70)
        
        # Naive forecast (último valor conocido)
        # Moving Average (MA-7)
        
        for sku_id in list(self.results.keys())[:5]:  # Primeros 5 SKUs como ejemplo
            result = self.results[sku_id]
            actuals = result['actuals']
            
            # Baseline 1: Naive (repetir último valor)
            naive_pred = np.full(len(actuals), actuals[0])
            mae_naive = mean_absolute_error(actuals, naive_pred)
            mape_naive = np.mean(np.abs((actuals - naive_pred) / (actuals + 1e-10))) * 100
            
            # Baseline 2: MA-7 (promedio de últimos 7 días)
            ma_pred = np.full(len(actuals), actuals[:7].mean())
            mae_ma = mean_absolute_error(actuals, ma_pred)
            mape_ma = np.mean(np.abs((actuals - ma_pred) / (actuals + 1e-10))) * 100
            
            print(f"\n{result['sku']} (Horizonte {result['horizon']}d):")
            print(f"  {result['algorithm']:12s}: MAE={result['mae']:.2f}, MAPE={result['mape']:.1f}%")
            print(f"  {'Naive':12s}: MAE={mae_naive:.2f}, MAPE={mape_naive:.1f}%")
            print(f"  {'MA-7':12s}: MAE={mae_ma:.2f}, MAPE={mape_ma:.1f}%")
            
            improvement_vs_naive = ((mape_naive - result['mape']) / mape_naive) * 100
            improvement_vs_ma = ((mape_ma - result['mape']) / mape_ma) * 100
            
            print(f"  Mejora vs Naive: {improvement_vs_naive:.1f}%")
            print(f"  Mejora vs MA-7: {improvement_vs_ma:.1f}%")
        
        print("\n" + "="*70)
    
    def identify_problematic_skus(self, threshold_mape=40):
        """
        Identificar SKUs con alto MAPE (problemáticos)
        """
        print("\n" + "="*70)
        print(f"  SKUs PROBLEMÁTICOS (MAPE > {threshold_mape}%)")
        print("="*70)
        
        results_list = list(self.results.values())
        df = pd.DataFrame([
            {k: v for k, v in r.items() if k not in ['predictions', 'actuals', 'dates']}
            for r in results_list
        ])
        
        problematic = df[df['mape'] > threshold_mape].sort_values('mape', ascending=False)
        
        if len(problematic) > 0:
            print(f"\n⚠️  Se identificaron {len(problematic)} casos con MAPE > {threshold_mape}%:\n")
            
            for idx, row in problematic.iterrows():
                print(f"  {row['sku']} (H={row['horizon']}d): "
                      f"MAE={row['mae']:.2f}, MAPE={row['mape']:.1f}%, Sesgo={row['bias']:.2f}")
            
            print(f"\nRecomendación: Revisar patrones de demanda de estos SKUs")
        else:
            print(f"\n✓ No se encontraron SKUs con MAPE > {threshold_mape}%")
        
        print("\n" + "="*70)
    
    def analyze_error_by_weekday(self):
        """
        Analizar errores por día de la semana
        """
        print("\n" + "="*70)
        print("  ANÁLISIS DE ERRORES POR DÍA DE SEMANA")
        print("="*70)
        
        weekday_errors = {i: [] for i in range(7)}
        
        for result in list(self.results.values())[:30]:  # Primeros 30 para muestra
            dates = pd.to_datetime(result['dates'])
            actuals = result['actuals']
            predictions = result['predictions']
            errors = np.abs(actuals - predictions)
            
            for date, error in zip(dates, errors):
                weekday_errors[date.weekday()].append(error)
        
        days_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        
        print("\nMAE promedio por día de semana:")
        for day_idx, day_name in enumerate(days_names):
            if len(weekday_errors[day_idx]) > 0:
                avg_error = np.mean(weekday_errors[day_idx])
                print(f"  {day_name:10s}: {avg_error:.2f} unidades")
        
        print("\n" + "="*70)
    
    def plot_error_distribution(self, save_path='error_distribution.png'):
        """
        Visualizar distribución de errores
        """
        results_list = list(self.results.values())
        df = pd.DataFrame([
            {k: v for k, v in r.items() if k not in ['predictions', 'actuals', 'dates']}
            for r in results_list
        ])
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle('Distribución de Errores por Horizonte de Predicción', 
                     fontsize=16, fontweight='bold')
        
        # 1. Histograma de MAPE
        for horizon in self.horizons:
            horizon_data = df[df['horizon'] == horizon]
            axes[0, 0].hist(horizon_data['mape'], bins=20, alpha=0.6, label=f'{horizon}d')
        
        axes[0, 0].set_title('Distribución de MAPE (%)')
        axes[0, 0].set_xlabel('MAPE (%)')
        axes[0, 0].set_ylabel('Frecuencia')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)
        
        # 2. Boxplot de MAE por horizonte
        mae_data = [df[df['horizon'] == h]['mae'].values for h in self.horizons]
        axes[0, 1].boxplot(mae_data, labels=[f'{h}d' for h in self.horizons])
        axes[0, 1].set_title('Distribución de MAE por Horizonte')
        axes[0, 1].set_xlabel('Horizonte')
        axes[0, 1].set_ylabel('MAE (unidades)')
        axes[0, 1].grid(True, alpha=0.3)
        
        # 3. Sesgo por horizonte
        bias_data = [df[df['horizon'] == h]['bias'].values for h in self.horizons]
        axes[1, 0].boxplot(bias_data, labels=[f'{h}d' for h in self.horizons])
        axes[1, 0].axhline(y=0, color='r', linestyle='--', label='Sesgo neutro')
        axes[1, 0].set_title('Distribución de Sesgo por Horizonte')
        axes[1, 0].set_xlabel('Horizonte')
        axes[1, 0].set_ylabel('Sesgo (unidades)')
        axes[1, 0].legend()
        axes[1, 0].grid(True, alpha=0.3)
        
        # 4. Scatter MAE vs MAPE
        for horizon in self.horizons:
            horizon_data = df[df['horizon'] == horizon]
            axes[1, 1].scatter(horizon_data['mae'], horizon_data['mape'], 
                             label=f'{horizon}d', alpha=0.6, s=50)
        
        axes[1, 1].set_title('MAE vs MAPE')
        axes[1, 1].set_xlabel('MAE')
        axes[1, 1].set_ylabel('MAPE (%)')
        axes[1, 1].legend()
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"  ✓ Gráfico guardado: {save_path}")
        plt.close()
    
    def plot_predictions_vs_actuals(self, sku_id, horizon, save_path='predictions_vs_actuals_sample.png'):
        """
        Visualizar predicciones vs valores reales para un SKU específico
        """
        # Buscar resultado del SKU
        sku_result = None
        for r in self.results.values():
            if r['sku'] == sku_id and r['horizon'] == horizon:
                sku_result = r
                break
        
        if sku_result is None:
            print(f"  ⚠ No hay resultados para {sku_id} - Horizonte {horizon}d")
            return
        
        predictions = np.array(sku_result['predictions'])
        actuals = np.array(sku_result['actuals'])
        
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f'Predicciones vs Reales - {sku_id} (Horizonte {horizon}d)', 
                     fontsize=14, fontweight='bold')
        
        # Serie temporal
        axes[0].plot(actuals, label='Real', marker='o', markersize=3, alpha=0.7)
        axes[0].plot(predictions, label='Predicción', marker='x', markersize=3, alpha=0.7)
        axes[0].set_title('Serie Temporal')
        axes[0].set_xlabel('Índice temporal')
        axes[0].set_ylabel('Demanda')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Scatter plot
        axes[1].scatter(actuals, predictions, alpha=0.5, s=30)
        
        # Línea diagonal (predicción perfecta)
        min_val = min(actuals.min(), predictions.min())
        max_val = max(actuals.max(), predictions.max())
        axes[1].plot([min_val, max_val], [min_val, max_val], 'r--', label='Predicción perfecta')
        
        axes[1].set_title('Predicción vs Real')
        axes[1].set_xlabel('Demanda Real')
        axes[1].set_ylabel('Demanda Predicha')
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)
        
        # Añadir métricas en el plot
        textstr = f"MAE: {sku_result['mae']:.2f}\nMAPE: {sku_result['mape']:.1f}%\nSesgo: {sku_result['bias']:.2f}"
        axes[1].text(0.05, 0.95, textstr, transform=axes[1].transAxes, fontsize=10,
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"  ✓ Gráfico guardado: {save_path}")
        plt.close()
    
    def export_detailed_results(self, filename='backtest_detailed_results.csv'):
        """
        Exportar resultados detallados a CSV
        """
        if len(self.results) == 0:
            return
        
        results_df = pd.DataFrame([
            {k: v for k, v in r.items() if k not in ['predictions', 'actuals', 'dates']}
            for r in self.results.values()
        ])
        
        results_df.to_csv(filename, index=False, encoding='utf-8')
        print(f"\n✓ Resultados exportados: {filename}")
        print(f"  Columnas: {', '.join(results_df.columns)}")
        print(f"  Registros: {len(results_df)}")

# =============================================================================
# GENERACIÓN DE DATOS SINTÉTICOS (FALLBACK)
# =============================================================================

def generate_synthetic_data_with_skus(n_skus=120, days=90, seed=42):
    """
    Generar datos sintéticos con múltiples SKUs si no hay datos reales
    """
    np.random.seed(seed)
    
    start_date = datetime.now() - timedelta(days=days)
    dates = [start_date + timedelta(days=i) for i in range(days)]
    
    data_list = []
    
    for sku_id in range(1, n_skus + 1):
        base_demand = np.random.uniform(50, 150)
        trend = np.random.uniform(-0.002, 0.002)
        
        for day_idx, date in enumerate(dates):
            # Patrón semanal
            day_of_week = date.weekday()
            weekly_factor = 1.2 if day_of_week in [0, 4] else (0.7 if day_of_week in [5, 6] else 1.0)
            
            # Ruido
            noise = np.random.normal(0, base_demand * 0.2)
            
            # Eventos aleatorios
            event = np.random.choice([0, base_demand * 0.5], p=[0.95, 0.05])
            
            # Demanda final
            demand = max(0, base_demand * weekly_factor * (1 + trend * day_idx) + noise + event)
            
            data_list.append({
                'fecha': date.strftime('%Y-%m-%d'),
                'sku': f'MED{sku_id:03d}',
                'demanda': round(demand, 0)
            })
    
    df = pd.DataFrame(data_list)
    
    print(f"✓ Datos sintéticos generados: {len(df)} registros ({n_skus} SKUs × {days} días)")
    
    return df

# =============================================================================
# SCRIPT PRINCIPAL
# =============================================================================

def main():
    """
    Script principal para backtesting automatizado
    """
    
    print("\n" + "="*70)
    print("  SCRIPTS BACKTESTING AUTOMATIZADO")
    print("="*70)
    print("  Farmacias Siman - San Pedro Sula")
    print("  Tesis: Modelo de Información con Capacidades Predictivas")
    print("  Objetivo Específico 2: Análisis Detallado por SKU")
    print("  Métricas: MAE, MAPE, Sesgo (según Tabla 17)")
    print("="*70)
    
    # Intentar cargar datos reales
    try:
        print("\nIntentando cargar datos reales...")
        data = pd.read_csv('datos_farmacias_siman.csv')
        print(f"✓ Datos reales cargados: {len(data)} registros")
        print(f"  - SKUs únicos: {data['sku'].nunique()}")
        print(f"  - Rango fechas: {data['fecha'].min()} a {data['fecha'].max()}")
    except:
        print("\n⚠ Datos reales no disponibles")
        print("Generando datos sintéticos para demostración...")
        data = generate_synthetic_data_with_skus(n_skus=120, days=90, seed=42)
    
    # Inicializar analizador
    analyzer = BacktestingAnalyzer(
        data=data,
        sku_column='sku',
        date_column='fecha',
        target_column='demanda'
    )
    
    # Ejecutar backtesting comprehensivo
    # Nota: Usar el algoritmo GANADOR del walk-forward principal (Anexo V)
    selected_algorithm = 'XGBoost'  # Cambiar según resultado del benchmarking
    
    # CORRECCIÓN #7: PROCESAR TODOS LOS SKUs (120), NO SOLO 10
    print(f"\nEjecutando backtesting detallado con {selected_algorithm}...")
    print(f"  ✓ Procesando TODOS los SKUs disponibles: {len(analyzer.skus)} SKUs")
    print(f"  ✓ Alcance completo del proyecto (100% cobertura)")
    
    results_df = analyzer.run_comprehensive_backtest(
        selected_algorithm=selected_algorithm,
        sample_skus=analyzer.skus  # TODOS los SKUs (120 completos)
    )
    
    if not results_df.empty:
        # Reporte resumen
        analyzer.generate_summary_report()
        
        # Comparación con baselines
        analyzer.compare_with_baselines()
        
        # Identificar SKUs problemáticos
        analyzer.identify_problematic_skus(threshold_mape=40)
        
        # Análisis por día de semana
        analyzer.analyze_error_by_weekday()
        
        # Visualizaciones
        print("\nGenerando visualizaciones...")
        analyzer.plot_error_distribution(save_path='error_distribution.png')
        
        # Plot para primer SKU encontrado
        if len(analyzer.skus) > 0:
            analyzer.plot_predictions_vs_actuals(
                sku_id=analyzer.skus[0],
                horizon=7,
                save_path='predictions_vs_actuals_sample.png'
            )
        
        # Exportar resultados
        analyzer.export_detailed_results(filename='backtest_detailed_results.csv')
        
        # Validación de alcance
        print("\n" + "="*70)
        print("  VALIDACIÓN DE ALCANCE")
        print("="*70)
        total_skus = len(data['sku'].unique())
        processed_skus = len(results_df['sku'].unique())
        coverage = (processed_skus / total_skus) * 100
        
        print(f"\n✓ SKUs en datos originales: {total_skus}")
        print(f"✓ SKUs procesados exitosamente: {processed_skus}")
        print(f"✓ Cobertura: {coverage:.1f}%")
        print(f"✓ Registros generados: {len(results_df)} (3 horizontes × {processed_skus} SKUs)")
        
        if coverage == 100.0:
            print("\n🎯 ALCANCE COMPLETO: Todos los SKUs han sido procesados")
        else:
            print(f"\n⚠️  ALCANCE PARCIAL: {total_skus - processed_skus} SKUs no procesados (posiblemente por datos insuficientes)")
    
    print("\n" + "="*70)
    print("  BACKTESTING COMPLETADO")
    print("="*70)
    print("\nArchivos generados:")
    print("  - backtest_detailed_results.csv (métricas: MAE, MAPE, Sesgo)")
    print("  - error_distribution.png (4 gráficos de errores)")
    print("  - predictions_vs_actuals_sample.png (ejemplo SKU)")
    print("\n" + "="*70)

if __name__ == "__main__":
    main()