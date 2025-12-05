"""
Endpoints para Evaluación de Alertas
Versión 2.0 - SaaS Genérico con Cálculo Dinámico

Permite ejecutar evaluación de alertas y consultar resultados.
"""

from fastapi import APIRouter, HTTPException, Query, Path, BackgroundTasks
from typing import Optional
from datetime import datetime
from app.database import supabase_client
from app.config import settings
from app.services.alert_evaluation import AlertEvaluationService, AlertEvaluationResultsStorage
import pandas as pd
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ejecutar")
async def ejecutar_evaluacion_alertas(background_tasks: BackgroundTasks):
    """
    Ejecuta evaluación de alertas para TODOS los SKUs en el sistema.

    Evalúa accionabilidad según criterios de lead time, stock de seguridad,
    confianza mínima y lote mínimo.

    Returns:
        dict: Status de ejecución
    """
    try:
        logger.info("🔍 Iniciando evaluación de alertas...")

        # Obtener datos de catálogo
        catalogo_result = supabase_client.table('catalogo_medicamentos') \
            .select('*') \
            .execute()

        if not catalogo_result.data:
            raise HTTPException(
                status_code=400,
                detail="No hay catálogo de medicamentos. Cargue datos primero."
            )

        catalogo_df = pd.DataFrame(catalogo_result.data)

        # Obtener datos de ventas
        ventas_result = supabase_client.table('ventas_diarias') \
            .select('sku, fecha, demanda') \
            .execute()

        if not ventas_result.data:
            raise HTTPException(
                status_code=400,
                detail="No hay datos de ventas. Cargue datos primero."
            )

        ventas_df = pd.DataFrame(ventas_result.data)

        logger.info(f"   📊 Catálogo: {len(catalogo_df)} SKUs")
        logger.info(f"   📈 Ventas: {len(ventas_df)} registros")

        # Inicializar servicio de evaluación
        eval_service = AlertEvaluationService(
            lead_time_buffer=settings.LEAD_TIME_BUFFER_DAYS,
            safety_threshold=settings.SAFETY_STOCK_THRESHOLD,
            min_confidence=settings.MIN_CONFIDENCE_THRESHOLD,
            risk_critical_days=settings.RISK_CRITICAL_DAYS,
            risk_high_days=settings.RISK_HIGH_DAYS
        )

        # Ejecutar evaluación
        results_df = await eval_service.evaluate_all_alerts(
            catalogo_df=catalogo_df,
            ventas_df=ventas_df,
            prediction_horizons=settings.ALERT_HORIZONS
        )

        if results_df.empty:
            raise HTTPException(
                status_code=500,
                detail="Evaluación no generó resultados. Verifique los datos."
            )

        # Guardar resultados en Supabase
        await AlertEvaluationResultsStorage.save_results(
            supabase_client,
            results_df,
            clear_existing=True
        )

        # Calcular métricas de resumen
        metricas = {
            "total_evaluaciones": len(results_df),
            "skus_evaluados": int(results_df['sku'].nunique()),
            "alertas_accionables": int(results_df['is_actionable'].sum()),
            "porcentaje_accionables": round(float(results_df['is_actionable'].mean() * 100), 1),
            "distribucion_riesgo": results_df['risk_level'].value_counts().to_dict()
        }

        logger.info(f"✅ Evaluación completada")
        logger.info(f"   Accionables: {metricas['porcentaje_accionables']}%")

        return {
            "success": True,
            "message": "Evaluación de alertas ejecutada exitosamente",
            "data": metricas,
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "nota": "Métricas calculadas dinámicamente"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error ejecutando evaluación: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def listar_evaluacion_alertas(
    horizonte: Optional[int] = Query(None, description="Filtrar por horizonte (7, 14)"),
    es_accionable: Optional[bool] = Query(None, description="Filtrar por accionabilidad"),
    nivel_riesgo: Optional[str] = Query(None, description="Filtrar por nivel (CRITICAL, HIGH, MEDIUM)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Lista resultados de evaluación de alertas.

    El total de registros varía según el número de SKUs × horizontes evaluados.

    Args:
        horizonte: Filtrar por horizonte (7 o 14 días)
        es_accionable: Filtrar por accionabilidad
        nivel_riesgo: Filtrar por nivel de riesgo
        limit: Máximo de resultados
        offset: Offset para paginación

    Returns:
        dict: Resultados de evaluación
    """
    try:
        query = supabase_client.table('alert_evaluation_results') \
            .select('*, catalogo_medicamentos(nombre_comercial, categoria_abc)')

        # Aplicar filtros
        if horizonte:
            if horizonte not in settings.ALERT_HORIZONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Horizonte debe ser uno de {settings.ALERT_HORIZONS}"
                )
            query = query.eq('prediction_horizon', horizonte)

        if es_accionable is not None:
            query = query.eq('is_actionable', es_accionable)

        if nivel_riesgo:
            if nivel_riesgo not in ['CRITICAL', 'HIGH', 'MEDIUM']:
                raise HTTPException(
                    status_code=400,
                    detail="Nivel de riesgo debe ser CRITICAL, HIGH o MEDIUM"
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
                "offset": offset
            },
            "meta": {
                "nota": "Total de registros varía según SKUs en el sistema"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listando evaluación de alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas")
async def obtener_metricas_consolidadas():
    """
    Obtiene métricas consolidadas de utilidad de alertas.

    TODAS las métricas se calculan dinámicamente.

    Returns:
        dict: Métricas consolidadas de utilidad
    """
    try:
        # Total registros
        total = supabase_client.table('alert_evaluation_results') \
            .select('count', count='exact') \
            .execute()

        if total.count == 0:
            return {
                "success": False,
                "error": "No hay evaluaciones de alertas. Ejecute POST /api/v1/evaluacion-alertas/ejecutar primero.",
                "data": None
            }

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
            .select('days_until_stockout, urgency_score, recommended_order_qty, risk_level') \
            .execute()

        # Calcular promedios
        dias_stockout = [r['days_until_stockout'] for r in all_data.data if r.get('days_until_stockout') is not None]
        urgencia = [r['urgency_score'] for r in all_data.data if r.get('urgency_score') is not None]
        cantidad = [r['recommended_order_qty'] for r in all_data.data if r.get('recommended_order_qty') is not None]

        # Distribución por riesgo
        riesgo_dist = {}
        for nivel in ['CRITICAL', 'HIGH', 'MEDIUM']:
            count = sum(1 for r in all_data.data if r.get('risk_level') == nivel)
            riesgo_dist[nivel] = count

        total_count = total.count

        # Obtener SKUs únicos evaluados
        skus_unicos = len(set(r.get('sku') for r in all_data.data if r.get('sku'))) if all_data.data else 0

        # ✅ CORREGIDO: Estructura alineada con frontend (MetricasEvaluacionAlertas)
        return {
            "success": True,
            "data": {
                "resumen": {
                    "total_alertas_evaluadas": total_count,
                    "alertas_accionables": accionables.count,
                    "porcentaje_accionables": round((accionables.count / total_count) * 100, 1),
                    "skus_evaluados": skus_unicos
                },
                "distribucion_riesgo": riesgo_dist,
                "criterios": {
                    "cumple_lead_time": {
                        "cumplidos": cumple_lead.count,
                        "porcentaje": round((cumple_lead.count / total_count) * 100, 1)
                    },
                    "cumple_stock_seguridad": {
                        "cumplidos": bajo_umbral.count,
                        "porcentaje": round((bajo_umbral.count / total_count) * 100, 1)
                    },
                    "cumple_confianza_minima": {
                        "cumplidos": cumple_confianza.count,
                        "porcentaje": round((cumple_confianza.count / total_count) * 100, 1)
                    },
                    "cumple_pedido_minimo": {
                        "cumplidos": cumple_pedido.count,
                        "porcentaje": round((cumple_pedido.count / total_count) * 100, 1)
                    }
                },
                "metricas_operacionales": {
                    "dias_promedio_hasta_stockout": round(sum(dias_stockout) / len(dias_stockout), 1) if dias_stockout else 0,
                    "score_urgencia_promedio": round(sum(urgencia) / len(urgencia), 2) if urgencia else 0,
                    "cantidad_promedio_recomendada": round(sum(cantidad) / len(cantidad), 1) if cantidad else 0,
                    "total_recomendado_ordenar": int(sum(cantidad)) if cantidad else 0
                }
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo métricas consolidadas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-horizonte")
async def obtener_evaluacion_por_horizonte():
    """
    Obtiene evaluación de alertas desglosada por horizonte de predicción.

    Calcula métricas dinámicamente para cada horizonte.

    Returns:
        dict: Métricas por horizonte
    """
    try:
        metricas_por_horizonte = {}

        for horizonte in settings.ALERT_HORIZONS:
            # Total del horizonte
            total = supabase_client.table('alert_evaluation_results') \
                .select('count', count='exact') \
                .eq('prediction_horizon', horizonte) \
                .execute()

            if total.count == 0:
                continue

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

            total_count = total.count

            metricas_por_horizonte[f"{horizonte}d"] = {
                "horizonte_dias": horizonte,
                "total_alertas": total_count,
                "accionables": accionables.count,
                "accionables_pct": round((accionables.count / total_count) * 100, 1),
                "cumple_lead_time": cumple_lead.count,
                "cumple_lead_time_pct": round((cumple_lead.count / total_count) * 100, 1)
            }

        # Identificar horizonte óptimo (mayor % accionables)
        if metricas_por_horizonte:
            horizonte_optimo = max(
                metricas_por_horizonte.items(),
                key=lambda x: x[1]['accionables_pct']
            )[0]
        else:
            horizonte_optimo = None

        return {
            "success": True,
            "data": {
                "por_horizonte": metricas_por_horizonte,
                "horizonte_optimo": horizonte_optimo
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo evaluación por horizonte: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/distribucion-riesgo")
async def obtener_distribucion_riesgo():
    """
    Obtiene distribución de alertas por nivel de riesgo.

    Calcula dinámicamente la distribución actual.

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
                "total_alertas": total
            },
            "meta": {
                "nota": "Distribución calculada dinámicamente",
                "timestamp": datetime.now().isoformat()
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
    Obtiene evaluación de alertas para un SKU específico.

    Args:
        sku: SKU del medicamento

    Returns:
        dict: Evaluaciones para todos los horizontes
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

        # Identificar mejor horizonte (más accionable)
        mejor_horizonte = None
        for eval in result.data:
            if eval.get('is_actionable'):
                mejor_horizonte = f"{eval['prediction_horizon']}d"
                break

        return {
            "success": True,
            "data": {
                "sku": sku,
                "medicamento": medicamento,
                "evaluaciones": por_horizonte,
                "horizonte_recomendado": mejor_horizonte
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo evaluación de {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
