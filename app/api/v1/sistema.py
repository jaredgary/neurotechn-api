"""
Endpoints para Métricas del Sistema
Versión 2.0 - SaaS Genérico con Cálculo Dinámico

PRINCIPIO: TODAS las métricas se calculan dinámicamente de los datos.
NO se usan constantes hardcodeadas.
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.database import supabase_client
from app.config import settings
import pandas as pd
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metricas-ml")
async def obtener_metricas_ml():
    """
    Retorna métricas ML calculadas de los resultados de backtesting.

    IMPORTANTE: Estas métricas cambian cada vez que se re-entrena el modelo.
    Se calculan dinámicamente de la tabla backtest_results.

    Returns:
        dict: Métricas ML agregadas por horizonte
    """
    try:
        # Obtener todos los resultados de backtesting
        result = supabase_client.table('backtest_results') \
            .select('*') \
            .eq('algorithm', 'XGBoost') \
            .execute()

        if not result.data:
            return {
                "success": False,
                "error": "No hay resultados de backtesting. Ejecute /api/v1/backtest/ejecutar primero.",
                "data": None
            }

        df = pd.DataFrame(result.data)

        # Calcular métricas globales
        metricas_globales = {
            "mae_promedio": round(float(df['mae'].mean()), 2),
            "mape_promedio": round(float(df['mape'].mean()), 2),
            "sesgo_promedio": round(float(df['bias'].mean()), 2),
            "total_backtests": len(df),
            "skus_evaluados": int(df['sku'].nunique())
        }

        # Métricas por horizonte
        por_horizonte = {}
        for horizon in sorted(df['horizon'].unique()):
            df_h = df[df['horizon'] == horizon]
            por_horizonte[f"{horizon}_dias"] = {
                "mae": round(float(df_h['mae'].mean()), 2),
                "mape": round(float(df_h['mape'].mean()), 2),
                "sesgo": round(float(df_h['bias'].mean()), 2),
                "n_skus": int(df_h['sku'].nunique()),
                "n_predicciones": int(df_h['n_predictions'].sum()) if 'n_predictions' in df_h.columns else 0
            }

        # Identificar horizonte óptimo (menor MAE)
        mejor_horizonte = df.groupby('horizon')['mae'].mean().idxmin()

        # Última actualización
        if 'created_at' in df.columns:
            ultima_actualizacion = pd.to_datetime(df['created_at']).max().isoformat()
        else:
            ultima_actualizacion = None

        return {
            "success": True,
            "data": {
                "algoritmo": "XGBoost",
                "metricas_globales": metricas_globales,
                "por_horizonte": por_horizonte,
                "horizonte_optimo": {
                    "dias": int(mejor_horizonte),
                    "razon": "Menor MAE promedio"
                }
            },
            "meta": {
                "ultima_actualizacion": ultima_actualizacion,
                "nota": "Métricas calculadas dinámicamente de tabla backtest_results",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo métricas ML: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas-alertas")
async def obtener_metricas_alertas():
    """
    Retorna métricas de utilidad de alertas calculadas dinámicamente.

    Se calculan de la tabla alert_evaluation_results.

    Returns:
        dict: Métricas de alertas accionables y distribución
    """
    try:
        result = supabase_client.table('alert_evaluation_results') \
            .select('*') \
            .execute()

        if not result.data:
            return {
                "success": False,
                "error": "No hay evaluaciones de alertas. Ejecute /api/v1/evaluacion-alertas/ejecutar primero.",
                "data": None
            }

        df = pd.DataFrame(result.data)

        total_alertas = len(df)
        accionables = int(df['is_actionable'].sum())

        # Distribución por nivel de riesgo
        riesgo_dist = df['risk_level'].value_counts().to_dict()

        # Métricas de criterios
        criterios = {
            "cumple_lead_time": int(df['meets_lead_time'].sum()),
            "bajo_umbral_seguridad": int(df['below_safety_threshold'].sum()),
            "cumple_confianza": int(df['meets_confidence'].sum()),
            "cumple_pedido_minimo": int(df['meets_min_order'].sum())
        }

        # Por horizonte
        por_horizonte = {}
        for horizon in sorted(df['prediction_horizon'].unique()):
            df_h = df[df['prediction_horizon'] == horizon]
            por_horizonte[f"{horizon}_dias"] = {
                "total_alertas": len(df_h),
                "accionables": int(df_h['is_actionable'].sum()),
                "porcentaje_accionables": round(float(df_h['is_actionable'].mean() * 100), 1),
                "cumple_lead_time_pct": round(float(df_h['meets_lead_time'].mean() * 100), 1)
            }

        # Métricas operacionales
        metricas_operacionales = {
            "dias_promedio_hasta_stockout": round(float(df['days_until_stockout'].mean()), 1),
            "score_urgencia_promedio": round(float(df['urgency_score'].mean()), 2),
            "cantidad_promedio_recomendada": round(float(df['recommended_order_qty'].mean()), 1),
            "total_recomendado_ordenar": int(df['recommended_order_qty'].sum())
        }

        return {
            "success": True,
            "data": {
                "resumen": {
                    "total_alertas_evaluadas": total_alertas,
                    "alertas_accionables": accionables,
                    "porcentaje_accionables": round(accionables / total_alertas * 100, 1),
                    "skus_evaluados": int(df['sku'].nunique())
                },
                "distribucion_riesgo": {
                    "CRITICAL": riesgo_dist.get('CRITICAL', 0),
                    "HIGH": riesgo_dist.get('HIGH', 0),
                    "MEDIUM": riesgo_dist.get('MEDIUM', 0)
                },
                "criterios": {
                    k: {
                        "cumplidos": v,
                        "porcentaje": round(v / total_alertas * 100, 1)
                    }
                    for k, v in criterios.items()
                },
                "por_horizonte": por_horizonte,
                "metricas_operacionales": metricas_operacionales
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente de tabla alert_evaluation_results",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo métricas de alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calidad-datos")
async def obtener_calidad_datos():
    """
    Valida y reporta calidad de datos actual del sistema.

    Calcula coberturas dinámicamente de las tablas.

    Returns:
        dict: Métricas de calidad por fuente de datos
    """
    try:
        validaciones = {}

        # Total SKUs esperados (calculado dinámicamente del catálogo)
        catalogo = supabase_client.table('catalogo_medicamentos') \
            .select('count', count='exact') \
            .execute()
        total_skus = catalogo.count

        # FD-001: Ventas diarias
        ventas = supabase_client.table('ventas_diarias') \
            .select('count', count='exact') \
            .execute()
        validaciones["FD-001"] = {
            "fuente": "Ventas diarias",
            "registros_actuales": ventas.count,
            "estado": "OK" if ventas.count > 0 else "SIN_DATOS"
        }

        # FD-002: Inventarios
        inventarios = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .execute()
        cobertura_inv = round((inventarios.count / total_skus) * 100, 1) if total_skus > 0 else 0
        validaciones["FD-002"] = {
            "fuente": "Inventarios",
            "registros_actuales": inventarios.count,
            "registros_esperados": total_skus,
            "cobertura_pct": cobertura_inv,
            "estado": "OK" if cobertura_inv >= 80 else "INCOMPLETO"
        }

        # FD-003: Catálogo
        validaciones["FD-003"] = {
            "fuente": "Catálogo medicamentos",
            "registros_actuales": total_skus,
            "cobertura_pct": 100,
            "estado": "COMPLETO"
        }

        # FD-004: Fechas vencimiento
        con_vencimiento = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .not_.is_('fecha_vencimiento', 'null') \
            .execute()
        cobertura_venc = round((con_vencimiento.count / total_skus) * 100, 1) if total_skus > 0 else 0
        validaciones["FD-004"] = {
            "fuente": "Fechas vencimiento",
            "registros_actuales": con_vencimiento.count,
            "registros_esperados": total_skus,
            "cobertura_pct": cobertura_venc,
            "estado": "OK" if cobertura_venc >= 60 else "PARCIAL"
        }

        # Calcular promedio
        coberturas = [v.get('cobertura_pct', 0) for v in validaciones.values() if 'cobertura_pct' in v]
        promedio = round(sum(coberturas) / len(coberturas), 1) if coberturas else 0

        return {
            "success": True,
            "data": {
                "validaciones": validaciones,
                "promedio_cobertura": promedio,
                "estado_general": "OK" if promedio >= 80 else "REQUIERE_ATENCION",
                "total_skus": total_skus
            },
            "meta": {
                "nota": "Validación ejecutada en tiempo real",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error validando calidad de datos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configuracion")
async def obtener_configuracion_sistema():
    """
    Retorna configuración actual del sistema (umbrales de negocio).

    Estos son los ÚNICOS valores que pueden estar "hardcodeados" ya que
    son decisiones de negocio configurables, NO métricas calculadas.

    Returns:
        dict: Configuración de umbrales y parámetros
    """
    try:
        return {
            "success": True,
            "data": {
                "version": settings.APP_VERSION,
                "umbrales_alertas": {
                    "lead_time_buffer_days": settings.LEAD_TIME_BUFFER_DAYS,
                    "safety_stock_threshold": settings.SAFETY_STOCK_THRESHOLD,
                    "min_confidence_threshold": settings.MIN_CONFIDENCE_THRESHOLD,
                    "risk_critical_days": settings.RISK_CRITICAL_DAYS,
                    "risk_high_days": settings.RISK_HIGH_DAYS
                },
                "horizontes_prediccion": {
                    "horizontes_ml": settings.PREDICTION_HORIZONS,
                    "horizontes_alertas": settings.ALERT_HORIZONS
                },
                "ml_config": {
                    "algorithm": "XGBoost",
                    "n_estimators": settings.XGBOOST_N_ESTIMATORS,
                    "max_depth": settings.XGBOOST_MAX_DEPTH,
                    "learning_rate": settings.XGBOOST_LEARNING_RATE
                },
                "walk_forward": {
                    "initial_train_days": settings.INITIAL_TRAIN_DAYS,
                    "step_size_days": settings.STEP_SIZE_DAYS
                },
                "slos": {
                    "disponibilidad_pct": settings.SLO_DISPONIBILIDAD_PCT,
                    "latencia_tablero_ms": settings.SLO_LATENCIA_TABLERO_MS,
                    "latencia_alertas_ms": settings.SLO_LATENCIA_ALERTAS_MS
                }
            },
            "meta": {
                "nota": "Esta es configuración de umbrales, NO métricas calculadas",
                "principio": "CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS"
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo configuración: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resumen-completo")
async def obtener_resumen_completo():
    """
    Retorna resumen completo del sistema con TODAS las métricas calculadas.

    Consolida información de múltiples fuentes.

    Returns:
        dict: Resumen ejecutivo del sistema
    """
    try:
        # Obtener métricas de cada subsistema
        metricas_ml = await obtener_metricas_ml()
        metricas_alertas = await obtener_metricas_alertas()
        calidad = await obtener_calidad_datos()

        # Información del catálogo
        catalogo = supabase_client.table('catalogo_medicamentos') \
            .select('categoria_abc, es_esencial, grupo_terapeutico') \
            .execute()

        df_cat = pd.DataFrame(catalogo.data)

        categorias_abc = df_cat['categoria_abc'].value_counts().to_dict() if not df_cat.empty else {}
        esenciales = int(df_cat['es_esencial'].sum()) if not df_cat.empty else 0
        grupos_terapeuticos = int(df_cat['grupo_terapeutico'].nunique()) if not df_cat.empty else 0

        # Ventas
        ventas = supabase_client.table('ventas_diarias') \
            .select('fecha, demanda') \
            .execute()

        df_ventas = pd.DataFrame(ventas.data)
        if not df_ventas.empty:
            df_ventas['fecha'] = pd.to_datetime(df_ventas['fecha'])
            fecha_inicio = df_ventas['fecha'].min().date().isoformat()
            fecha_fin = df_ventas['fecha'].max().date().isoformat()
            total_ventas = len(df_ventas)
            demandas_cero = int((df_ventas['demanda'] == 0).sum())
        else:
            fecha_inicio = None
            fecha_fin = None
            total_ventas = 0
            demandas_cero = 0

        return {
            "success": True,
            "data": {
                "proyecto": {
                    "nombre": settings.APP_NAME,
                    "version": settings.APP_VERSION,
                    "tipo": "SaaS Genérico - Inventario Predictivo"
                },
                "alcance": {
                    "total_skus": len(df_cat),
                    "medicamentos_esenciales": esenciales,
                    "grupos_terapeuticos": grupos_terapeuticos,
                    "categorias_abc": categorias_abc,
                    "periodo_datos": {
                        "inicio": fecha_inicio,
                        "fin": fecha_fin,
                        "total_registros_ventas": total_ventas,
                        "demandas_cero": demandas_cero
                    }
                },
                "metricas_ml": metricas_ml.get('data') if metricas_ml.get('success') else None,
                "metricas_alertas": metricas_alertas.get('data') if metricas_alertas.get('success') else None,
                "calidad_datos": calidad.get('data') if calidad.get('success') else None
            },
            "meta": {
                "nota": "TODAS las métricas calculadas dinámicamente de los datos",
                "principio": "CÁLCULO DINÁMICO - CERO HARDCODEO DE MÉTRICAS",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo resumen completo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
