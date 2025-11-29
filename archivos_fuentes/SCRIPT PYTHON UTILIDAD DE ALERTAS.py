# EVALUADOR DE UTILIDAD DE ALERTAS ACCIONABLES - VERSIÓN CORREGIDA
# Sistema: Modelo de Información con Capacidades Predictivas - Farmacias Siman
# Objetivo: Evaluar utilidad operativa de alertas generadas por el sistema predictivo
# 
# CORRECCIÓN #8: Procesar todos los 120 SKUs (no solo 30)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CLASE PRINCIPAL: EVALUADOR DE UTILIDAD DE ALERTAS
# =============================================================================

class AlertUtilityEvaluator:
    """
    Evaluador de utilidad operativa para alertas de reposición de inventario
    farmacéutico basadas en predicciones de demanda
    """
    
    def __init__(self, sku_config: Dict, alert_criteria: Dict = None):
        """
        Inicializar evaluador de utilidad de alertas
        
        Parameters:
        -----------
        sku_config : dict
            Configuración por SKU: {sku: {'lead_time': int, 'safety_stock': int, 
                                         'min_order': int, 'category': str}}
        alert_criteria : dict, optional
            Criterios personalizados para alertas accionables
        """
        self.sku_config = sku_config
        self.alert_criteria = alert_criteria or self._default_alert_criteria()
        self.evaluation_results = {}
        
    def _default_alert_criteria(self) -> Dict:
        """Criterios por defecto para alertas accionables"""
        return {
            'min_confidence': 0.70,          # Confianza mínima predicción
            'lead_time_buffer': 2,           # Días adicionales al lead time
            'safety_stock_threshold': 1.0,   # Factor multiplicador stock seguridad
            'max_duplicate_window': 7        # Días para considerar duplicación
        }
    
    def evaluate_alert_actionability(self, 
                                   sku: str, 
                                   current_stock: float,
                                   predicted_stock: float,
                                   prediction_horizon: int,
                                   prediction_confidence: float = 1.0,
                                   alert_date: datetime = None) -> Dict:
        """
        Evaluar si una alerta es accionable según criterios de negocio
        
        Parameters:
        -----------
        sku : str
            Código del SKU
        current_stock : float
            Stock actual en unidades
        predicted_stock : float
            Stock proyectado en unidades
        prediction_horizon : int
            Horizonte de la predicción en días
        prediction_confidence : float
            Confianza de la predicción (0-1)
        alert_date : datetime, optional
            Fecha de la alerta (default: hoy)
            
        Returns:
        --------
        dict: Evaluación completa de la alerta
        """
        
        alert_date = alert_date or datetime.now()
        
        # Obtener configuración del SKU
        if sku not in self.sku_config:
            return self._create_error_response(sku, "SKU no configurado")
        
        config = self.sku_config[sku]
        
        # Extraer parámetros
        lead_time = config.get('lead_time', 7)
        safety_stock = config.get('safety_stock', 0)
        min_order_qty = config.get('min_order', 1)
        category = config.get('category', 'Unknown')
        
        # Criterios de evaluación
        criteria_results = {}
        
        # 1. Anticipación suficiente
        min_anticipation = lead_time + self.alert_criteria['lead_time_buffer']
        criteria_results['sufficient_lead_time'] = {
            'value': prediction_horizon >= min_anticipation,
            'required': min_anticipation,
            'actual': prediction_horizon,
            'description': f"Horizonte {prediction_horizon}d >= Lead time {lead_time}d + Buffer {self.alert_criteria['lead_time_buffer']}d"
        }
        
        # 2. Umbral crítico
        safety_threshold = safety_stock * self.alert_criteria['safety_stock_threshold']
        criteria_results['below_safety_threshold'] = {
            'value': predicted_stock < safety_threshold,
            'required': f"< {safety_threshold}",
            'actual': predicted_stock,
            'description': f"Stock proyectado {predicted_stock} < Stock seguridad {safety_threshold}"
        }
        
        # 3. Confianza mínima
        criteria_results['minimum_confidence'] = {
            'value': prediction_confidence >= self.alert_criteria['min_confidence'],
            'required': self.alert_criteria['min_confidence'],
            'actual': prediction_confidence,
            'description': f"Confianza {prediction_confidence:.2f} >= Mínimo {self.alert_criteria['min_confidence']}"
        }
        
        # 4. Viabilidad de acción
        stock_deficit = max(0, safety_threshold - predicted_stock)
        recommended_order = max(min_order_qty, stock_deficit * 1.2)  # 20% buffer adicional
        
        criteria_results['actionable_quantity'] = {
            'value': recommended_order >= min_order_qty,
            'required': min_order_qty,
            'actual': recommended_order,
            'description': f"Cantidad recomendada {recommended_order} >= Pedido mínimo {min_order_qty}"
        }
        
        # Evaluación general
        all_criteria_met = all(criteria['value'] for criteria in criteria_results.values())
        
        # Clasificación de riesgo
        days_until_stockout = self._estimate_days_until_stockout(
            current_stock, predicted_stock, prediction_horizon, config
        )
        
        risk_level = self._classify_risk_level(days_until_stockout)
        
        # Resultado consolidado
        alert_evaluation = {
            'sku': sku,
            'category': category,
            'alert_date': alert_date.isoformat(),
            'prediction_horizon': prediction_horizon,
            'is_actionable': all_criteria_met,
            'criteria_evaluation': criteria_results,
            'risk_assessment': {
                'risk_level': risk_level,
                'days_until_stockout': days_until_stockout,
                'urgency_score': self._calculate_urgency_score(days_until_stockout, prediction_confidence)
            },
            'recommendations': {
                'recommended_order_quantity': recommended_order,
                'order_by_date': (alert_date + timedelta(days=max(1, days_until_stockout - lead_time))).isoformat(),
                'priority_level': self._determine_priority_level(risk_level, all_criteria_met)
            },
            'context': {
                'current_stock': current_stock,
                'predicted_stock': predicted_stock,
                'safety_stock': safety_stock,
                'lead_time': lead_time,
                'prediction_confidence': prediction_confidence
            }
        }
        
        return alert_evaluation
    
    def _estimate_days_until_stockout(self, current_stock: float, predicted_stock: float, 
                                     horizon: int, config: Dict) -> int:
        """Estimar días hasta stockout basado en tendencia"""
        
        if current_stock <= 0:
            return 0
        
        if predicted_stock >= current_stock:
            return horizon + 10  # Stock estable o creciente
        
        # Calcular tasa de decline diaria
        daily_decline = (current_stock - predicted_stock) / horizon
        
        if daily_decline <= 0:
            return horizon + 10
        
        # Estimar días hasta llegar a stock de seguridad
        safety_stock = config.get('safety_stock', 0)
        days_to_safety = (current_stock - safety_stock) / daily_decline
        
        return max(0, int(days_to_safety))
    
    def _classify_risk_level(self, days_until_stockout: int) -> str:
        """Clasificar nivel de riesgo según días hasta stockout"""
        if days_until_stockout <= 3:
            return "CRITICAL"
        elif days_until_stockout <= 7:
            return "HIGH"
        elif days_until_stockout <= 14:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _calculate_urgency_score(self, days_until_stockout: int, confidence: float) -> float:
        """Calcular score de urgencia combinando riesgo y confianza"""
        # Score inverso: menos días = mayor urgencia
        time_score = max(0, 1 - (days_until_stockout / 30))
        # Combinar con confianza
        urgency = (time_score * 0.7) + (confidence * 0.3)
        return round(urgency, 2)
    
    def _determine_priority_level(self, risk_level: str, is_actionable: bool) -> str:
        """Determinar prioridad de la alerta"""
        if not is_actionable:
            return "NO_ACTION"
        
        priority_map = {
            "CRITICAL": "P1_URGENT",
            "HIGH": "P2_HIGH",
            "MEDIUM": "P3_NORMAL",
            "LOW": "P4_LOW"
        }
        
        return priority_map.get(risk_level, "P3_NORMAL")
    
    def _create_error_response(self, sku: str, error_message: str) -> Dict:
        """Crear respuesta de error estandarizada"""
        return {
            'sku': sku,
            'error': error_message,
            'is_actionable': False,
            'evaluation_status': 'ERROR'
        }
    
    def evaluate_alert_batch(self, alerts_df: pd.DataFrame) -> pd.DataFrame:
        """
        Evaluar un lote de alertas desde DataFrame
        
        Parameters:
        -----------
        alerts_df : pd.DataFrame
            DataFrame con columnas: sku, current_stock, predicted_stock, 
                                   prediction_horizon, prediction_confidence, alert_date
        
        Returns:
        --------
        pd.DataFrame: Resultados de evaluación consolidados
        """
        
        results = []
        
        for idx, row in alerts_df.iterrows():
            try:
                alert_date = pd.to_datetime(row['alert_date']) if 'alert_date' in row else datetime.now()
                
                evaluation = self.evaluate_alert_actionability(
                    sku=row['sku'],
                    current_stock=row['current_stock'],
                    predicted_stock=row['predicted_stock'],
                    prediction_horizon=int(row['prediction_horizon']),
                    prediction_confidence=row.get('prediction_confidence', 0.85),
                    alert_date=alert_date
                )
                
                # Extraer datos clave para DataFrame
                result_row = {
                    'sku': evaluation['sku'],
                    'category': evaluation.get('category', 'Unknown'),
                    'alert_date': evaluation['alert_date'],
                    'prediction_horizon': evaluation['prediction_horizon'],
                    'is_actionable': evaluation['is_actionable'],
                    'risk_level': evaluation['risk_assessment']['risk_level'],
                    'days_until_stockout': evaluation['risk_assessment']['days_until_stockout'],
                    'urgency_score': evaluation['risk_assessment']['urgency_score'],
                    'priority_level': evaluation['recommendations']['priority_level'],
                    'recommended_order_qty': evaluation['recommendations']['recommended_order_quantity'],
                    'order_by_date': evaluation['recommendations']['order_by_date'],
                    'current_stock': evaluation['context']['current_stock'],
                    'predicted_stock': evaluation['context']['predicted_stock'],
                    'safety_stock': evaluation['context']['safety_stock'],
                    'lead_time': evaluation['context']['lead_time'],
                    'prediction_confidence': evaluation['context']['prediction_confidence'],
                    # Criterios individuales
                    'meets_lead_time': evaluation['criteria_evaluation']['sufficient_lead_time']['value'],
                    'below_safety_threshold': evaluation['criteria_evaluation']['below_safety_threshold']['value'],
                    'meets_confidence': evaluation['criteria_evaluation']['minimum_confidence']['value'],
                    'meets_min_order': evaluation['criteria_evaluation']['actionable_quantity']['value']
                }
                
                results.append(result_row)
                
            except Exception as e:
                print(f"⚠ Error evaluando SKU {row.get('sku', 'Unknown')}: {str(e)}")
                continue
        
        return pd.DataFrame(results)
    
    def calculate_metrics(self, results_df: pd.DataFrame) -> Dict:
        """Calcular métricas agregadas de utilidad del sistema"""
        
        if len(results_df) == 0:
            return {}
        
        total_alerts = len(results_df)
        actionable_alerts = results_df['is_actionable'].sum()
        
        metrics = {
            'evaluation_summary': {
                'total_alerts_evaluated': total_alerts,
                'actionable_alerts': int(actionable_alerts),
                'non_actionable_alerts': total_alerts - int(actionable_alerts),
                'actionable_percentage': round((actionable_alerts / total_alerts) * 100, 1)
            },
            'criteria_performance': {
                'sufficient_lead_time': round(results_df['meets_lead_time'].mean() * 100, 1),
                'below_safety_threshold': round(results_df['below_safety_threshold'].mean() * 100, 1),
                'minimum_confidence': round(results_df['meets_confidence'].mean() * 100, 1),
                'actionable_quantity': round(results_df['meets_min_order'].mean() * 100, 1)
            },
            'risk_analysis': {
                'distribution': results_df['risk_level'].value_counts().to_dict(),
                'avg_days_until_stockout': round(results_df['days_until_stockout'].mean(), 1),
                'avg_urgency_score': round(results_df['urgency_score'].mean(), 2)
            },
            'operational_metrics': {
                'avg_recommended_order_qty': round(results_df['recommended_order_qty'].mean(), 1),
                'total_recommended_orders': int(results_df['recommended_order_qty'].sum()),
                'priority_distribution': results_df['priority_level'].value_counts().to_dict()
            },
            'category_performance': results_df['category'].value_counts().to_dict()
        }
        
        return metrics
    
    def generate_utility_report(self, results_df: pd.DataFrame, output_file: str = None) -> str:
        """Generar reporte textual de utilidad del sistema de alertas"""
        
        metrics = self.calculate_metrics(results_df)
        
        if not metrics:
            return "No hay datos para generar reporte"
        
        report_lines = [
            "="*70,
            "REPORTE DE UTILIDAD DE ALERTAS",
            "Sistema: Farmacias Siman - Alertas Predictivas",
            "="*70,
            "",
            "RESUMEN EJECUTIVO",
            "-"*30,
            f"Total de alertas evaluadas: {metrics['evaluation_summary']['total_alerts_evaluated']}",
            f"Alertas accionables: {metrics['evaluation_summary']['actionable_alerts']} "
            f"({metrics['evaluation_summary']['actionable_percentage']}%)",
            f"Alertas no accionables: {metrics['evaluation_summary']['non_actionable_alerts']}",
            "",
            "CUMPLIMIENTO DE CRITERIOS",
            "-"*30
        ]
        
        # Criterios
        for criterion, percentage in metrics['criteria_performance'].items():
            criterion_name = criterion.replace('_', ' ').title()
            report_lines.append(f"{criterion_name}: {percentage}%")
        
        report_lines.extend([
            "",
            "ANÁLISIS DE RIESGO",
            "-"*30,
            f"Días promedio hasta stockout: {metrics['risk_analysis']['avg_days_until_stockout']}",
            f"Score promedio de urgencia: {metrics['risk_analysis']['avg_urgency_score']}",
            "",
            "Distribución por nivel de riesgo:"
        ])
        
        # Distribución de riesgo
        for risk_level, count in metrics['risk_analysis']['distribution'].items():
            percentage = (count / metrics['evaluation_summary']['total_alerts_evaluated']) * 100
            report_lines.append(f"  {risk_level}: {count} alertas ({percentage:.1f}%)")
        
        report_lines.extend([
            "",
            "MÉTRICAS OPERACIONALES",
            "-"*30,
            f"Cantidad promedio recomendada: {metrics['operational_metrics']['avg_recommended_order_qty']} unidades",
            f"Total recomendado a ordenar: {metrics['operational_metrics']['total_recommended_orders']} unidades",
            "",
            "DISTRIBUCIÓN POR CATEGORÍA ATC",
            "-"*30
        ])
        
        # Distribución por categoría
        for category, count in metrics['category_performance'].items():
            percentage = (count / metrics['evaluation_summary']['total_alerts_evaluated']) * 100
            report_lines.append(f"{category}: {count} alertas ({percentage:.1f}%)")
        
        report_lines.extend([
            "",
            "RECOMENDACIONES",
            "-"*15,
            self._generate_recommendations(metrics),
            "",
            "="*70
        ])
        
        report_text = "\n".join(report_lines)
        
        # Guardar archivo si se especifica
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(report_text)
                print(f"✓ Reporte guardado en: {output_file}")
            except Exception as e:
                print(f"✗ Error guardando reporte: {str(e)}")
        
        return report_text
    
    def _generate_recommendations(self, metrics: Dict) -> str:
        """Generar recomendaciones basadas en métricas"""
        
        recommendations = []
        
        actionable_pct = metrics['evaluation_summary']['actionable_percentage']
        
        if actionable_pct >= 75:
            recommendations.append("✓ Excelente performance del sistema de alertas")
        elif actionable_pct >= 60:
            recommendations.append("⚠ Sistema funcional - Revisar criterios para optimización")
        else:
            recommendations.append("✗ Performance subóptima - Requiere ajuste de parámetros")
        
        # Recomendaciones específicas
        criteria_perf = metrics['criteria_performance']
        
        if criteria_perf['sufficient_lead_time'] < 80:
            recommendations.append("• Ajustar horizontes de predicción o lead times")
        
        if criteria_perf['minimum_confidence'] < 70:
            recommendations.append("• Mejorar calibración de confianza del modelo predictivo")
        
        if metrics['risk_analysis']['distribution'].get('CRITICAL', 0) > metrics['evaluation_summary']['total_alerts_evaluated'] * 0.2:
            recommendations.append("• Revisión urgente: Demasiadas alertas críticas")
        
        return "\n".join(recommendations)

# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def load_sku_config_from_catalog(catalog_file: str = 'catalogo_medicamentos.csv') -> Dict:
    """Cargar configuración de SKUs desde catálogo real"""
    
    try:
        catalog_df = pd.read_csv(catalog_file)
        
        sku_config = {}
        
        for _, row in catalog_df.iterrows():
            sku_config[row['sku']] = {
                'lead_time': int(row['lead_time_dias']),
                'safety_stock': int(row['stock_seguridad']),
                'min_order': int(row['lote_minimo']),
                'category': row['grupo_terapeutico']
            }
        
        return sku_config
        
    except Exception as e:
        print(f"✗ Error cargando catálogo: {str(e)}")
        return {}

def generate_alerts_from_real_data(demand_file: str = 'datos_farmacias_siman.csv',
                                   catalog_file: str = 'catalogo_medicamentos.csv',
                                   prediction_horizons: List[int] = [7, 14]) -> pd.DataFrame:
    """Generar alertas desde datos reales de demanda histórica"""
    
    try:
        # Cargar datos
        demand_df = pd.read_csv(demand_file)
        catalog_df = pd.read_csv(catalog_file)
        
        demand_df['fecha'] = pd.to_datetime(demand_df['fecha'])
        
        # Obtener última fecha disponible
        max_date = demand_df['fecha'].max()
        
        # Calcular stock actual (suma últimos 7 días como proxy)
        recent_demand = demand_df[demand_df['fecha'] >= max_date - timedelta(days=7)]
        current_stock_estimate = recent_demand.groupby('sku')['demanda'].sum().to_dict()
        
        # CORRECCIÓN #8: PROCESAR TODOS LOS SKUs (120), NO SOLO 30
        print(f"\n✓ Procesando TODOS los SKUs disponibles en el catálogo")
        skus_with_alerts = list(current_stock_estimate.keys())  # ✅ TODOS los SKUs
        print(f"✓ Total de SKUs a procesar: {len(skus_with_alerts)}")
        
        # Generar alertas para TODOS los SKUs
        alerts_data = []
        
        for sku in skus_with_alerts:
            if sku not in catalog_df['sku'].values:
                continue
                
            sku_info = catalog_df[catalog_df['sku'] == sku].iloc[0]
            current_stock = current_stock_estimate[sku]
            
            for horizon in prediction_horizons:
                # Calcular demanda promedio diaria
                sku_demand = demand_df[demand_df['sku'] == sku]['demanda']
                avg_daily_demand = sku_demand.mean()
                
                # Proyectar stock (stock actual - demanda proyectada)
                predicted_demand = avg_daily_demand * horizon
                predicted_stock = max(0, current_stock - predicted_demand)
                
                # Calcular confianza basada en variabilidad histórica
                demand_std = sku_demand.std()
                demand_cv = demand_std / avg_daily_demand if avg_daily_demand > 0 else 1
                confidence = max(0.6, min(0.95, 1 - (demand_cv * 0.5)))
                
                alerts_data.append({
                    'sku': sku,
                    'current_stock': round(current_stock, 1),
                    'predicted_stock': round(predicted_stock, 1),
                    'prediction_horizon': horizon,
                    'prediction_confidence': round(confidence, 2),
                    'alert_date': max_date
                })
        
        print(f"✓ Alertas generadas: {len(alerts_data)} (SKUs: {len(skus_with_alerts)}, Horizontes: {len(prediction_horizons)})")
        
        return pd.DataFrame(alerts_data)
        
    except Exception as e:
        print(f"✗ Error generando alertas desde datos reales: {str(e)}")
        return pd.DataFrame()

# =============================================================================
# SCRIPT PRINCIPAL
# =============================================================================

def main():
    """Script principal para evaluación de utilidad de alertas"""
    
    print("\n" + "="*70)
    print("EVALUADOR DE UTILIDAD DE ALERTAS - VERSIÓN CORREGIDA")
    print("="*70)
    print("Sistema: Farmacias Siman - Alertas Predictivas")
    print("CORRECCIÓN #8: Procesamiento completo de 120 SKUs")
    print("="*70)
    print("")
    
    try:
        # Cargar configuración de SKUs desde catálogo real
        sku_config = load_sku_config_from_catalog('catalogo_medicamentos.csv')
        print(f"✓ Configuración cargada para {len(sku_config)} SKUs")
        
        # Generar alertas desde datos reales
        alerts_df = generate_alerts_from_real_data('datos_farmacias_siman.csv', 
                                                   'catalogo_medicamentos.csv')
        print(f"✓ {len(alerts_df)} alertas generadas desde datos históricos")
        
        # Validación de alcance
        unique_skus = alerts_df['sku'].nunique()
        expected_skus = 120
        coverage = (unique_skus / expected_skus) * 100
        
        print(f"\n{'='*70}")
        print(f"  VALIDACIÓN DE ALCANCE")
        print(f"{'='*70}")
        print(f"✓ SKUs esperados: {expected_skus}")
        print(f"✓ SKUs procesados: {unique_skus}")
        print(f"✓ Cobertura: {coverage:.1f}%")
        
        if coverage == 100.0:
            print(f"🎯 ALCANCE COMPLETO: Todos los SKUs han sido procesados")
        else:
            print(f"⚠️  ALCANCE PARCIAL: {expected_skus - unique_skus} SKUs no procesados")
        
        print(f"{'='*70}\n")
        
        # Inicializar evaluador
        evaluator = AlertUtilityEvaluator(sku_config)
        
        # Evaluar alertas
        print("Evaluando alertas...")
        results_df = evaluator.evaluate_alert_batch(alerts_df)
        print(f"✓ Evaluación completada: {len(results_df)} resultados")
        
        # Generar reporte
        report = evaluator.generate_utility_report(results_df, 'utility_report.txt')
        print(f"\n{report}")
        
        # Exportar resultados detallados
        results_df.to_csv('alert_evaluation_results.csv', index=False)
        print(f"\n✓ Resultados detallados exportados a: alert_evaluation_results.csv")
        print(f"  - Total registros: {len(results_df)}")
        print(f"  - SKUs únicos: {results_df['sku'].nunique()}")
        print(f"  - Columnas: {len(results_df.columns)}")
        
        return results_df
        
    except Exception as e:
        print(f"✗ Error durante evaluación: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    results = main()