# =============================================================================
# PROTOCOLO DE VALIDACIÓN WALK-FORWARD (ROLLING ORIGIN) - VERSIÓN CORREGIDA
# =============================================================================
# Objetivo Específico 2: Definir Técnicas de IA
# Tesis: Modelo de Información con Capacidades Predictivas
# Farmacias Siman - San Pedro Sula
# 
# FIX: Manejo correcto de features con fillna() en lugar de dropna()
# =============================================================================

import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostRegressor
import time
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CLASE PRINCIPAL: PROTOCOLO DE VALIDACIÓN
# =============================================================================

class ValidationProtocol:
    """
    Protocolo de validación temporal walk-forward para series cortas (90 días)
    
    Implementa validación rolling origin con ventana inicial de 60 días y 
    expansión de 7 días por fold, según metodología Tabla 21 (Capítulo III).
    """
    
    def __init__(self, data, target_column='demanda', date_column='fecha'):
        """
        Inicializar protocolo de validación
        
        Parameters:
        -----------
        data : pandas.DataFrame
            Datos históricos con fecha y variable objetivo
        target_column : str
            Nombre de columna objetivo (demanda/ventas)
        date_column : str
            Nombre de columna fecha (formato YYYY-MM-DD)
        """
        self.data = data.copy()
        self.data[date_column] = pd.to_datetime(self.data[date_column])
        self.data = self.data.sort_values(date_column).reset_index(drop=True)
        
        self.target_column = target_column
        self.date_column = date_column
        self.horizons = [7, 14, 28]  # Horizontes de pronóstico (días)
        self.algorithms = {}
        self.results = {}
        
        # Configuración walk-forward según Tabla 21
        self.initial_train_size = 60  # Ventana inicial entrenamiento (días)
        self.step_size = 7            # Incremento por fold (días)
        
        print(f"✓ Protocolo inicializado")
        print(f"  - Datos: {len(self.data)} registros")
        print(f"  - Período: {self.data[date_column].min().date()} a {self.data[date_column].max().date()}")
        print(f"  - Ventana inicial: {self.initial_train_size} días")
        print(f"  - Incremento por fold: {self.step_size} días")
        
    def setup_algorithms(self):
        """
        Configuración estándar de algoritmos gradient boosting
        
        Hiperparámetros base para comparación justa:
        - n_estimators/iterations: 100
        - max_depth/depth: 6
        - learning_rate: 0.1
        - random_state/seed: 42
        """
        self.algorithms = {
            'XGBoost': xgb.XGBRegressor(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                verbosity=0
            ),
            'LightGBM': lgb.LGBMRegressor(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                verbose=-1
            ),
            'CatBoost': CatBoostRegressor(
                iterations=100,
                depth=6,
                learning_rate=0.1,
                random_seed=42,
                verbose=False
            )
        }
        print(f"✓ Algoritmos configurados: {list(self.algorithms.keys())}")
    
    def create_features(self, data, horizon):
        """
        Feature engineering para series temporales farmacéuticas
        
        CRÍTICO: Usa fillna() para imputar NaN en lugar de dropna()
        
        Según Tabla 21 (Fase 1):
        - Lags temporales: rezagos 7, 14, 28 días
        - Medias móviles: ventanas 7, 14, 30 días
        - Tendencias: diferencias de primer orden
        - Estacionalidad semanal: día de la semana (1-7)
        
        Parameters:
        -----------
        data : pandas.DataFrame
            Datos base con columna fecha y objetivo
        horizon : int
            Horizonte de pronóstico (7, 14, 28 días)
            
        Returns:
        --------
        features : pandas.DataFrame
            DataFrame con features temporales agregados
        """
        df = data.copy()
        
        # Variables temporales básicas
        df['day_of_week'] = df[self.date_column].dt.dayofweek + 1  # 1=Lunes, 7=Domingo
        df['day_of_month'] = df[self.date_column].dt.day
        df['week_of_year'] = df[self.date_column].dt.isocalendar().week
        
        # Lags temporales (rezagos críticos para farmacia)
        # FIX: Solo crear lags que tengan sentido para el horizonte
        lag_periods = [7, 14, 28]
        for lag in lag_periods:
            df[f'lag_{lag}'] = df[self.target_column].shift(lag)
        
        # Medias móviles (suavizado de demanda)
        ma_windows = [7, 14, 30]
        for window in ma_windows:
            df[f'ma_{window}'] = df[self.target_column].rolling(
                window=window, 
                min_periods=1
            ).mean()
        
        # Tendencia (cambio en demanda)
        df['trend'] = df[self.target_column].diff()
        
        # Desviación estándar móvil (volatilidad demanda)
        df['std_7'] = df[self.target_column].rolling(
            window=7, 
            min_periods=1
        ).std()
        
        # FIX CRÍTICO: Usar fillna() con estrategia forward-fill + backward-fill
        # En lugar de dropna() que elimina demasiados registros
        
        # Rellenar NaN en lags con forward fill (propagar último valor conocido)
        for lag in lag_periods:
            df[f'lag_{lag}'] = df[f'lag_{lag}'].fillna(method='ffill').fillna(method='bfill')
        
        # Rellenar NaN en moving averages
        for window in ma_windows:
            df[f'ma_{window}'] = df[f'ma_{window}'].fillna(method='bfill')
        
        # Rellenar tendencia y std
        df['trend'] = df['trend'].fillna(0)
        df['std_7'] = df['std_7'].fillna(df[self.target_column].std())
        
        # Verificar que no queden NaN críticos
        # Solo eliminar filas con NaN en el target
        df = df[df[self.target_column].notna()].copy()
        
        return df
    
    def walk_forward_validation(self, algorithm_name, horizon):
        """
        Validación walk-forward para un algoritmo y horizonte específico
        
        Metodología:
        1. Ventana inicial: 60 días entrenamiento
        2. Cada fold: expandir ventana +7 días, predecir siguiente horizonte
        3. Continuar hasta agotar datos disponibles
        
        Parameters:
        -----------
        algorithm_name : str
            Nombre del algoritmo ('XGBoost', 'LightGBM', 'CatBoost')
        horizon : int
            Horizonte de pronóstico en días (7, 14, 28)
            
        Returns:
        --------
        metrics : dict
            Métricas agregadas (MAE, MAPE, sesgo, tiempo)
        """
        
        print("\n" + "="*70)
        print(f"  VALIDACIÓN: {algorithm_name} - Horizonte {horizon} días")
        print("="*70)
        
        fold_metrics = []
        training_times = []
        
        # Calcular número de folds posibles
        total_days = len(self.data)
        n_folds = (total_days - self.initial_train_size - horizon) // self.step_size + 1
        n_folds = max(1, n_folds)  # Al menos 1 fold
        
        print(f"  • Folds a ejecutar: {n_folds}")
        
        for fold_idx in range(n_folds):
            try:
                # Definir tamaño de ventana de entrenamiento (expanding window)
                train_end_idx = self.initial_train_size + (fold_idx * self.step_size)
                test_start_idx = train_end_idx
                test_end_idx = test_start_idx + horizon
                
                # Validar que hay suficientes datos
                if test_end_idx > len(self.data):
                    break
                
                # Extraer datos de train y test
                train_data = self.data.iloc[:train_end_idx].copy()
                test_data = self.data.iloc[test_start_idx:test_end_idx].copy()
                
                # Validación mínima de datos
                if len(train_data) < 30 or len(test_data) == 0:
                    continue
                
                # Feature engineering
                train_features = self.create_features(train_data, horizon)
                test_features = self.create_features(test_data, horizon)
                
                # Preparar X, y
                feature_cols = [col for col in train_features.columns 
                               if col not in [self.target_column, self.date_column]]
                
                # Validar que las features existen
                if len(feature_cols) == 0:
                    print(f"  ⚠ Fold {fold_idx + 1}: Sin features válidas")
                    continue
                
                X_train = train_features[feature_cols]
                y_train = train_features[self.target_column]
                X_test = test_features[feature_cols]
                y_test = test_features[self.target_column]
                
                # Validar que X_train y X_test tienen las mismas columnas
                missing_cols = set(X_train.columns) - set(X_test.columns)
                if missing_cols:
                    print(f"  ⚠ Fold {fold_idx + 1}: Columnas faltantes en test: {missing_cols}")
                    continue
                
                # Entrenar con timing
                start_time = time.time()
                model = self.algorithms[algorithm_name]
                model.fit(X_train, y_train)
                training_time = time.time() - start_time
                training_times.append(training_time)
                
                # Predicción
                y_pred = model.predict(X_test)
                
                # Calcular métricas fold
                mae = mean_absolute_error(y_test, y_pred)
                
                # MAPE con manejo de ceros
                mape = np.mean(np.abs((y_test - y_pred) / np.where(y_test == 0, 1, y_test))) * 100
                
                # Sesgo (bias)
                bias = np.mean(y_pred - y_test)
                
                fold_metrics.append({
                    'fold': fold_idx + 1,
                    'mae': mae,
                    'mape': mape,
                    'bias': bias,
                    'train_size': len(train_data),
                    'test_size': len(test_data)
                })
                
                print(f"  Fold {fold_idx + 1}/{n_folds}: MAE={mae:.2f}, MAPE={mape:.1f}%, Sesgo={bias:.2f}, Tiempo={training_time:.2f}s")
                
            except Exception as e:
                print(f"  ⚠ ERROR en Fold {fold_idx + 1}: {str(e)}")
                continue
        
        # Métricas agregadas
        if len(fold_metrics) == 0:
            print(f"  ⚠ Sin folds válidos para {algorithm_name} - Horizonte {horizon}")
            return None
        
        df_metrics = pd.DataFrame(fold_metrics)
        
        final_metrics = {
            'algorithm': algorithm_name,
            'horizon': horizon,
            'mae': df_metrics['mae'].mean(),
            'mape': df_metrics['mape'].mean(),
            'bias': df_metrics['bias'].mean(),
            'mae_std': df_metrics['mae'].std(),
            'mape_std': df_metrics['mape'].std(),
            'avg_training_time': np.mean(training_times),
            'total_folds': len(fold_metrics)
        }
        
        print(f"\n  RESUMEN:")
        print(f"    MAE promedio:  {final_metrics['mae']:.2f} ± {final_metrics['mae_std']:.2f}")
        print(f"    MAPE promedio: {final_metrics['mape']:.1f}% ± {final_metrics['mape_std']:.1f}%")
        print(f"    Sesgo promedio: {final_metrics['bias']:.2f}")
        print(f"    Tiempo promedio: {final_metrics['avg_training_time']:.2f}s")
        
        return final_metrics
    
    def run_benchmarking(self):
        """
        Ejecutar benchmarking completo: 3 algoritmos × 3 horizontes = 9 validaciones
        
        Returns:
        --------
        results : pandas.DataFrame
            Tabla consolidada con todas las métricas
        """
        print("\n" + "="*70)
        print("  BENCHMARKING AUTOMATIZADO - GRADIENT BOOSTING")
        print("="*70)
        print(f"  Fecha ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Datos: {len(self.data)} registros")
        print(f"  Período: {self.data[self.date_column].min().date()} a {self.data[self.date_column].max().date()}")
        print(f"  Algoritmos: {list(self.algorithms.keys())}")
        print(f"  Horizontes: {self.horizons} días")
        print(f"  Validación: Walk-forward (ventana inicial {self.initial_train_size}d, step {self.step_size}d)")
        
        all_results = []
        
        for algorithm_name in self.algorithms.keys():
            for horizon in self.horizons:
                try:
                    metrics = self.walk_forward_validation(algorithm_name, horizon)
                    if metrics:
                        all_results.append(metrics)
                except Exception as e:
                    print(f"\n  ⚠ ERROR {algorithm_name}-{horizon}días: {str(e)}")
                    continue
        
        if len(all_results) == 0:
            print("\n⚠ No se generaron resultados válidos")
            return pd.DataFrame()
        
        results_df = pd.DataFrame(all_results)
        self.results = results_df
        
        return results_df
    
    def generate_comparison_report(self):
        """
        Generar reporte comparativo consolidado
        """
        if self.results.empty:
            return
        
        print("\n" + "="*70)
        print("  REPORTE COMPARATIVO FINAL")
        print("="*70)
        
        # Tabla comparativa por horizonte
        for horizon in self.horizons:
            horizon_data = self.results[self.results['horizon'] == horizon]
            
            if len(horizon_data) == 0:
                continue
            
            print(f"\n  HORIZONTE {horizon} DÍAS:")
            print(f"  {'-'*66}")
            print(f"  {'Algoritmo':<15} {'MAE':<12} {'MAPE (%)':<12} {'Sesgo':<12} {'Tiempo (s)':<12}")
            print(f"  {'-'*66}")
            
            for _, row in horizon_data.iterrows():
                print(f"  {row['algorithm']:<15} {row['mae']:<12.2f} {row['mape']:<12.1f} {row['bias']:<12.2f} {row['avg_training_time']:<12.2f}")
        
        # Ranking general (promedio de los 3 horizontes)
        print(f"\n  RANKING GENERAL (promedio 3 horizontes):")
        print(f"  {'-'*50}")
        
        ranking = self.results.groupby('algorithm').agg({
            'mae': 'mean',
            'mape': 'mean',
            'bias': lambda x: np.abs(x).mean(),
            'avg_training_time': 'mean'
        }).sort_values('mae')
        
        for idx, (algo, row) in enumerate(ranking.iterrows(), 1):
            print(f"  {idx}. {algo:<15} MAE={row['mae']:.2f}, MAPE={row['mape']:.1f}%")
    
    def export_results(self):
        """
        Exportar resultados a CSV con timestamp
        """
        if self.results.empty:
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'benchmarking_results_{timestamp}.csv'
        
        self.results.to_csv(filename, index=False, encoding='utf-8')
        print(f"\n✓ Resultados exportados: {filename}")

# =============================================================================
# GENERACIÓN DE DATOS SINTÉTICOS (FALLBACK)
# =============================================================================

def generate_synthetic_data(n_skus=5, days=90, seed=42):
    """
    Generar datos sintéticos si no hay datos reales disponibles
    
    Parameters:
    -----------
    n_skus : int
        Número de SKUs a generar
    days : int
        Número de días de historia
    seed : int
        Semilla aleatoria para reproducibilidad
        
    Returns:
    --------
    data : pandas.DataFrame
        Datos sintéticos con columnas: fecha, sku, demanda
    """
    np.random.seed(seed)
    
    start_date = datetime.now() - timedelta(days=days)
    dates = [start_date + timedelta(days=i) for i in range(days)]
    
    data = []
    for sku_id in range(1, n_skus + 1):
        base_demand = np.random.uniform(50, 150)
        
        for date in dates:
            # Patrón semanal
            day_of_week = date.weekday()
            weekly_factor = 1.2 if day_of_week in [0, 4] else (0.7 if day_of_week in [5, 6] else 1.0)
            
            # Ruido aleatorio
            noise = np.random.normal(1, 0.3)
            
            # Demanda final
            demand = max(0, int(base_demand * weekly_factor * noise))
            
            data.append({
                'fecha': date.strftime('%Y-%m-%d'),
                'sku': f'MED{str(sku_id).zfill(3)}',
                'demanda': demand
            })
    
    return pd.DataFrame(data)

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """
    Script principal:
    1. Cargar datos reales (o generar sintéticos si no hay)
    2. Configurar protocolo de validación
    3. Setup algoritmos
    4. Ejecutar benchmarking (3 algoritmos × 3 horizontes)
    5. Generar reporte comparativo
    6. Exportar resultados
    """
    
    print("\n" + "="*70)
    print("  PROTOCOLO DE VALIDACIÓN WALK-FORWARD")
    print("="*70)
    print("  Farmacias Siman - San Pedro Sula")
    print("  Tesis: Modelo de Información con Capacidades Predictivas")
    print("  Objetivo Específico 2: Definir Técnicas de IA")
    print("="*70)
    
    # Intentar cargar datos reales
    try:
        print("\nIntentando cargar datos reales...")
        data = pd.read_csv('datos_farmacias_siman.csv')
        print(f"✓ Datos reales cargados: {len(data)} registros")
    except:
        print("\n⚠ Datos reales no disponibles")
        print("Generando datos sintéticos para demostración...")
        data = generate_synthetic_data(n_skus=5, days=90, seed=42)
    
    # Agregar demanda por fecha (suma de todos los SKUs por día)
    data_agg = data.groupby('fecha').agg({'demanda': 'sum'}).reset_index()
    
    print(f"\n✓ Datos agregados por fecha: {len(data_agg)} días")
    
    # Configurar protocolo de validación
    validator = ValidationProtocol(
        data=data_agg,
        target_column='demanda',
        date_column='fecha'
    )
    
    # Setup algoritmos
    validator.setup_algorithms()
    
    # Ejecutar benchmarking
    print("\nIniciando benchmarking...")
    results = validator.run_benchmarking()
    
    # Generar reporte comparativo
    if not results.empty:
        validator.generate_comparison_report()
        
        # Exportar resultados
        validator.export_results()
    else:
        print("\n⚠ No se generaron resultados válidos del benchmarking")
    
    print("\n" + "="*70)
    print("  EJECUCIÓN COMPLETADA")
    print("="*70)

# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    main()