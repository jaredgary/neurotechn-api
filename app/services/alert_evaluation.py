"""
Servicio de Evaluación de Alertas
Adapta la lógica de SCRIPT_PYTHON_UTILIDAD_DE_ALERTAS.py para SaaS genérico
"""

from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AlertEvaluationService:
    """
    Servicio genérico de evaluación de alertas.

    Evalúa TODOS los SKUs en el catálogo (variable, no hardcodeado).
    Clasifica alertas según criterios de accionabilidad.
    """

    def __init__(
        self,
        lead_time_buffer: int = 2,
        safety_threshold: float = 1.0,
        min_confidence: float = 0.70,
        risk_critical_days: int = 7,
        risk_high_days: int = 10
    ):
        """
        Inicializa el servicio con umbrales configurables.

        Args:
            lead_time_buffer: Días adicionales al lead time para anticipación
            safety_threshold: Multiplicador de stock de seguridad
            min_confidence: Confianza mínima para que alerta sea accionable (0-1)
            risk_critical_days: Umbral para riesgo CRITICAL (<N días)
            risk_high_days: Umbral para riesgo HIGH (<N días)
        """
        self.lead_time_buffer = lead_time_buffer
        self.safety_threshold = safety_threshold
        self.min_confidence = min_confidence
        self.risk_critical_days = risk_critical_days
        self.risk_high_days = risk_high_days

    async def evaluate_all_alerts(
        self,
        catalogo_df: pd.DataFrame,
        ventas_df: pd.DataFrame,
        prediction_horizons: List[int] = [7, 14]
    ) -> pd.DataFrame:
        """
        Evalúa alertas para TODOS los SKUs en el catálogo.

        Args:
            catalogo_df: DataFrame con catálogo de medicamentos
            ventas_df: DataFrame con ventas históricas
            prediction_horizons: Lista de horizontes de predicción

        Returns:
            DataFrame con evaluación de alertas
        """
        results = []

        # Obtener lista de SKUs (variable, no hardcodeado)
        skus = catalogo_df['sku'].unique()
        total_skus = len(skus)

        logger.info(f"🔍 Evaluando alertas para {total_skus} SKUs")
        logger.info(f"   Horizontes: {prediction_horizons}")
        logger.info(f"   Lead time buffer: {self.lead_time_buffer} días")
        logger.info(f"   Safety threshold: {self.safety_threshold}x")
        logger.info(f"   Min confidence: {self.min_confidence}")

        for idx, sku in enumerate(skus, 1):
            sku_config = self._get_sku_config(catalogo_df, sku)
            sku_ventas = ventas_df[ventas_df['sku'] == sku]

            if sku_ventas.empty:
                logger.warning(f"   ⚠️  SKU {sku}: Sin datos de ventas, omitiendo")
                continue

            # Estimar stock actual
            current_stock = self._estimate_current_stock(sku_ventas)

            # Evaluar para cada horizonte
            for horizon in prediction_horizons:
                alert_eval = self._evaluate_single_alert(
                    sku=sku,
                    config=sku_config,
                    current_stock=current_stock,
                    ventas_df=sku_ventas,
                    horizon=horizon
                )
                results.append(alert_eval)

            if idx % 20 == 0:
                logger.info(f"   Procesado {idx}/{total_skus} SKUs")

        logger.info(f"✅ Evaluación completada: {len(results)} alertas evaluadas")

        return pd.DataFrame(results)

    def _get_sku_config(self, catalogo_df: pd.DataFrame, sku: str) -> Dict:
        """
        Obtiene configuración de un SKU del catálogo.

        Args:
            catalogo_df: DataFrame del catálogo
            sku: SKU a buscar

        Returns:
            Diccionario con configuración del SKU
        """
        row = catalogo_df[catalogo_df['sku'] == sku].iloc[0]
        return {
            'lead_time': int(row['lead_time_dias']),
            'safety_stock': int(row['stock_seguridad']),
            'min_order': int(row['lote_minimo']),
            'category': row['grupo_terapeutico'],
            'is_essential': bool(row.get('es_esencial', False))
        }

    def _estimate_current_stock(self, ventas_df: pd.DataFrame) -> float:
        """
        Estima stock actual basado en ventas recientes.

        En un sistema real, esto vendría de inventarios_actuales.
        Para evaluación, usamos suma de últimos 7 días como proxy.

        Args:
            ventas_df: DataFrame de ventas del SKU

        Returns:
            Estimación de stock actual
        """
        ventas_df = ventas_df.copy()
        ventas_df['fecha'] = pd.to_datetime(ventas_df['fecha'])
        max_date = ventas_df['fecha'].max()

        # Usar suma de últimos 7 días como proxy de stock inicial
        recent = ventas_df[ventas_df['fecha'] >= max_date - timedelta(days=7)]
        return float(recent['demanda'].sum())

    def _evaluate_single_alert(
        self,
        sku: str,
        config: Dict,
        current_stock: float,
        ventas_df: pd.DataFrame,
        horizon: int
    ) -> Dict:
        """
        Evalúa una alerta individual según criterios de accionabilidad.

        Args:
            sku: SKU a evaluar
            config: Configuración del SKU
            current_stock: Stock actual estimado
            ventas_df: DataFrame de ventas del SKU
            horizon: Horizonte de predicción en días

        Returns:
            Diccionario con evaluación completa
        """
        # Calcular demanda proyectada
        avg_daily_demand = float(ventas_df['demanda'].mean())
        predicted_demand = avg_daily_demand * horizon
        predicted_stock = max(0, current_stock - predicted_demand)

        # Calcular confianza basada en variabilidad de demanda
        demand_std = float(ventas_df['demanda'].std())
        demand_cv = demand_std / avg_daily_demand if avg_daily_demand > 0 else 1
        # Confianza inversa a variabilidad (CV alto = confianza baja)
        confidence = max(0.6, min(0.95, 1 - (demand_cv * 0.5)))

        # Extraer configuración
        lead_time = config['lead_time']
        safety_stock = config['safety_stock']
        min_order = config['min_order']

        # Criterio 1: Cumple lead time de anticipación
        min_anticipation = lead_time + self.lead_time_buffer
        meets_lead_time = horizon >= min_anticipation

        # Criterio 2: Stock proyectado bajo umbral de seguridad
        safety_threshold_value = safety_stock * self.safety_threshold
        below_safety = predicted_stock < safety_threshold_value

        # Criterio 3: Cumple confianza mínima
        meets_confidence = confidence >= self.min_confidence

        # Criterio 4: Cantidad recomendada cumple lote mínimo
        stock_deficit = max(0, safety_threshold_value - predicted_stock)
        recommended_qty = max(min_order, stock_deficit * 1.2)  # +20% buffer
        meets_min_order = recommended_qty >= min_order

        # Determinar si es accionable (cumple TODOS los criterios)
        is_actionable = all([
            meets_lead_time,
            below_safety,
            meets_confidence,
            meets_min_order
        ])

        # Calcular días hasta stockout
        if avg_daily_demand > 0:
            days_until_stockout = int(current_stock / avg_daily_demand)
        else:
            days_until_stockout = horizon + 10  # Valor por defecto si no hay demanda

        # Clasificar nivel de riesgo (usando umbrales configurables)
        if days_until_stockout < self.risk_critical_days:
            risk_level = 'CRITICAL'
        elif days_until_stockout < self.risk_high_days:
            risk_level = 'HIGH'
        else:
            risk_level = 'MEDIUM'

        # Calcular score de urgencia (0-1, donde 1 = máxima urgencia)
        urgency_score = max(0, min(1, 1.0 - (days_until_stockout / 14)))

        # Determinar prioridad textual
        if risk_level == 'CRITICAL':
            priority_level = 'ALTA'
        elif risk_level == 'HIGH':
            priority_level = 'MEDIA'
        else:
            priority_level = 'BAJA'

        # Calcular fecha límite para ordenar
        days_to_order = max(1, days_until_stockout - lead_time)
        order_by_date = (datetime.now() + timedelta(days=days_to_order)).date()

        return {
            'sku': sku,
            'category': config['category'],
            'is_essential': config['is_essential'],
            'alert_date': datetime.now().date().isoformat(),
            'prediction_horizon': horizon,
            'is_actionable': is_actionable,
            'risk_level': risk_level,
            'days_until_stockout': days_until_stockout,
            'urgency_score': round(urgency_score, 2),
            'priority_level': priority_level,
            'recommended_order_qty': round(recommended_qty, 1),
            'order_by_date': order_by_date.isoformat(),
            'current_stock': round(current_stock, 1),
            'predicted_stock': round(predicted_stock, 1),
            'predicted_demand': round(predicted_demand, 1),
            'avg_daily_demand': round(avg_daily_demand, 1),
            'safety_stock': safety_stock,
            'lead_time': lead_time,
            'prediction_confidence': round(confidence, 2),
            'meets_lead_time': meets_lead_time,
            'below_safety_threshold': below_safety,
            'meets_confidence': meets_confidence,
            'meets_min_order': meets_min_order
        }


class AlertEvaluationResultsStorage:
    """
    Clase auxiliar para guardar resultados de evaluación en Supabase.
    """

    @staticmethod
    async def save_results(
        supabase_client,
        results_df: pd.DataFrame,
        clear_existing: bool = True
    ):
        """
        Guarda resultados de evaluación en tabla alert_evaluation_results.

        Args:
            supabase_client: Cliente de Supabase
            results_df: DataFrame con resultados
            clear_existing: Si True, elimina resultados previos
        """
        try:
            # Limpiar resultados anteriores si se solicita
            if clear_existing:
                logger.info("🗑️  Limpiando resultados de evaluación anteriores...")
                supabase_client.table('alert_evaluation_results').delete().neq('sku', '').execute()

            # Convertir a lista de diccionarios
            records = results_df.to_dict('records')

            # Insertar en batch
            batch_size = 500
            total_inserted = 0

            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                result = supabase_client.table('alert_evaluation_results').insert(batch).execute()
                total_inserted += len(batch)
                logger.info(f"   📝 Insertados {total_inserted}/{len(records)} registros")

            logger.info(f"✅ {total_inserted} resultados guardados en alert_evaluation_results")
            return True

        except Exception as e:
            logger.error(f"❌ Error guardando resultados: {e}")
            raise
