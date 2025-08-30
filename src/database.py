"""
Conexión y operaciones con Supabase (MVP simplificado)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import pandas as pd
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from loguru import logger
import numpy as np

from src.config import get_settings


class DataRepository:
    """Repositorio de datos para operaciones CRUD con Supabase."""

    def __init__(self):
        settings = get_settings()
        try:
            # Un solo cliente con service key para todas las operaciones
            self.client: Client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_KEY,
                options=ClientOptions(
                    auto_refresh_token=False, 
                    persist_session=False
                )
            )
            self.settings = settings
            logger.info("DB (service) initialized.")
        except Exception as e:
            logger.error(f"DB init failed: {e}")
            raise

    def test_connection(self) -> bool:
        """Prueba de conexión a la base de datos."""
        try:
            self.client.table('sku_atc').select('sku').limit(1).execute()
            logger.info("Database connection successful")
            return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    # ============= SKU Operations =============

    def get_active_skus(self) -> pd.DataFrame:
        """Obtener SKUs activos."""
        try:
            result = self.client.table('sku_atc').select('*').execute()
            return pd.DataFrame(result.data) if result.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching SKUs: {e}")
            return pd.DataFrame()

    def get_sku_by_atc(self, atc_code: str) -> pd.DataFrame:
        """Obtener SKUs por prefijo de código ATC."""
        try:
            result = (
                self.client.table('sku_atc')
                .select('*')
                .like('atc_code', f'{atc_code}%')
                .execute()
            )
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
        """Obtener datos de ventas."""
        try:
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=self.settings.TRAINING_WINDOW_DAYS)

            query = self.client.table('ventas_diarias').select('*')

            if sku:
                query = query.eq('sku', sku)

            query = (
                query.gte('fecha', start_date.isoformat())
                .lte('fecha', end_date.isoformat())
                .order('fecha', desc=False)
            )

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
        """Obtener ventas agregadas."""
        df = self.get_sales_data(start_date=start_date, end_date=end_date)
        if df.empty:
            return df

        if group_by == 'sku':
            out = df.groupby('sku').agg({
                'unidades_vendidas': ['sum', 'mean', 'std'],
                'promo_flag': 'mean'
            }).round(3)
            out.columns = ['_'.join(c).strip() for c in out.columns.values]
            return out.reset_index()
        elif group_by == 'date':
            out = df.groupby('fecha').agg({
                'unidades_vendidas': 'sum'
            }).reset_index()
            return out
        else:
            return df

    # ============= Inventory Operations =============

    def get_current_inventory(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Obtener inventario actual."""
        try:
            query = (
                self.client.table('inventario_diario')
                .select('*')
                .gte('fecha', (date.today() - timedelta(days=7)).isoformat())
            )
            if sku:
                query = query.eq('sku', sku)

            result = query.order('fecha', desc=True).execute()
            if result.data:
                df = pd.DataFrame(result.data)
                df['fecha'] = pd.to_datetime(df['fecha'])
                df = df.sort_values('fecha', ascending=False).drop_duplicates(subset=['sku'], keep='first')
                return df.reset_index(drop=True)
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching inventory: {e}")
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
        """Guardar ejecución de modelo."""
        try:
            data = {
                'modelo': modelo,
                'version': version,
                'horizonte_dias': horizonte_dias,
                'ventana_entrenamiento_dias': ventana_entrenamiento_dias,
                'parametros': parametros,
                'notas': f"skus_procesados={skus_procesados}"
            }
            result = self.client.table('ejecuciones_modelo').insert(data).execute()
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
        """Actualizar ejecución de modelo."""
        try:
            notas_parts = [f"exito={exito}", f"skus_procesados={skus_procesados}"]
            if metricas_globales:
                notas_parts.append(f"metricas={metricas_globales}")
            if mensaje_error:
                notas_parts.append(f"error={mensaje_error}")

            self.client.table('ejecuciones_modelo') \
                .update({'notas': '; '.join(map(str, notas_parts))}) \
                .eq('run_id', run_id) \
                .execute()
            logger.info(f"Forecast run updated: {run_id}")
        except Exception as e:
            logger.error(f"Error updating forecast run: {e}")

    def save_forecasts(self, run_id: str, forecasts: pd.DataFrame):
        """Guardar pronósticos."""
        try:
            if forecasts.empty:
                return
            required = {'sku', 'fecha_objetivo', 'unidades_pronosticadas'}
            missing = required - set(map(str, forecasts.columns))
            if missing:
                raise ValueError(f"Missing forecast columns: {missing}")

            records = []
            for _, row in forecasts.iterrows():
                fecha_obj = row['fecha_objetivo']
                if isinstance(fecha_obj, (datetime, date)):
                    fecha_obj = fecha_obj.isoformat()
                records.append({
                    'run_id': run_id,
                    'sku': row['sku'],
                    'fecha_objetivo': fecha_obj,
                    'unidades_pronosticadas': float(row['unidades_pronosticadas'])
                })

            if records:
                self.client.table('forecast_historico').upsert(records, on_conflict="run_id, sku, fecha_objetivo").execute()
                logger.info(f"Saved {len(records)} forecasts for run {run_id}")

        except Exception as e:
            logger.error(f"Error saving forecasts: {e}")
            raise

    def save_metrics(self, run_id: str, metrics: pd.DataFrame):
        """Guardar métricas de backtesting."""
        try:
            if metrics.empty:
                return
            required = {'sku'}
            if not required.issubset(set(map(str, metrics.columns))):
                raise ValueError("Metrics must include 'sku' column")

            records = []
            for _, row in metrics.iterrows():
                rec = {
                    'run_id': run_id,
                    'sku': row['sku'],
                    'mape': float(row['mape']) if 'mape' in row and not pd.isna(row['mape']) else None,
                    'mae': float(row['mae']) if 'mae' in row and not pd.isna(row['mae']) else None,
                    'smape': float(row['smape']) if 'smape' in row and not pd.isna(row['smape']) else None,
                    'sesgo': float(row['sesgo']) if 'sesgo' in row and not pd.isna(row['sesgo']) else None,
                }
                records.append(rec)

            if records:
                self.client.table('metricas_backtesting').upsert(records, on_conflict="run_id, sku").execute()
                logger.info(f"Saved metrics for {len(records)} SKUs")

        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
            raise

    def get_latest_forecast(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Obtener pronósticos del último run."""
        try:
            query = self.client.table('v_forecast_latest').select('*')
            if sku:
                query = query.eq('sku', sku)
            result = query.execute()
            if result.data:
                df = pd.DataFrame(result.data)
                df['fecha_objetivo'] = pd.to_datetime(df['fecha_objetivo'])
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching latest forecast: {e}")
            return pd.DataFrame()

    def get_future_demand_agg(self) -> pd.DataFrame:
        """Obtener demanda futura agregada."""
        try:
            result = self.client.table('v_demanda_futura_7_14_28').select('*').execute()
            return pd.DataFrame(result.data) if result.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching future demand agg: {e}")
            return pd.DataFrame()

    # ============= Alert Operations =============

    def create_alert(
        self,
        sku: str,
        tipo_alerta: str,
        severidad: str,
        descripcion: str,
        fecha_objetivo: Optional[date] = None,
        lote_id: Optional[str] = None,
    ) -> bool:
        """Crear alerta."""
        try:
            data = {
                'sku': sku,
                'tipo_alerta': tipo_alerta,
                'severidad': severidad,
                'descripcion': descripcion,
            }
            if fecha_objetivo:
                data['fecha_objetivo'] = fecha_objetivo.isoformat()
            if lote_id:
                data['lote_id'] = lote_id

            result = self.client.table('alertas').insert(data).execute()
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
        """Obtener alertas activas."""
        try:
            query = (
                self.client.table('alertas')
                .select('*, sku_atc(nombre_producto)')
                .eq('resuelta', False)
            )
            if sku:
                query = query.eq('sku', sku)
            if tipo_alerta:
                query = query.eq('tipo_alerta', tipo_alerta)
            if severidad:
                query = query.eq('severidad', severidad)

            result = query.order('ts_creacion', desc=True).execute()
            return pd.DataFrame(result.data) if result.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching alerts: {e}")
            return pd.DataFrame()

    def acknowledge_alert(self, alert_id: str, comentario: Optional[str] = None) -> bool:
        try:
            if comentario is not None:
                self.client.rpc('ack_alert', {'p_id': alert_id, 'p_comment': comentario}).execute()
            else:
                self.client.rpc('ack_alert', {'p_id': alert_id}).execute()
            return True
        except Exception:
            try:
                self.client.rpc('ack_alert', {'p_id': alert_id}).execute()
                return True
            except Exception as e2:
                logger.error(f"ack_alert failed: {e2}")
                return False

    # ============= Batch Expiry Operations =============

    def get_expiring_batches(self, days_ahead: int = 30) -> pd.DataFrame:
        """Obtener lotes que caducan próximamente."""
        try:
            target_date = (date.today() + timedelta(days=days_ahead)).isoformat()
            result = (
                self.client.table('lotes_caducidad')
                .select('*, sku_atc(nombre_producto)')
                .lte('fecha_caducidad', target_date)
                .gt('unidades', 0)
                .order('fecha_caducidad')
                .execute()
            )
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

    def get_model_kpis(self) -> Dict[str, Any]:
        """Obtener KPIs del modelo."""
        try:
            result = self.client.table('v_kpi_modelo').select('*').execute()
            if result.data and len(result.data) > 0:
                row = result.data[0]
                out = dict(row)
                for k in ('mape_prom', 'mae_prom', 'sesgo_prom'):
                    if k in out and out[k] is not None:
                        out[k] = float(out[k])
                return out
            return {}
        except Exception as e:
            logger.error(f"Error fetching model KPIs: {e}")
            return {}

    def get_executive_summary(self) -> Dict[str, Any]:
        """Resumen ejecutivo (placeholder)."""
        return {}

    def get_inventory_status(self) -> pd.DataFrame:
        """Estado de inventario (placeholder)."""
        return pd.DataFrame()

    def get_abc_analysis(self) -> pd.DataFrame:
        """Análisis ABC (placeholder)."""
        return pd.DataFrame()

    # ============= Utility Methods =============

    def check_data_quality(self, sku: str) -> Dict[str, Any]:
        """Verificar calidad de datos para un SKU."""
        try:
            sales_df = self.get_sales_data(sku=sku)
            if sales_df.empty:
                return {
                    'sku': sku,
                    'has_data': False,
                    'message': 'No sales data available'
                }

            total_days = (sales_df['fecha'].max() - sales_df['fecha'].min()).days + 1
            actual_days = len(sales_df)
            completeness = actual_days / total_days if total_days > 0 else 0

            Q1 = sales_df['unidades_vendidas'].quantile(0.25)
            Q3 = sales_df['unidades_vendidas'].quantile(0.75)
            IQR = Q3 - Q1
            outliers = sales_df[
                (sales_df['unidades_vendidas'] < Q1 - 1.5 * IQR) |
                (sales_df['unidades_vendidas'] > Q3 + 1.5 * IQR)
            ]
            outlier_pct = len(outliers) / len(sales_df) if len(sales_df) > 0 else 0

            sufficient_data = (
                actual_days >= self.settings.MIN_TRAINING_SAMPLES and
                completeness >= self.settings.MIN_DATA_COMPLETENESS and
                outlier_pct <= self.settings.MAX_OUTLIER_PERCENTAGE
            )

            return {
                'sku': sku,
                'has_data': True,
                'total_days': int(total_days),
                'actual_days': int(actual_days),
                'completeness': round(float(completeness), 3),
                'outlier_percentage': round(float(outlier_pct), 3),
                'mean_sales': round(float(sales_df['unidades_vendidas'].mean()), 2),
                'std_sales': round(float(sales_df['unidades_vendidas'].std() or 0), 2),
                'sufficient_for_training': bool(sufficient_data)
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
        """Comparar pronósticos vs ventas reales."""
        try:
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=30)

            forecast_df = self.get_latest_forecast(sku=sku)
            if forecast_df.empty:
                return pd.DataFrame()

            forecast_df = forecast_df[
                (forecast_df['fecha_objetivo'] >= pd.Timestamp(start_date)) &
                (forecast_df['fecha_objetivo'] <= pd.Timestamp(end_date))
            ][['fecha_objetivo', 'unidades_pronosticadas']].copy()

            sales_df = self.get_sales_data(
                sku=sku,
                start_date=start_date,
                end_date=end_date
            )
            if sales_df.empty:
                comparison_df = forecast_df.rename(columns={'fecha_objetivo': 'fecha'})
                comparison_df['unidades_vendidas'] = np.nan
                comparison_df['error'] = np.nan
                comparison_df['error_pct'] = np.nan
                return comparison_df

            comparison_df = pd.merge(
                forecast_df,
                sales_df[['fecha', 'unidades_vendidas']],
                left_on='fecha_objetivo',
                right_on='fecha',
                how='left'
            ).drop(columns=['fecha'])

            comparison_df.rename(columns={'fecha_objetivo': 'fecha'}, inplace=True)
            comparison_df['error'] = comparison_df['unidades_vendidas'] - comparison_df['unidades_pronosticadas']
            denom = comparison_df['unidades_vendidas'].replace({0: np.nan})
            comparison_df['error_pct'] = (comparison_df['error'] / denom) * 100.0

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