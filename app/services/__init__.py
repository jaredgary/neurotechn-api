"""
Servicios de lógica de negocio
Sistema de Alertas Predictivas - Farmacias Siman
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date
from app.database import supabase_client, supabase_admin
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class AlertaService:
    """Servicio para operaciones de alertas"""
    
    @staticmethod
    async def generar_alertas_automaticas() -> dict:
        """
        Genera alertas automáticas usando la función PL/pgSQL generar_alertas_batch()
        
        Returns:
            dict: Resultado con alertas generadas
        """
        try:
            if supabase_admin is None:
                raise Exception("Cliente admin no disponible")
            
            # Llamar función PostgreSQL
            result = supabase_admin.rpc('generar_alertas_batch').execute()
            
            if not result.data:
                return {"alertas_generadas": 0, "mensaje": "No hay SKUs en riesgo"}
            
            # Insertar alertas en la tabla
            alertas_nuevas = []
            for alerta_data in result.data:
                dias = alerta_data.get("dias", 14)
                alerta = {
                    "sku": alerta_data["sku_alerta"],
                    "nivel_riesgo": alerta_data["nivel"],
                    "dias_hasta_stockout": dias,
                    "cantidad_recomendada": alerta_data["cantidad_recomendar"],
                    "fecha_limite_pedido": alerta_data.get("fecha_limite"),
                    "score_urgencia": round(max(0, min(1, 1.0 - (dias / 14.0))), 3),
                    "estado": "pendiente"
                }
                alertas_nuevas.append(alerta)
            
            # Insertar alertas
            if alertas_nuevas:
                insert_result = supabase_admin.table('alertas').insert(alertas_nuevas).execute()
                return {
                    "alertas_generadas": len(insert_result.data),
                    "alertas": insert_result.data
                }
            
            return {"alertas_generadas": 0, "mensaje": "No se generaron alertas nuevas"}
            
        except Exception as e:
            logger.error(f"Error generando alertas automáticas: {str(e)}")
            raise
    
    @staticmethod
    async def obtener_factores_explicativos(sku: str) -> dict:
        """
        Obtiene factores explicativos de una alerta usando función PL/pgSQL
        
        Args:
            sku: SKU del medicamento
            
        Returns:
            dict: Factores explicativos JSON con top-3 drivers
        """
        try:
            if supabase_client is None:
                return {"error": "Cliente no disponible"}
            
            result = supabase_client.rpc(
                'obtener_factores_explicativos',
                {'p_sku': sku}
            ).execute()
            
            return result.data if result.data else {}
            
        except Exception as e:
            logger.error(f"Error obteniendo factores explicativos: {str(e)}")
            return {"error": str(e)}
    
    @staticmethod
    async def calcular_score_urgencia(dias_stockout: int) -> float:
        """
        Calcula score de urgencia basado en días hasta stockout
        
        Score = 1 - (días / horizonte_óptimo)
        Horizonte óptimo = 14 días (OE2)
        
        Args:
            dias_stockout: Días hasta stockout
            
        Returns:
            float: Score de urgencia (0-1), promedio esperado: 0.74
        """
        try:
            # Fórmula verificada: score = 1 - (días / 14)
            score = 1.0 - (dias_stockout / settings.HORIZONTE_OPTIMO)
            return round(max(0, min(1, score)), 3)
            
        except Exception as e:
            logger.error(f"Error calculando score urgencia: {str(e)}")
            return 0.0


class PrediccionService:
    """Servicio para operaciones de predicciones ML"""
    
    @staticmethod
    async def calcular_stock_proyectado(sku: str, dias: int) -> Optional[float]:
        """
        Calcula stock proyectado usando función PL/pgSQL
        
        Stock proyectado = Stock actual - (demanda_predicha para horizonte)
        
        Args:
            sku: SKU del medicamento
            dias: Horizonte en días (7, 14, 28)
            
        Returns:
            float: Stock proyectado (puede ser negativo si hay riesgo)
        """
        try:
            if supabase_client is None:
                return None
            
            result = supabase_client.rpc(
                'calcular_stock_proyectado',
                {'p_sku': sku, 'p_dias': dias}
            ).execute()
            
            return float(result.data) if result.data is not None else None
            
        except Exception as e:
            logger.error(f"Error calculando stock proyectado: {str(e)}")
            return None
    
    @staticmethod
    async def obtener_metricas_modelo() -> dict:
        """
        Obtiene métricas del modelo XGBoost
        
        Valores verificados (OE2):
        - MAE promedio: 379.69 unidades
        - MAPE promedio: 3.85%
        - Horizonte óptimo: 14 días
        
        Returns:
            dict: Métricas del modelo
        """
        return {
            "algoritmo": "XGBoost",
            "scoring": settings.XGBOOST_SCORING,
            "metricas_promedio": {
                "mae": settings.XGBOOST_MAE_PROMEDIO,
                "mape": settings.XGBOOST_MAPE_PROMEDIO,
                "sesgo": settings.XGBOOST_SESGO_PROMEDIO,
                "tiempo_entrenamiento": settings.XGBOOST_TIEMPO_ENTRENAMIENTO
            },
            "por_horizonte": {
                "7d": {"mae": settings.XGBOOST_MAE_7D, "mape": settings.XGBOOST_MAPE_7D},
                "14d": {"mae": settings.XGBOOST_MAE_14D, "mape": settings.XGBOOST_MAPE_14D},
                "28d": {"mae": settings.XGBOOST_MAE_28D, "mape": settings.XGBOOST_MAPE_28D}
            },
            "horizonte_optimo": settings.HORIZONTE_OPTIMO
        }


class InventarioService:
    """Servicio para operaciones de inventario"""
    
    @staticmethod
    async def obtener_skus_en_riesgo(horizonte: int = 14) -> List[Dict[str, Any]]:
        """
        Obtiene SKUs con stock proyectado negativo
        
        Args:
            horizonte: Horizonte de predicción (default: 14 días óptimo)
            
        Returns:
            list: SKUs en riesgo ordenados por urgencia
        """
        try:
            if supabase_client is None:
                return []
            
            columna_stock = f"stock_proyectado_{horizonte}d"
            
            result = supabase_client.table('inventarios_actuales') \
                .select(f'sku, stock_actual, {columna_stock}, catalogo_medicamentos(nombre_comercial, es_esencial)') \
                .lt(columna_stock, 0) \
                .order(columna_stock) \
                .execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error obteniendo SKUs en riesgo: {str(e)}")
            return []


class ValidacionService:
    """Servicio para validación de coherencia con la tesis"""
    
    @staticmethod
    async def validar_coherencia_datos() -> dict:
        """
        Valida que los datos en BD sean coherentes con la tesis
        
        Returns:
            dict: Resultado de validación con discrepancias
        """
        validaciones = {}
        
        try:
            if supabase_client is None:
                return {"error": "Cliente no disponible"}
            
            # Validar catálogo (120 SKUs)
            catalogo = supabase_client.table('catalogo_medicamentos').select('count', count='exact').execute()
            validaciones["catalogo_medicamentos"] = {
                "actual": catalogo.count,
                "esperado": settings.TOTAL_SKUS,
                "valido": catalogo.count == settings.TOTAL_SKUS
            }
            
            # Validar ventas (10,800 registros)
            ventas = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
            validaciones["ventas_diarias"] = {
                "actual": ventas.count,
                "esperado": settings.TOTAL_REGISTROS_VENTAS,
                "valido": ventas.count == settings.TOTAL_REGISTROS_VENTAS
            }
            
            # Validar backtest (360 registros)
            backtest = supabase_client.table('backtest_results').select('count', count='exact').execute()
            validaciones["backtest_results"] = {
                "actual": backtest.count,
                "esperado": settings.TOTAL_BACKTEST_RECORDS,
                "valido": backtest.count == settings.TOTAL_BACKTEST_RECORDS
            }
            
            # Validar evaluación alertas (240 registros)
            evaluacion = supabase_client.table('alert_evaluation_results').select('count', count='exact').execute()
            validaciones["alert_evaluation"] = {
                "actual": evaluacion.count,
                "esperado": settings.TOTAL_ALERTAS_EVALUADAS,
                "valido": evaluacion.count == settings.TOTAL_ALERTAS_EVALUADAS
            }
            
            todas_validas = all(v["valido"] for v in validaciones.values())
            
            return {
                "coherencia_total": todas_validas,
                "validaciones": validaciones,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error validando coherencia: {str(e)}")
            return {"error": str(e)}
