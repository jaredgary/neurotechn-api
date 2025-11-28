"""
Endpoints para Evaluación de Alertas (OE4)
Acceso a los 240 registros de evaluación (120 SKUs × 2 horizontes: 7d, 14d)
Métricas verificadas: 71.7% alertas accionables, 89.2% cumple lead time
"""

from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from datetime import datetime
from app.database import supabase_client
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_evaluacion_alertas(
    horizonte: Optional[int] = Query(None, description="Filtrar por horizonte (7, 14)"),
    es_accionable: Optional[bool] = Query(None, description="Filtrar por accionabilidad"),
    nivel_riesgo: Optional[str] = Query(None, description="Filtrar por nivel (HIGH, MEDIUM)"),
    limit: int = Query(100, ge=1, le=240),
    offset: int = Query(0, ge=0)
):
    """
    Lista resultados de evaluación de alertas (OE4)
    
    Métricas verificadas:
    - Total: 240 registros (120 SKUs × 2 horizontes)
    - Accionables: 172 (71.7%)
    - Cumple lead time: 214 (89.2%)
    - Horizonte óptimo: 14 días (100% accionables)
    
    Args:
        horizonte: Filtrar por horizonte (7 o 14 días)
        es_accionable: Filtrar por accionabilidad
        nivel_riesgo: Filtrar por nivel de riesgo
        limit: Máximo de resultados
        offset: Offset para paginación
        
    Returns:
        dict: Resultados de evaluación con métricas
    """
    try:
        query = supabase_client.table('alert_evaluation_results') \
            .select('*, catalogo_medicamentos(nombre_comercial, categoria_abc)')
        
        # Aplicar filtros
        if horizonte:
            if horizonte not in [7, 14]:
                raise HTTPException(
                    status_code=400, 
                    detail="Horizonte debe ser 7 o 14 días"
                )
            query = query.eq('prediction_horizon', horizonte)
        
        if es_accionable is not None:
            query = query.eq('is_actionable', es_accionable)
        
        if nivel_riesgo:
            if nivel_riesgo not in ['HIGH', 'MEDIUM', 'CRITICAL']:
                raise HTTPException(
                    status_code=400,
                    detail="Nivel de riesgo debe ser HIGH, MEDIUM o CRITICAL"
                )
            query = query.eq('risk_level', nivel_riesgo)
        
        # Ordenar y paginar
        query = query.order('urgency_score', desc=True).range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Count total
        count_query = supabase_client.table('alert_evaluation_results').select('count', count='exact')
        if horizonte:
            count_query = count_query.eq('prediction_horizon', horizonte)
        if es_accionable is not None:
            count_query = count_query.eq('is_actionable', es_accionable)
        if nivel_riesgo:
            count_query = count_query.eq('risk_level', nivel_riesgo)
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "evaluaciones": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset,
                "metricas_esperadas": {
                    "total_registros": settings.TOTAL_ALERTAS_EVALUADAS,
                    "accionables": settings.ALERTAS_ACCIONABLES,
                    "accionables_pct": settings.ALERTAS_ACCIONABLES_PCT
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listando evaluación de alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas-consolidadas")
async def obtener_metricas_consolidadas():
    """
    Obtiene métricas consolidadas de utilidad de alertas (OE4)
    
    Valores verificados (utility_report.txt):
    - Alertas accionables: 71.7% (172/240)
    - Cumple lead time: 89.2% (214/240)
    - Días promedio stockout: 8.6
    - Score urgencia promedio: 0.74
    - Cantidad promedio recomendada: 96.1 unidades
    - Total recomendado ordenar: 23,072 unidades
    
    Returns:
        dict: Métricas consolidadas de utilidad
    """
    try:
        # Total registros
        total = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .execute()
        
        # Accionables
        accionables = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('is_actionable', True) \
            .execute()
        
        # Cumple lead time
        cumple_lead = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('meets_lead_time', True) \
            .execute()
        
        # Bajo umbral seguridad
        bajo_umbral = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('below_safety_threshold', True) \
            .execute()
        
        # Cumple confianza mínima
        cumple_confianza = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('meets_confidence', True) \
            .execute()
        
        # Cumple pedido mínimo
        cumple_pedido = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('meets_min_order', True) \
            .execute()
        
        # Obtener datos para calcular promedios
        all_data = supabase_client.table('alert_evaluation_results') \
            .select('days_until_stockout, urgency_score, recommended_order_qty') \
            .execute()
        
        # Calcular promedios
        dias_stockout = [r['days_until_stockout'] for r in all_data.data if r.get('days_until_stockout') is not None]
        urgencia = [r['urgency_score'] for r in all_data.data if r.get('urgency_score') is not None]
        cantidad = [r['recommended_order_qty'] for r in all_data.data if r.get('recommended_order_qty') is not None]
        
        total_count = total.count or 1  # Evitar división por cero
        
        return {
            "success": True,
            "data": {
                "resumen_accionabilidad": {
                    "total_alertas": total.count,
                    "accionables": accionables.count,
                    "accionables_pct": round((accionables.count / total_count) * 100, 1),
                    "no_accionables": total_count - accionables.count
                },
                "cumplimiento_criterios": {
                    "cumple_lead_time": {
                        "cantidad": cumple_lead.count,
                        "porcentaje": round((cumple_lead.count / total_count) * 100, 1)
                    },
                    "bajo_umbral_seguridad": {
                        "cantidad": bajo_umbral.count,
                        "porcentaje": round((bajo_umbral.count / total_count) * 100, 1)
                    },
                    "cumple_confianza_minima": {
                        "cantidad": cumple_confianza.count,
                        "porcentaje": round((cumple_confianza.count / total_count) * 100, 1)
                    },
                    "cumple_pedido_minimo": {
                        "cantidad": cumple_pedido.count,
                        "porcentaje": round((cumple_pedido.count / total_count) * 100, 1)
                    }
                },
                "metricas_operacionales": {
                    "dias_promedio_stockout": round(sum(dias_stockout) / len(dias_stockout), 1) if dias_stockout else 0,
                    "score_urgencia_promedio": round(sum(urgencia) / len(urgencia), 2) if urgencia else 0,
                    "cantidad_promedio_recomendada": round(sum(cantidad) / len(cantidad), 1) if cantidad else 0,
                    "total_recomendado_ordenar": round(sum(cantidad)) if cantidad else 0
                },
                "valores_verificados_tesis": {
                    "accionables_pct_oficial": settings.ALERTAS_ACCIONABLES_PCT,
                    "dias_promedio_oficial": settings.DIAS_PROMEDIO_STOCKOUT,
                    "score_urgencia_oficial": settings.SCORE_URGENCIA_PROMEDIO,
                    "total_ordenar_oficial": settings.TOTAL_RECOMENDADO_ORDENAR
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas consolidadas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-horizonte")
async def obtener_evaluacion_por_horizonte():
    """
    Obtiene evaluación de alertas desglosada por horizonte de predicción
    
    Valores verificados (OE4):
    - 7 días:  52 accionables (43.3%), 78.3% cumple lead time
    - 14 días: 120 accionables (100%), 100% cumple lead time (ÓPTIMO)
    
    Returns:
        dict: Métricas por horizonte
    """
    try:
        metricas_por_horizonte = {}
        
        for horizonte in [7, 14]:
            # Total del horizonte
            total = supabase_client.table('alert_evaluation_results') \
                .select('count', count='exact') \
                .eq('prediction_horizon', horizonte) \
                .execute()
            
            # Accionables
            accionables = supabase_client.table('alert_evaluation_results') \
                .select('count', count='exact') \
                .eq('prediction_horizon', horizonte) \
                .eq('is_actionable', True) \
                .execute()
            
            # Cumple lead time
            cumple_lead = supabase_client.table('alert_evaluation_results') \
                .select('count', count='exact') \
                .eq('prediction_horizon', horizonte) \
                .eq('meets_lead_time', True) \
                .execute()
            
            total_count = total.count or 1
            
            metricas_por_horizonte[f"{horizonte}d"] = {
                "horizonte_dias": horizonte,
                "total_alertas": total.count,
                "accionables": accionables.count,
                "accionables_pct": round((accionables.count / total_count) * 100, 1),
                "cumple_lead_time": cumple_lead.count,
                "cumple_lead_time_pct": round((cumple_lead.count / total_count) * 100, 1)
            }
        
        return {
            "success": True,
            "data": {
                "por_horizonte": metricas_por_horizonte,
                "horizonte_optimo": "14d",
                "razon_optimo": "100% alertas accionables y 100% cumple lead time",
                "valores_verificados_tesis": {
                    "accionables_7d": settings.ACCIONABLES_7D,
                    "accionables_14d": settings.ACCIONABLES_14D
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo evaluación por horizonte: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribucion-riesgo")
async def obtener_distribucion_riesgo():
    """
    Obtiene distribución de alertas por nivel de riesgo
    
    Valores verificados (OE4):
    - MEDIUM: 131 alertas (54.6%)
    - HIGH: 109 alertas (45.4%)
    - CRITICAL: 0 alertas (0%)
    
    Returns:
        dict: Distribución por nivel de riesgo
    """
    try:
        distribucion = {}
        total = 0
        
        for nivel in ['CRITICAL', 'HIGH', 'MEDIUM']:
            count = supabase_client.table('alert_evaluation_results') \
                .select('count', count='exact') \
                .eq('risk_level', nivel) \
                .execute()
            
            distribucion[nivel] = count.count
            total += count.count
        
        # Calcular porcentajes
        distribucion_con_pct = {}
        for nivel, cantidad in distribucion.items():
            distribucion_con_pct[nivel] = {
                "cantidad": cantidad,
                "porcentaje": round((cantidad / total) * 100, 1) if total > 0 else 0
            }
        
        return {
            "success": True,
            "data": {
                "distribucion": distribucion_con_pct,
                "total_alertas": total,
                "valores_verificados_tesis": {
                    "medium": settings.RIESGO_MEDIUM,
                    "high": settings.RIESGO_HIGH,
                    "critical": settings.RIESGO_CRITICAL
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo distribución de riesgo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-sku/{sku}")
async def obtener_evaluacion_por_sku(
    sku: str = Path(..., description="SKU del medicamento")
):
    """
    Obtiene evaluación de alertas para un SKU específico
    
    Args:
        sku: SKU del medicamento
        
    Returns:
        dict: Evaluaciones para ambos horizontes (7d, 14d)
    """
    try:
        # Validar SKU
        check = supabase_client.table('catalogo_medicamentos') \
            .select('sku, nombre_comercial, categoria_abc, es_esencial') \
            .eq('sku', sku) \
            .execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail=f"SKU {sku} no encontrado")
        
        medicamento = check.data[0]
        
        # Obtener evaluaciones
        result = supabase_client.table('alert_evaluation_results') \
            .select('*') \
            .eq('sku', sku) \
            .order('prediction_horizon') \
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail=f"No hay evaluaciones de alerta para SKU {sku}"
            )
        
        # Organizar por horizonte
        por_horizonte = {}
        for eval in result.data:
            h = eval['prediction_horizon']
            por_horizonte[f"{h}d"] = {
                "horizonte_dias": h,
                "es_accionable": eval.get('is_actionable'),
                "nivel_riesgo": eval.get('risk_level'),
                "dias_hasta_stockout": eval.get('days_until_stockout'),
                "score_urgencia": eval.get('urgency_score'),
                "cantidad_recomendada": eval.get('recommended_order_qty'),
                "cumple_lead_time": eval.get('meets_lead_time'),
                "bajo_umbral_seguridad": eval.get('below_safety_threshold'),
                "cumple_confianza": eval.get('meets_confidence'),
                "cumple_pedido_minimo": eval.get('meets_min_order')
            }
        
        return {
            "success": True,
            "data": {
                "sku": sku,
                "medicamento": medicamento,
                "evaluaciones": por_horizonte,
                "recomendacion": "Usar horizonte 14d para alertas más accionables"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo evaluación de {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validacion-coherencia")
async def validar_coherencia_evaluacion():
    """
    Valida coherencia de datos de evaluación contra valores de tesis
    
    Returns:
        dict: Resultado de validación con discrepancias
    """
    try:
        # Contar registros totales
        total = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .execute()
        
        # Contar accionables
        accionables = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('is_actionable', True) \
            .execute()
        
        # Contar por horizonte
        h7 = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('prediction_horizon', 7) \
            .execute()
        
        h14 = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .eq('prediction_horizon', 14) \
            .execute()
        
        # SKUs únicos
        skus = supabase_client.table('alert_evaluation_results') \
            .select('sku') \
            .execute()
        skus_unicos = len(set(r['sku'] for r in skus.data))
        
        # Validaciones
        validaciones = {
            "total_registros": {
                "actual": total.count,
                "esperado": settings.TOTAL_ALERTAS_EVALUADAS,
                "valido": total.count == settings.TOTAL_ALERTAS_EVALUADAS
            },
            "alertas_accionables": {
                "actual": accionables.count,
                "esperado": settings.ALERTAS_ACCIONABLES,
                "valido": accionables.count == settings.ALERTAS_ACCIONABLES
            },
            "skus_unicos": {
                "actual": skus_unicos,
                "esperado": settings.TOTAL_SKUS,
                "valido": skus_unicos == settings.TOTAL_SKUS
            },
            "registros_horizonte_7d": {
                "actual": h7.count,
                "esperado": 120,
                "valido": h7.count == 120
            },
            "registros_horizonte_14d": {
                "actual": h14.count,
                "esperado": 120,
                "valido": h14.count == 120
            }
        }
        
        todas_validas = all(v["valido"] for v in validaciones.values())
        
        return {
            "success": True,
            "data": {
                "coherencia_total": todas_validas,
                "validaciones": validaciones,
                "mensaje": "✅ Datos coherentes con tesis" if todas_validas else "⚠️ Discrepancias detectadas"
            }
        }
        
    except Exception as e:
        logger.error(f"Error validando coherencia: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
