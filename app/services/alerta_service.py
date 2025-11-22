"""
Servicio de lógica de negocio para Alertas
"""

from typing import List, Optional
from datetime import datetime, date
from app.database import supabase_client, supabase_admin
import logging

logger = logging.getLogger(__name__)


class AlertaService:
    """Servicio para operaciones de alertas"""
    
    @staticmethod
    async def generar_alertas_automaticas() -> dict:
        """
        Genera alertas automáticas usando la función PL/pgSQL generar_alertas_batch
        
        Returns:
            dict: Resultado con alertas generadas
        """
        try:
            # Llamar función PostgreSQL
            result = supabase_admin.rpc('generar_alertas_batch').execute()
            
            if not result.data:
                return {"alertas_generadas": 0, "mensaje": "No hay SKUs en riesgo"}
            
            # Insertar alertas en la tabla
            alertas_nuevas = []
            for alerta_data in result.data:
                alerta = {
                    "sku": alerta_data["sku_alerta"],
                    "nivel_riesgo": alerta_data["nivel"],
                    "dias_hasta_stockout": alerta_data["dias"],
                    "cantidad_recomendada": alerta_data["cantidad_recomendar"],
                    "fecha_limite_pedido": alerta_data["fecha_limite"],
                    "score_urgencia": round(1.0 - (alerta_data["dias"] / 14.0), 3),
                    "estado": "pendiente"
                }
                alertas_nuevas.append(alerta)
            
            # Insertar alertas
            insert_result = supabase_admin.table('alertas').insert(alertas_nuevas).execute()
            
            return {
                "alertas_generadas": len(insert_result.data),
                "alertas": insert_result.data
            }
            
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
            dict: Factores explicativos JSON
        """
        try:
            result = supabase_client.rpc(
                'obtener_factores_explicativos',
                {'p_sku': sku}
            ).execute()
            
            return result.data if result.data else {}
            
        except Exception as e:
            logger.error(f"Error obteniendo factores explicativos: {str(e)}")
            return {}
    
    @staticmethod
    async def calcular_score_urgencia(dias_stockout: int) -> float:
        """
        Calcula score de urgencia usando función PL/pgSQL
        
        Args:
            dias_stockout: Días hasta stockout
            
        Returns:
            float: Score de urgencia (0-1)
        """
        try:
            result = supabase_client.rpc(
                'calcular_score_urgencia',
                {'p_dias_stockout': dias_stockout}
            ).execute()
            
            return float(result.data) if result.data else 0.0
            
        except Exception as e:
            logger.error(f"Error calculando score urgencia: {str(e)}")
            return 0.0