"""
Endpoints para Calidad de Datos y Viabilidad del Sistema
Acceso a métricas de calidad FD-001 a FD-004 y viabilidad global (89/100)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime
from app.database import supabase_client
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# =====================================================================
# CALIDAD DE DATOS (OE1 - FD-001 a FD-004)
# =====================================================================

@router.get("/calidad-datos")
async def obtener_calidad_datos():
    """
    Obtiene métricas de calidad de datos (OE1)
    
    Valores verificados (MATRIZ DE DISPONIBILIDAD Y CALIDAD DE DATOS.pdf):
    - FD-001 (Ventas diarias): 83%
    - FD-002 (Inventarios): 80%
    - FD-003 (Catálogo): 100%
    - FD-004 (Fechas vencimiento): 60%
    - Promedio: 83.3%
    
    Returns:
        dict: Métricas de calidad por fuente de datos
    """
    try:
        # Obtener logs de calidad si existen
        result = supabase_client.table('calidad_datos_log') \
            .select('*') \
            .order('fecha_validacion', desc=True) \
            .limit(10) \
            .execute()
        
        # Valores verificados de la tesis
        calidad_verificada = {
            "FD-001": {
                "fuente": "Ventas diarias",
                "disponibilidad_pct": 83,
                "registros_esperados": settings.TOTAL_REGISTROS_VENTAS,
                "estado": "DISPONIBLE"
            },
            "FD-002": {
                "fuente": "Inventarios",
                "disponibilidad_pct": 80,
                "registros_esperados": settings.TOTAL_SKUS,
                "estado": "DISPONIBLE"
            },
            "FD-003": {
                "fuente": "Catálogo medicamentos",
                "disponibilidad_pct": 100,
                "registros_esperados": settings.TOTAL_SKUS,
                "estado": "COMPLETO"
            },
            "FD-004": {
                "fuente": "Fechas vencimiento",
                "disponibilidad_pct": 60,
                "registros_esperados": settings.TOTAL_SKUS,
                "estado": "PARCIAL"
            }
        }
        
        promedio = sum(f["disponibilidad_pct"] for f in calidad_verificada.values()) / 4
        
        return {
            "success": True,
            "data": {
                "fuentes_datos": calidad_verificada,
                "promedio_disponibilidad": round(promedio, 1),
                "promedio_verificado_tesis": settings.DISPONIBILIDAD_DATOS_PROMEDIO,
                "logs_recientes": result.data if result.data else [],
                "fecha_evaluacion": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo calidad de datos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calidad-datos/validar")
async def validar_calidad_actual():
    """
    Ejecuta validación de calidad de datos actual en tiempo real
    
    Returns:
        dict: Resultado de validación actual
    """
    try:
        validaciones = {}
        
        # FD-001: Ventas diarias
        ventas = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
        ventas_esperadas = settings.TOTAL_REGISTROS_VENTAS
        validaciones["FD-001"] = {
            "fuente": "Ventas diarias",
            "registros_actuales": ventas.count,
            "registros_esperados": ventas_esperadas,
            "cobertura_pct": round((ventas.count / ventas_esperadas) * 100, 1) if ventas_esperadas > 0 else 0,
            "estado": "OK" if ventas.count >= ventas_esperadas else "INCOMPLETO"
        }
        
        # FD-002: Inventarios
        inventarios = supabase_client.table('inventarios_actuales').select('count', count='exact').execute()
        validaciones["FD-002"] = {
            "fuente": "Inventarios",
            "registros_actuales": inventarios.count,
            "registros_esperados": settings.TOTAL_SKUS,
            "cobertura_pct": round((inventarios.count / settings.TOTAL_SKUS) * 100, 1),
            "estado": "OK" if inventarios.count >= settings.TOTAL_SKUS else "INCOMPLETO"
        }
        
        # FD-003: Catálogo
        catalogo = supabase_client.table('catalogo_medicamentos').select('count', count='exact').execute()
        validaciones["FD-003"] = {
            "fuente": "Catálogo medicamentos",
            "registros_actuales": catalogo.count,
            "registros_esperados": settings.TOTAL_SKUS,
            "cobertura_pct": round((catalogo.count / settings.TOTAL_SKUS) * 100, 1),
            "estado": "OK" if catalogo.count == settings.TOTAL_SKUS else "INCOMPLETO"
        }
        
        # FD-004: Fechas vencimiento
        con_vencimiento = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .not_.is_('fecha_vencimiento', 'null') \
            .execute()
        validaciones["FD-004"] = {
            "fuente": "Fechas vencimiento",
            "registros_actuales": con_vencimiento.count,
            "registros_esperados": settings.TOTAL_SKUS,
            "cobertura_pct": round((con_vencimiento.count / settings.TOTAL_SKUS) * 100, 1),
            "estado": "OK" if con_vencimiento.count >= settings.TOTAL_SKUS * 0.6 else "PARCIAL"
        }
        
        # Calcular promedio
        promedio = sum(v["cobertura_pct"] for v in validaciones.values()) / 4
        
        return {
            "success": True,
            "data": {
                "validaciones": validaciones,
                "promedio_cobertura": round(promedio, 1),
                "estado_general": "OK" if promedio >= 80 else "REQUIERE_ATENCION",
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error validando calidad: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# VIABILIDAD DEL SISTEMA (OE4)
# =====================================================================

@router.get("/viabilidad")
async def obtener_viabilidad_sistema():
    """
    Obtiene evaluación de viabilidad del sistema (OE4)
    
    Valores verificados (MARCO DE EVALUACIÓN DE VIABILIDAD.pdf):
    - Viabilidad Global: 89/100 puntos (ALTAMENTE VIABLE)
    - Técnica: 94%
    - Operativa: 87%
    - Económica: 86%
    
    Returns:
        dict: Evaluación completa de viabilidad
    """
    try:
        return {
            "success": True,
            "data": {
                "evaluacion_global": {
                    "puntuacion": settings.VIABILIDAD_GLOBAL,
                    "maximo": 100,
                    "clasificacion": settings.CLASIFICACION_VIABILIDAD,
                    "criterios_clasificacion": {
                        "85-100": "ALTAMENTE VIABLE - Implementación recomendada",
                        "70-84": "VIABLE CON AJUSTES - Implementación condicionada",
                        "55-69": "PARCIALMENTE VIABLE - Rediseñar componentes",
                        "<55": "NO VIABLE - Replantear enfoque"
                    }
                },
                "dimensiones": {
                    "tecnica": {
                        "puntuacion_pct": settings.VIABILIDAD_TECNICA_PCT,
                        "peso": "60%",
                        "componentes": {
                            "mape_promedio": f"{settings.XGBOOST_MAPE_PROMEDIO}%",
                            "disponibilidad_sistema": f"≥{settings.SLO_DISPONIBILIDAD_PCT}%",
                            "latencia_dashboard": f"<{settings.SLO_LATENCIA_TABLERO_MS}ms"
                        }
                    },
                    "operativa": {
                        "puntuacion_pct": settings.VIABILIDAD_OPERATIVA_PCT,
                        "peso": "25%",
                        "componentes": {
                            "alertas_accionables": f"{settings.ALERTAS_ACCIONABLES_PCT}%",
                            "horizonte_optimo": f"{settings.HORIZONTE_OPTIMO} días"
                        }
                    },
                    "economica": {
                        "puntuacion_pct": settings.VIABILIDAD_ECONOMICA_PCT,
                        "peso": "15%",
                        "componentes": {
                            "costo_mensual_estimado": "$40-60 USD",
                            "roi_estimado": "Reducción de pérdidas por quiebres"
                        }
                    }
                },
                "metricas_clave": {
                    "ml": {
                        "algoritmo": "XGBoost",
                        "mae_promedio": settings.XGBOOST_MAE_PROMEDIO,
                        "mape_promedio": settings.XGBOOST_MAPE_PROMEDIO,
                        "scoring": f"{settings.XGBOOST_SCORING}/100"
                    },
                    "alertas": {
                        "evaluadas": settings.TOTAL_ALERTAS_EVALUADAS,
                        "accionables": settings.ALERTAS_ACCIONABLES,
                        "porcentaje": f"{settings.ALERTAS_ACCIONABLES_PCT}%"
                    },
                    "arquitectura": {
                        "well_architected_cumplidos": settings.WELL_ARCHITECTED_CUMPLIDOS,
                        "well_architected_total": settings.WELL_ARCHITECTED_TOTAL,
                        "cumplimiento_pct": round((settings.WELL_ARCHITECTED_CUMPLIDOS / settings.WELL_ARCHITECTED_TOTAL) * 100)
                    }
                },
                "fuente": "MARCO_DE_EVALUACIÓN_DE_VIABILIDAD.pdf"
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo viabilidad: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas-tesis")
async def obtener_metricas_tesis():
    """
    Obtiene todas las métricas verificadas de la tesis en un solo endpoint
    
    Returns:
        dict: Métricas consolidadas por objetivo específico
    """
    try:
        return {
            "success": True,
            "data": {
                "proyecto": {
                    "titulo": "Sistema de Información con Capacidades Predictivas",
                    "cliente": "Farmacias Siman - Sucursal Circunvalación, SPS",
                    "investigador": "Gary González Zepeda",
                    "maestria": "Gestión de Tecnologías de la Información (GTI), UNITEC Honduras"
                },
                "OE1_identificacion_requisitos": {
                    "alcance": {
                        "total_skus": settings.TOTAL_SKUS,
                        "registros_historicos": settings.TOTAL_REGISTROS_VENTAS,
                        "periodo_dias": settings.TOTAL_DIAS,
                        "fecha_inicio": settings.PERIODO_INICIO,
                        "fecha_fin": settings.PERIODO_FIN,
                        "grupos_terapeuticos": settings.GRUPOS_TERAPEUTICOS,
                        "medicamentos_esenciales": settings.MEDICAMENTOS_ESENCIALES
                    },
                    "encuesta": {
                        "participantes": settings.PARTICIPANTES_ENCUESTA,
                        "disponibilidad_datos_promedio": settings.DISPONIBILIDAD_DATOS_PROMEDIO
                    },
                    "distribucion_abc": {
                        "A": settings.CATEGORIA_A,
                        "B": settings.CATEGORIA_B,
                        "C": settings.CATEGORIA_C
                    }
                },
                "OE2_tecnicas_ia": {
                    "algoritmo_ganador": "XGBoost",
                    "scoring": f"{settings.XGBOOST_SCORING}/100",
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
                    "horizonte_optimo": settings.HORIZONTE_OPTIMO,
                    "backtesting_registros": settings.TOTAL_BACKTEST_RECORDS
                },
                "OE3_arquitectura": {
                    "well_architected": {
                        "cumplidos": settings.WELL_ARCHITECTED_CUMPLIDOS,
                        "total": settings.WELL_ARCHITECTED_TOTAL,
                        "porcentaje": round((settings.WELL_ARCHITECTED_CUMPLIDOS / settings.WELL_ARCHITECTED_TOTAL) * 100)
                    },
                    "slos": {
                        "disponibilidad": f"≥{settings.SLO_DISPONIBILIDAD_PCT}% mensual",
                        "latencia_tablero": f"<{settings.SLO_LATENCIA_TABLERO_MS}ms",
                        "latencia_alertas": f"<{settings.SLO_LATENCIA_ALERTAS_MS}ms",
                        "error_budget": f"{settings.ERROR_BUDGET_HORAS}h/mes"
                    }
                },
                "OE4_viabilidad": {
                    "global": {
                        "puntuacion": settings.VIABILIDAD_GLOBAL,
                        "clasificacion": settings.CLASIFICACION_VIABILIDAD
                    },
                    "dimensiones": {
                        "tecnica": settings.VIABILIDAD_TECNICA_PCT,
                        "operativa": settings.VIABILIDAD_OPERATIVA_PCT,
                        "economica": settings.VIABILIDAD_ECONOMICA_PCT
                    },
                    "alertas": {
                        "evaluadas": settings.TOTAL_ALERTAS_EVALUADAS,
                        "accionables": settings.ALERTAS_ACCIONABLES,
                        "porcentaje": settings.ALERTAS_ACCIONABLES_PCT,
                        "dias_promedio_stockout": settings.DIAS_PROMEDIO_STOCKOUT,
                        "score_urgencia_promedio": settings.SCORE_URGENCIA_PROMEDIO,
                        "total_ordenar": settings.TOTAL_RECOMENDADO_ORDENAR
                    },
                    "distribucion_riesgo": {
                        "MEDIUM": settings.RIESGO_MEDIUM,
                        "HIGH": settings.RIESGO_HIGH,
                        "CRITICAL": settings.RIESGO_CRITICAL
                    }
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas de tesis: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
