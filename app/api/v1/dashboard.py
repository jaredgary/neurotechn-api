"""
Endpoints para Dashboard principal
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, date, timedelta
from app.database import supabase_client
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats")
async def obtener_estadisticas_dashboard():
    """
    Obtiene estadísticas principales para el dashboard
    
    Returns:
        dict: Indicadores clave del sistema
    """
    try:
        # Total alertas pendientes
        alertas = supabase_client.table('alertas') \
            .select('count', count='exact') \
            .eq('estado', 'pendiente') \
            .execute()
        
        # Alertas críticas
        alertas_criticas = supabase_client.table('alertas') \
            .select('count', count='exact') \
            .eq('estado', 'pendiente') \
            .eq('nivel_riesgo', 'CRITICAL') \
            .execute()
        
        # Alertas HIGH
        alertas_high = supabase_client.table('alertas') \
            .select('count', count='exact') \
            .eq('estado', 'pendiente') \
            .eq('nivel_riesgo', 'HIGH') \
            .execute()
        
        # SKUs con stock proyectado negativo
        inventarios_riesgo = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .lt('stock_proyectado_14d', 0) \
            .execute()
        
        # Total medicamentos
        total_medicamentos = supabase_client.table('catalogo_medicamentos') \
            .select('count', count='exact') \
            .execute()
        
        # Medicamentos esenciales en riesgo
        esenciales_riesgo = supabase_client.table('inventarios_actuales') \
            .select('*, catalogo_medicamentos!inner(es_esencial)', count='exact') \
            .eq('catalogo_medicamentos.es_esencial', True) \
            .lt('stock_proyectado_14d', 0) \
            .execute()
        
        return {
            "success": True,
            "data": {
                "alertas_pendientes": alertas.count,
                "alertas_criticas": alertas_criticas.count,
                "alertas_high": alertas_high.count,
                "skus_en_riesgo": inventarios_riesgo.count,
                "esenciales_en_riesgo": esenciales_riesgo.count,
                "total_medicamentos": total_medicamentos.count,
                "fecha_actualizacion": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alertas-recientes")
async def obtener_alertas_recientes(
    limit: int = Query(10, ge=1, le=50, description="Número de alertas a mostrar")
):
    """
    Obtiene las alertas más recientes ordenadas por urgencia
    
    Args:
        limit: Número máximo de alertas
        
    Returns:
        dict: Top N alertas pendientes
    """
    try:
        alertas = supabase_client.table('alertas') \
            .select(
                '*, catalogo_medicamentos('
                'nombre_comercial, grupo_terapeutico, categoria_abc, es_esencial'
                '), inventarios_actuales('
                'stock_actual, stock_proyectado_14d'
                ')'
            ) \
            .eq('estado', 'pendiente') \
            .order('score_urgencia', desc=True) \
            .order('fecha_generacion', desc=True) \
            .limit(limit) \
            .execute()
        
        return {
            "success": True,
            "data": {
                "alertas": alertas.data,
                "total": len(alertas.data)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo alertas recientes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventarios-criticos")
async def obtener_inventarios_criticos(
    limit: int = Query(10, ge=1, le=50, description="Número de registros")
):
    """
    Obtiene inventarios con stock proyectado más bajo
    
    Args:
        limit: Número máximo de registros
        
    Returns:
        dict: Top N inventarios críticos
    """
    try:
        inventarios = supabase_client.table('inventarios_actuales') \
            .select(
                '*, catalogo_medicamentos('
                'nombre_comercial, stock_seguridad, es_esencial, categoria_abc'
                ')'
            ) \
            .lt('stock_proyectado_14d', 0) \
            .order('stock_proyectado_14d') \
            .limit(limit) \
            .execute()
        
        return {
            "success": True,
            "data": {
                "inventarios": inventarios.data,
                "total": len(inventarios.data)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo inventarios críticos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tendencias")
async def obtener_tendencias(
    dias: int = Query(30, ge=7, le=90, description="Días de histórico")
):
    """
    Obtiene tendencias de alertas en los últimos N días
    
    Args:
        dias: Número de días de histórico (7-90)
        
    Returns:
        dict: Datos para gráficas de tendencias
    """
    try:
        fecha_inicio = (date.today() - timedelta(days=dias)).isoformat()
        
        # Obtener alertas del período
        alertas = supabase_client.table('alertas') \
            .select('fecha_generacion, nivel_riesgo, estado') \
            .gte('fecha_generacion', fecha_inicio) \
            .execute()
        
        # Agrupar por fecha y nivel de riesgo
        por_fecha = {}
        for alerta in alertas.data:
            fecha = alerta['fecha_generacion'][:10]  # Solo YYYY-MM-DD
            if fecha not in por_fecha:
                por_fecha[fecha] = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'total': 0}
            
            por_fecha[fecha][alerta['nivel_riesgo']] += 1
            por_fecha[fecha]['total'] += 1
        
        # Convertir a lista ordenada
        tendencias = [
            {
                "fecha": fecha,
                "critical": datos['CRITICAL'],
                "high": datos['HIGH'],
                "medium": datos['MEDIUM'],
                "total": datos['total']
            }
            for fecha, datos in sorted(por_fecha.items())
        ]
        
        # Distribución actual por nivel
        distribucion_actual = {
            'CRITICAL': 0,
            'HIGH': 0,
            'MEDIUM': 0
        }
        
        alertas_actuales = supabase_client.table('alertas') \
            .select('nivel_riesgo') \
            .eq('estado', 'pendiente') \
            .execute()
        
        for alerta in alertas_actuales.data:
            distribucion_actual[alerta['nivel_riesgo']] += 1
        
        return {
            "success": True,
            "data": {
                "tendencias_diarias": tendencias,
                "distribucion_actual": distribucion_actual,
                "periodo_dias": dias
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo tendencias: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resumen-general")
async def obtener_resumen_general():
    """
    Obtiene resumen completo del sistema para el dashboard
    Combina múltiples métricas en una sola respuesta
    
    Returns:
        dict: Resumen consolidado del sistema
    """
    try:
        # Estadísticas de alertas
        stats = await obtener_estadisticas_dashboard()
        
        # Alertas recientes (top 5)
        alertas_recientes = await obtener_alertas_recientes(limit=5)
        
        # Inventarios críticos (top 5)
        inventarios_criticos = await obtener_inventarios_criticos(limit=5)
        
        # Alertas atendidas hoy
        hoy = date.today().isoformat()
        atendidas_hoy = supabase_client.table('alertas') \
            .select('count', count='exact') \
            .eq('estado', 'atendida') \
            .gte('fecha_atencion', hoy) \
            .execute()
        
        return {
            "success": True,
            "data": {
                "estadisticas": stats['data'],
                "alertas_recientes": alertas_recientes['data']['alertas'],
                "inventarios_criticos": inventarios_criticos['data']['inventarios'],
                "alertas_atendidas_hoy": atendidas_hoy.count,
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo resumen general: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance-sistema")
async def obtener_performance_sistema():
    """
    Obtiene métricas de performance del sistema ML
    
    Returns:
        dict: Métricas de precisión y utilidad
    """
    try:
        # Métricas de backtest (OE2)
        backtest = supabase_client.table('backtest_results') \
            .select('mae, mape, horizon') \
            .eq('algorithm', 'XGBoost') \
            .execute()
        
        # Calcular promedios por horizonte
        metricas_por_horizonte = {}
        for record in backtest.data:
            horizonte = record['horizon']
            if horizonte not in metricas_por_horizonte:
                metricas_por_horizonte[horizonte] = {'mae_list': [], 'mape_list': []}
            
            if record.get('mae') is not None and record['mae'] < 10000:  # Filtrar outliers
                metricas_por_horizonte[horizonte]['mae_list'].append(record['mae'])
            if record.get('mape') is not None and record['mape'] < 100:  # Filtrar outliers
                metricas_por_horizonte[horizonte]['mape_list'].append(record['mape'])
        
        # Calcular promedios
        metricas = {}
        for horizonte, valores in metricas_por_horizonte.items():
            if valores['mae_list']:
                metricas[f"{horizonte}d"] = {
                    "mae_promedio": round(sum(valores['mae_list']) / len(valores['mae_list']), 2),
                    "mape_promedio": round(sum(valores['mape_list']) / len(valores['mape_list']), 2) if valores['mape_list'] else None
                }
        
        # Utilidad de alertas (OE4)
        total_alertas_evaluadas = 240  # Del estudio OE4
        alertas_accionables = 172  # Del estudio OE4
        
        return {
            "success": True,
            "data": {
                "metricas_ml": metricas,
                "horizonte_optimo": "14d",
                "utilidad_alertas": {
                    "total_evaluadas": total_alertas_evaluadas,
                    "accionables": alertas_accionables,
                    "porcentaje_accionables": round((alertas_accionables / total_alertas_evaluadas) * 100, 1)
                },
                "viabilidad_sistema": 89  # Puntos de 100 (OE4)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo performance del sistema: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))