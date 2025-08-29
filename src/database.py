"""
Conexión y operaciones con Supabase
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, date
import pandas as pd
from supabase import create_client, Client
from loguru import logger
import asyncio
from functools import lru_cache
import numpy as np

from config import get_settings


class SupabaseConnection:
    """Gestor de conexión con Supabase"""
    
    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[Client] = None
        self._service_client: Optional[Client] = None
    
    @property
    def client(self) -> Client:
        """Cliente con key anónima para operaciones de lectura"""
        if not self._client:
            self._client = create_client(
                self.settings.SUPABASE_URL,
                self.settings.SUPABASE_KEY
            )
        return self._client
    
    @property
    def service_client(self) -> Client:
        """Cliente con service key para operaciones de escritura"""
        if not self._service_client and self.settings.SUPABASE_SERVICE_KEY:
            self._service_client = create_client(
                self.settings.SUPABASE_URL,
                self.settings.SUPABASE_SERVICE_KEY
            )
        return self._service_client or self.client
    
    def test_connection(self) -> bool:
        """Test database connection"""
        try:
            result = self.client.table('sku_atc').select('sku').limit(1).execute()
            logger.info("Database connection successful")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False


class DataRepository:
    """Repositorio de datos para operaciones CRUD"""
    
    def __init__(self):
        self.db = SupabaseConnection()
        self.settings = get_settings()
    
    # ============= SKU Operations =============
    
    def get_active_skus(self, essential_only: bool = False) -> pd.DataFrame:
        """Obtener SKUs activos"""
        try:
            query = self.db.client.table('sku_atc').select('*')
            
            if essential_only:
                query = query.eq('es_esencial', True)
            
            result = query.eq('activo', True).execute()
            
            if result.data:
                return pd.DataFrame(result.data)
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching SKUs: {e}")
            return pd.DataFrame()
    
    def get_sku_by_atc(self, atc_code: str) -> pd.DataFrame:
        """Obtener SKUs por código ATC"""
        try:
            result = self.db.client.table('sku_atc')\
                .select('*')\
                .like('atc_code', f'{atc_code}%')\
                .execute()
            
            return pd.DataFrame(result.data) if result.data else pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching SKUs by ATC: {e}")
            return pd.DataFrame()
    
    # ============= Sales Data Operations =============
    
    def get_sales_data(
        self,
        sku: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Obtener datos de ventas"""
        try:
            # Default date range: last 90 days
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=self.settings.TRAINING_WINDOW_DAYS)
            
            query = self.db.client.table('ventas_diarias').select('*')
            
            if sku:
                query = query.eq('sku', sku)
            
            query = query.gte('fecha', start_date.isoformat())\
                        .lte('fecha', end_date.isoformat())\
                        .order('fecha', desc=False)
            
            if limit:
                query = query.limit(limit)
            
            result = query.execute()
            
            if result.data:
                df = pd.DataFrame(result.data)
                df['fecha'] = pd.to_datetime(df['fecha'])
                return df
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching sales data: {e}")
            return pd.DataFrame()
    
    def get_aggregated_sales(
        self,
        group_by: str = 'sku',
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """Obtener ventas agregadas"""
        df = self.get_sales_data(start_date=start_date, end_date=end_date)
        
        if df.empty:
            return df
        
        if group_by == 'sku':
            return df.groupby('sku').agg({
                'unidades_vendidas': ['sum', 'mean', 'std'],
                'monto_total': 'sum',
                'promo_flag': 'mean'
            }).round(2)
        elif group_by == 'date':
            return df.groupby('fecha').agg({
                'unidades_vendidas': 'sum',
                'monto_total': 'sum'
            })
        else:
            return df
    
    # ============= Inventory Operations =============
    
    def get_current_inventory(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Obtener inventario actual"""
        try:
            # Get latest inventory for each SKU
            query = """
                SELECT DISTINCT ON (sku) 
                    sku, fecha, unidades_stock, stock_seguridad, 
                    stock_transito, dias_cobertura
                FROM inventario_diario
                WHERE fecha >= current_date - interval '7 days'
                ORDER BY sku, fecha DESC
            """
            
            result = self.db.client.rpc('get_current_inventory', {}).execute()
            
            if result.data:
                df = pd.DataFrame(result.data)
                if sku:
                    df = df[df['sku'] == sku]
                return df
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching inventory: {e}")
            # Fallback to direct query
            return self._get_inventory_fallback(sku)
    
    def _get_inventory_fallback(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Fallback method for inventory"""
        try:
            query = self.db.client.table('inventario_diario')\
                .select('*')\
                .gte('fecha', (date.today() - timedelta(days=7)).isoformat())
            
            if sku:
                query = query.eq('sku', sku)
            
            result = query.order('fecha', desc=True).execute()
            
            if result.data:
                df = pd.DataFrame(result.data)
                # Get latest per SKU
                df['fecha'] = pd.to_datetime(df['fecha'])
                df = df.sort_values('fecha', ascending=False)\
                       .drop_duplicates(subset=['sku'], keep='first')
                return df
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error in inventory fallback: {e}")
            return pd.DataFrame()
    
    # ============= Forecast Operations =============
    
    def save_forecast_run(
        self,
        modelo: str,
        version: str,
        horizonte_dias: int,
        ventana_entrenamiento_dias: int,
        parametros: Dict[str, Any],
        skus_procesados: int = 0
    ) -> str:
        """Guardar ejecución de modelo"""
        try:
            data = {
                'modelo': modelo,
                'version': version,
                'horizonte_dias': horizonte_dias,
                'ventana_entrenamiento_dias': ventana_entrenamiento_dias,
                'parametros': parametros,
                'skus_procesados': skus_procesados,
                'ts_inicio': datetime.now().isoformat(),
                'exito': False
            }
            
            result = self.db.service_client.table('ejecuciones_modelo')\
                .insert(data)\
                .execute()
            
            if result.data:
                run_id = result.data[0]['run_id']
                logger.info(f"Forecast run created: {run_id}")
                return run_id
            
            raise Exception("No run_id returned")
            
        except Exception as e:
            logger.error(f"Error saving forecast run: {e}")
            raise
    
    def update_forecast_run(
        self,
        run_id: str,
        exito: bool,
        skus_procesados: int,
        metricas_globales: Optional[Dict[str, Any]] = None,
        mensaje_error: Optional[str] = None
    ):
        """Actualizar ejecución de modelo"""
        try:
            data = {
                'ts_fin': datetime.now().isoformat(),
                'exito': exito,
                'skus_procesados': skus_procesados
            }
            
            if metricas_globales:
                data['metricas_globales'] = metricas_globales
            
            if mensaje_error:
                data['mensaje_error'] = mensaje_error
            
            self.db.service_client.table('ejecuciones_modelo')\
                .update(data)\
                .eq('run_id', run_id)\
                .execute()
            
            logger.info(f"Forecast run updated: {run_id}")
            
        except Exception as e:
            logger.error(f"Error updating forecast run: {e}")
    
    def save_forecasts(
        self,
        run_id: str,
        forecasts: pd.DataFrame
    ):
        """Guardar pronósticos
        
        Args:
            run_id: ID de la ejecución
            forecasts: DataFrame con columnas [sku, fecha_objetivo, unidades_pronosticadas, ...]
        """
        try:
            # Prepare data for insertion
            records = []
            for _, row in forecasts.iterrows():
                record = {
                    'run_id': run_id,
                    'sku': row['sku'],
                    'fecha_objetivo': row['fecha_objetivo'].isoformat() if isinstance(row['fecha_objetivo'], (datetime, date)) else row['fecha_objetivo'],
                    'unidades_pronosticadas': float(row['unidades_pronosticadas'])
                }
                
                # Optional fields
                if 'limite_inferior' in row:
                    record['limite_inferior'] = float(row['limite_inferior'])
                if 'limite_superior' in row:
                    record['limite_superior'] = float(row['limite_superior'])
                if 'probabilidad_quiebre' in row:
                    record['probabilidad_quiebre'] = float(row['probabilidad_quiebre'])
                if 'features_importancia' in row:
                    record['features_importancia'] = row['features_importancia']
                
                records.append(record)
            
            # Batch insert
            if records:
                self.db.service_client.table('forecast_historico')\
                    .insert(records)\
                    .execute()
                
                logger.info(f"Saved {len(records)} forecasts for run {run_id}")
            
        except Exception as e:
            logger.error(f"Error saving forecasts: {e}")
            raise
    
    def save_metrics(
        self,
        run_id: str,
        metrics: pd.DataFrame
    ):
        """Guardar métricas de backtesting
        
        Args:
            run_id: ID de la ejecución
            metrics: DataFrame con columnas [sku, mape, mae, rmse, ...]
        """
        try:
            records = []
            for _, row in metrics.iterrows():
                record = {
                    'run_id': run_id,
                    'sku': row['sku'],
                    'mape': float(row.get('mape', 0)) if not pd.isna(row.get('mape')) else None,
                    'mae': float(row.get('mae', 0)) if not pd.isna(row.get('mae')) else None,
                    'rmse': float(row.get('rmse', 0)) if not pd.isna(row.get('rmse')) else None,
                    'smape': float(row.get('smape', 0)) if not pd.isna(row.get('smape')) else None,
                    'sesgo': float(row.get('sesgo', 0)) if not pd.isna(row.get('sesgo')) else None,
                    'r2_score': float(row.get('r2_score', 0)) if not pd.isna(row.get('r2_score')) else None,
                    'n_observaciones': int(row.get('n_observaciones', 0))
                }
                
                if 'coverage_probability' in row:
                    record['coverage_probability'] = float(row['coverage_probability'])
                
                records.append(record)
            
            if records:
                self.db.service_client.table('metricas_backtesting')\
                    .insert(records)\
                    .execute()
                
                logger.info(f"Saved metrics for {len(records)} SKUs")
            
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
            raise
    
    def get_latest_forecast(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Obtener pronósticos más recientes"""
        try:
            query = """
                SELECT f.*, s.nombre_producto, s.atc_code, s.es_esencial
                FROM v_forecast_latest f
                JOIN sku_atc s ON s.sku = f.sku
                WHERE s.activo = true
            """
            
            if sku:
                query += f" AND f.sku = '{sku}'"
            
            result = self.db.client.rpc('get_latest_forecast', {
                'p_sku': sku
            } if sku else {}).execute()
            
            if result.data:
                df = pd.DataFrame(result.data)
                df['fecha_objetivo'] = pd.to_datetime(df['fecha_objetivo'])
                return df
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching latest forecast: {e}")
            return pd.DataFrame()
    
    # ============= Alert Operations =============
    
    def create_alert(
        self,
        sku: str,
        tipo_alerta: str,
        severidad: str,
        descripcion: str,
        accion_sugerida: Optional[str] = None,
        fecha_objetivo: Optional[date] = None,
        lote_id: Optional[str] = None,
        valor_metrica: Optional[float] = None,
        umbral_metrica: Optional[float] = None,
        impacto_estimado: Optional[float] = None
    ) -> bool:
        """Crear nueva alerta"""
        try:
            data = {
                'sku': sku,
                'tipo_alerta': tipo_alerta,
                'severidad': severidad,
                'descripcion': descripcion,
                'estado': 'PENDIENTE'
            }
            
            # Optional fields
            if accion_sugerida:
                data['accion_sugerida'] = accion_sugerida
            if fecha_objetivo:
                data['fecha_objetivo'] = fecha_objetivo.isoformat()
            if lote_id:
                data['lote_id'] = lote_id
            if valor_metrica is not None:
                data['valor_metrica'] = float(valor_metrica)
            if umbral_metrica is not None:
                data['umbral_metrica'] = float(umbral_metrica)
            if impacto_estimado is not None:
                data['impacto_estimado'] = float(impacto_estimado)
            
            result = self.db.service_client.table('alertas')\
                .insert(data)\
                .execute()
            
            if result.data:
                logger.info(f"Alert created for SKU {sku}: {tipo_alerta}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            return False
    
    def get_active_alerts(
        self,
        sku: Optional[str] = None,
        tipo_alerta: Optional[str] = None,
        severidad: Optional[str] = None
    ) -> pd.DataFrame:
        """Obtener alertas activas"""
        try:
            query = self.db.client.table('alertas')\
                .select('*, sku_atc(nombre_producto, es_esencial)')\
                .in_('estado', ['PENDIENTE', 'EN_REVISION'])
            
            if sku:
                query = query.eq('sku', sku)
            if tipo_alerta:
                query = query.eq('tipo_alerta', tipo_alerta)
            if severidad:
                query = query.eq('severidad', severidad)
            
            result = query.order('ts_creacion', desc=True).execute()
            
            if result.data:
                return pd.DataFrame(result.data)
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching alerts: {e}")
            return pd.DataFrame()
    
    def acknowledge_alert(
        self,
        alert_id: str,
        user_id: Optional[str] = None,
        comentario: Optional[str] = None
    ) -> bool:
        """Reconocer/resolver una alerta"""
        try:
            result = self.db.service_client.rpc('ack_alert', {
                'p_id': alert_id,
                'p_comentario': comentario
            }).execute()
            
            logger.info(f"Alert {alert_id} acknowledged")
            return True
            
        except Exception as e:
            logger.error(f"Error acknowledging alert: {e}")
            return False
    
    # ============= Batch Expiry Operations =============
    
    def get_expiring_batches(self, days_ahead: int = 30) -> pd.DataFrame:
        """Obtener lotes próximos a vencer"""
        try:
            target_date = (date.today() + timedelta(days=days_ahead)).isoformat()
            
            result = self.db.client.table('lotes_caducidad')\
                .select('*, sku_atc(nombre_producto, es_esencial, costo_unitario)')\
                .lte('fecha_caducidad', target_date)\
                .gt('unidades', 0)\
                .order('fecha_caducidad')\
                .execute()
            
            if result.data:
                df = pd.DataFrame(result.data)
                df['fecha_caducidad'] = pd.to_datetime(df['fecha_caducidad'])
                df['dias_hasta_vencimiento'] = (df['fecha_caducidad'] - pd.Timestamp.today()).dt.days
                return df
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching expiring batches: {e}")
            return pd.DataFrame()
    
    # ============= Dashboard Data Operations =============
    
    def get_executive_summary(self) -> Dict[str, Any]:
        """Obtener resumen ejecutivo para dashboard"""
        try:
            result = self.db.client.rpc('get_executive_summary', {}).execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            
            # Fallback to view
            result = self.db.client.table('v_resumen_ejecutivo')\
                .select('*')\
                .execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            
            return {}
            
        except Exception as e:
            logger.error(f"Error fetching executive summary: {e}")
            return {}
    
    def get_inventory_status(self) -> pd.DataFrame:
        """Obtener estado del inventario"""
        try:
            result = self.db.client.table('v_estado_inventario')\
                .select('*')\
                .execute()
            
            if result.data:
                return pd.DataFrame(result.data)
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching inventory status: {e}")
            return pd.DataFrame()
    
    def get_model_kpis(self) -> Dict[str, Any]:
        """Obtener KPIs del modelo"""
        try:
            result = self.db.client.table('v_kpi_modelo')\
                .select('*')\
                .execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            return {}
            
        except Exception as e:
            logger.error(f"Error fetching model KPIs: {e}")
            return {}
    
    def get_abc_analysis(self) -> pd.DataFrame:
        """Obtener análisis ABC de productos"""
        try:
            result = self.db.client.table('v_analisis_abc')\
                .select('*')\
                .execute()
            
            if result.data:
                return pd.DataFrame(result.data)
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Error fetching ABC analysis: {e}")
            return pd.DataFrame()
    
    # ============= Utility Methods =============
    
    def check_data_quality(self, sku: str) -> Dict[str, Any]:
        """Verificar calidad de datos para un SKU"""
        try:
            # Get sales data
            sales_df = self.get_sales_data(sku=sku)
            
            if sales_df.empty:
                return {
                    'sku': sku,
                    'has_data': False,
                    'message': 'No sales data available'
                }
            
            # Calculate metrics
            total_days = (sales_df['fecha'].max() - sales_df['fecha'].min()).days + 1
            actual_days = len(sales_df)
            completeness = actual_days / total_days if total_days > 0 else 0
            
            # Check for outliers using IQR
            Q1 = sales_df['unidades_vendidas'].quantile(0.25)
            Q3 = sales_df['unidades_vendidas'].quantile(0.75)
            IQR = Q3 - Q1
            outliers = sales_df[
                (sales_df['unidades_vendidas'] < Q1 - 1.5 * IQR) |
                (sales_df['unidades_vendidas'] > Q3 + 1.5 * IQR)
            ]
            outlier_pct = len(outliers) / len(sales_df) if len(sales_df) > 0 else 0
            
            # Check if sufficient data
            sufficient_data = (
                actual_days >= self.settings.MIN_TRAINING_SAMPLES and
                completeness >= self.settings.MIN_DATA_COMPLETENESS and
                outlier_pct <= self.settings.MAX_OUTLIER_PERCENTAGE
            )
            
            return {
                'sku': sku,
                'has_data': True,
                'total_days': total_days,
                'actual_days': actual_days,
                'completeness': round(completeness, 3),
                'outlier_percentage': round(outlier_pct, 3),
                'mean_sales': round(sales_df['unidades_vendidas'].mean(), 2),
                'std_sales': round(sales_df['unidades_vendidas'].std(), 2),
                'sufficient_for_training': sufficient_data
            }
            
        except Exception as e:
            logger.error(f"Error checking data quality for {sku}: {e}")
            return {
                'sku': sku,
                'has_data': False,
                'error': str(e)
            }
    
    def get_forecast_comparison(
        self,
        sku: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> pd.DataFrame:
        """Comparar pronósticos vs ventas reales"""
        try:
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            # Get forecasts
            forecast_df = self.get_latest_forecast(sku=sku)
            
            if forecast_df.empty:
                return pd.DataFrame()
            
            # Filter by date range
            forecast_df = forecast_df[
                (forecast_df['fecha_objetivo'] >= pd.Timestamp(start_date)) &
                (forecast_df['fecha_objetivo'] <= pd.Timestamp(end_date))
            ]
            
            # Get actual sales
            sales_df = self.get_sales_data(
                sku=sku,
                start_date=start_date,
                end_date=end_date
            )
            
            if sales_df.empty:
                return forecast_df
            
            # Merge forecast and actual
            comparison_df = pd.merge(
                forecast_df[['fecha_objetivo', 'unidades_pronosticadas', 
                           'limite_inferior', 'limite_superior']],
                sales_df[['fecha', 'unidades_vendidas']],
                left_on='fecha_objetivo',
                right_on='fecha',
                how='left'
            )
            
            # Calculate error metrics
            comparison_df['error'] = (
                comparison_df['unidades_vendidas'] - 
                comparison_df['unidades_pronosticadas']
            )
            comparison_df['error_pct'] = (
                comparison_df['error'] / 
                comparison_df['unidades_vendidas'].replace(0, np.nan) * 100
            )
            comparison_df['within_interval'] = (
                (comparison_df['unidades_vendidas'] >= comparison_df['limite_inferior']) &
                (comparison_df['unidades_vendidas'] <= comparison_df['limite_superior'])
            )
            
            return comparison_df
            
        except Exception as e:
            logger.error(f"Error comparing forecast vs actual: {e}")
            return pd.DataFrame()


# Singleton instance
_db_instance: Optional[DataRepository] = None


def get_db() -> DataRepository:
    """Get database repository instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DataRepository()
    return _db_instance