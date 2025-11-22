"""
Servicio de lógica de negocio para Predicciones
"""

from typing import List, Optional
from datetime import date
from app.database import supabase_client
import logging

logger = logging.getLogger(__name__)


class PrediccionService:
    """Servicio para operaciones de predicciones"""
    
    @staticmethod
    async def calcular_stock_proyectado(sku: str, dias: int) -> Optional[float]:
        """
        Calcula stock proyectado usando función PL/pgSQL
        
        Args:
            sku: SKU del medicamento
            dias: Horizonte en días (7, 14, 28)
            
        Returns:
            float: Stock proyectado (puede ser negativo)
        """
        try:
            result = supabase_client.rpc(
                'calcular_stock_proyectado',
                {'p_sku': sku, 'p_dias': dias}
            ).execute()
            
            return float(result.data) if result.data is not None else None
            
        except Exception as e:
            logger.error(f"Error calculando stock proyectado: {str(e)}")
            return None