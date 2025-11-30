"""
Servicios de lógica de negocio
Sistema Predictivo de Inventario Farmacéutico - SaaS Genérico
Versión: 2.1 - Cálculo Dinámico

PRINCIPIO FUNDAMENTAL:
"CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"
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
                dias = alerta_data.get("dias", settings.DEFAULT_HORIZON)
                alerta = {
                    "sku": alerta_data["sku_alerta"],
                    "nivel_riesgo": alerta_data["nivel"],
                    "dias_hasta_stockout": dias,
                    "cantidad_recomendada": alerta_data["cantidad_recomendar"],
                    "fecha_limite_pedido": alerta_data.get("fecha_limite"),
                    "score_urgencia": round(max(0, min(1, 1.0 - (dias / float(settings.DEFAULT_HORIZON)))), 3),
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
        
        Score = 1 - (días / horizonte_default)
        
        Args:
            dias_stockout: Días hasta stockout
            
        Returns:
            float: Score de urgencia (0-1)
        """
        try:
            # Usar horizonte configurable, no hardcodeado
            score = 1.0 - (dias_stockout / float(settings.DEFAULT_HORIZON))
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
        Obtiene métricas del modelo XGBoost CALCULADAS DINÁMICAMENTE.
        
        NO retorna valores hardcodeados - consulta la tabla backtest_results.
        
        Returns:
            dict: Métricas del modelo calculadas de los datos
        """
        try:
            if supabase_client is None:
                return {"error": "Cliente no disponible"}
            
            # Obtener todos los resultados de backtest
            result = supabase_client.table('backtest_results') \
                .select('*') \
                .eq('algorithm', 'XGBoost') \
                .execute()
            
            if not result.data:
                return {
                    "success": False,
                    "error": "No hay resultados de backtesting. Ejecute /api/v1/backtest/ejecutar",
                    "data": None
                }
            
            # Calcular métricas globales dinámicamente
            mae_values = [r['mae'] for r in result.data if r.get('mae') is not None]
            mape_values = [r['mape'] for r in result.data if r.get('mape') is not None]
            bias_values = [r['bias'] for r in result.data if r.get('bias') is not None]
            
            metricas_globales = {
                "mae_promedio": round(sum(mae_values) / len(mae_values), 2) if mae_values else None,
                "mape_promedio": round(sum(mape_values) / len(mape_values), 2) if mape_values else None,
                "sesgo_promedio": round(sum(bias_values) / len(bias_values), 2) if bias_values else None,
                "total_backtests": len(result.data),
                "skus_evaluados": len(set(r['sku'] for r in result.data))
            }
            
            # Calcular por horizonte dinámicamente
            horizontes = {}
            for r in result.data:
                h = r.get('horizon')
                if h not in horizontes:
                    horizontes[h] = {'mae': [], 'mape': []}
                if r.get('mae') is not None:
                    horizontes[h]['mae'].append(r['mae'])
                if r.get('mape') is not None:
                    horizontes[h]['mape'].append(r['mape'])
            
            por_horizonte = {}
            for h, vals in sorted(horizontes.items()):
                por_horizonte[f"{h}d"] = {
                    "mae": round(sum(vals['mae']) / len(vals['mae']), 2) if vals['mae'] else None,
                    "mape": round(sum(vals['mape']) / len(vals['mape']), 2) if vals['mape'] else None
                }
            
            # Identificar horizonte óptimo (menor MAE)
            mejor_horizonte = None
            menor_mae = float('inf')
            for h, vals in horizontes.items():
                if vals['mae']:
                    mae_prom = sum(vals['mae']) / len(vals['mae'])
                    if mae_prom < menor_mae:
                        menor_mae = mae_prom
                        mejor_horizonte = h
            
            return {
                "algoritmo": "XGBoost",
                "metricas_globales": metricas_globales,
                "por_horizonte": por_horizonte,
                "horizonte_optimo": mejor_horizonte,
                "meta": {
                    "nota": "Métricas calculadas dinámicamente de backtest_results",
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo métricas del modelo: {str(e)}")
            return {"error": str(e)}


class InventarioService:
    """Servicio para operaciones de inventario"""
    
    @staticmethod
    async def obtener_skus_en_riesgo(horizonte: int = None) -> List[Dict[str, Any]]:
        """
        Obtiene SKUs con stock proyectado negativo
        
        Args:
            horizonte: Horizonte de predicción (default: configurable)
            
        Returns:
            list: SKUs en riesgo ordenados por urgencia
        """
        try:
            if supabase_client is None:
                return []
            
            # Usar horizonte configurable si no se especifica
            if horizonte is None:
                horizonte = settings.DEFAULT_HORIZON
            
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
    """
    Servicio para validación de coherencia de datos.
    
    NOTA: Este servicio NO valida contra valores "esperados" hardcodeados.
    En su lugar, valida la integridad interna de los datos.
    """
    
    @staticmethod
    async def validar_integridad_datos() -> dict:
        """
        Valida la integridad de los datos cargados.
        
        NO compara contra valores hardcodeados - verifica consistencia interna.
        
        Returns:
            dict: Resultado de validación con estadísticas calculadas
        """
        validaciones = {}
        
        try:
            if supabase_client is None:
                return {"error": "Cliente no disponible"}
            
            # Contar catálogo (dinámico)
            catalogo = supabase_client.table('catalogo_medicamentos').select('count', count='exact').execute()
            total_skus = catalogo.count
            
            # Contar ventas (dinámico)
            ventas = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
            total_ventas = ventas.count
            
            # Verificar SKUs en ventas vs catálogo
            skus_ventas = supabase_client.table('ventas_diarias').select('sku').execute()
            skus_unicos_ventas = len(set(v['sku'] for v in skus_ventas.data)) if skus_ventas.data else 0
            
            validaciones["catalogo_medicamentos"] = {
                "total_skus": total_skus,
                "estado": "OK" if total_skus > 0 else "SIN_DATOS"
            }
            
            validaciones["ventas_diarias"] = {
                "total_registros": total_ventas,
                "skus_con_ventas": skus_unicos_ventas,
                "cobertura_skus": round((skus_unicos_ventas / total_skus) * 100, 1) if total_skus > 0 else 0,
                "estado": "OK" if total_ventas > 0 else "SIN_DATOS"
            }
            
            # Verificar backtest (opcional - puede no existir aún)
            try:
                backtest = supabase_client.table('backtest_results').select('count', count='exact').execute()
                backtest_skus = supabase_client.table('backtest_results').select('sku').execute()
                skus_backtest = len(set(b['sku'] for b in backtest_skus.data)) if backtest_skus.data else 0
                
                validaciones["backtest_results"] = {
                    "total_registros": backtest.count,
                    "skus_evaluados": skus_backtest,
                    "cobertura_skus": round((skus_backtest / total_skus) * 100, 1) if total_skus > 0 else 0,
                    "estado": "OK" if backtest.count > 0 else "PENDIENTE_EJECUCION"
                }
            except:
                validaciones["backtest_results"] = {"estado": "TABLA_NO_EXISTE"}
            
            # Verificar evaluación alertas (opcional)
            try:
                evaluacion = supabase_client.table('alert_evaluation_results').select('count', count='exact').execute()
                eval_skus = supabase_client.table('alert_evaluation_results').select('sku').execute()
                skus_eval = len(set(e['sku'] for e in eval_skus.data)) if eval_skus.data else 0
                
                validaciones["alert_evaluation"] = {
                    "total_registros": evaluacion.count,
                    "skus_evaluados": skus_eval,
                    "cobertura_skus": round((skus_eval / total_skus) * 100, 1) if total_skus > 0 else 0,
                    "estado": "OK" if evaluacion.count > 0 else "PENDIENTE_EJECUCION"
                }
            except:
                validaciones["alert_evaluation"] = {"estado": "TABLA_NO_EXISTE"}
            
            # Determinar integridad general
            estados = [v.get("estado", "UNKNOWN") for v in validaciones.values()]
            integridad_ok = all(e in ["OK", "PENDIENTE_EJECUCION", "TABLA_NO_EXISTE"] for e in estados)
            
            return {
                "integridad_ok": integridad_ok,
                "validaciones": validaciones,
                "resumen": {
                    "total_skus_sistema": total_skus,
                    "total_registros_ventas": total_ventas
                },
                "meta": {
                    "nota": "Validación de integridad interna (sin valores hardcodeados)",
                    "principio": "CÁLCULO DINÁMICO",
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error validando integridad: {str(e)}")
            return {"error": str(e)}
