"""
Endpoints para Ventas Diarias
Acceso a los 10,800 registros históricos (120 SKUs × 90 días)
Período: 2025-08-02 a 2025-10-30
"""

from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from datetime import date, datetime, timedelta
from app.database import supabase_client
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_ventas(
    sku: Optional[str] = Query(None, description="Filtrar por SKU"),
    fecha_inicio: Optional[date] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_fin: Optional[date] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    demanda_minima: Optional[int] = Query(None, ge=0, description="Demanda mínima"),
    limit: int = Query(100, ge=1, le=1000, description="Máximo de registros"),
    offset: int = Query(0, ge=0, description="Offset para paginación")
):
    """
    Lista ventas diarias con filtros
    
    Args:
        sku: Filtrar por SKU específico
        fecha_inicio: Fecha inicio del período
        fecha_fin: Fecha fin del período
        demanda_minima: Filtrar demanda >= valor
        limit: Máximo de resultados (1-1000)
        offset: Offset para paginación
        
    Returns:
        dict: Lista de ventas con paginación
    """
    try:
        query = supabase_client.table('ventas_diarias').select('*')
        
        # Aplicar filtros
        if sku:
            query = query.eq('sku', sku)
        if fecha_inicio:
            query = query.gte('fecha', fecha_inicio.isoformat())
        if fecha_fin:
            query = query.lte('fecha', fecha_fin.isoformat())
        if demanda_minima is not None:
            query = query.gte('demanda', demanda_minima)
        
        # Ordenar y paginar
        query = query.order('fecha', desc=True).order('sku').range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Obtener count total
        count_query = supabase_client.table('ventas_diarias').select('count', count='exact')
        if sku:
            count_query = count_query.eq('sku', sku)
        if fecha_inicio:
            count_query = count_query.gte('fecha', fecha_inicio.isoformat())
        if fecha_fin:
            count_query = count_query.lte('fecha', fecha_fin.isoformat())
        if demanda_minima is not None:
            count_query = count_query.gte('demanda', demanda_minima)
            
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "ventas": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset,
                "periodo": {
                    "inicio": settings.PERIODO_INICIO,
                    "fin": settings.PERIODO_FIN,
                    "total_dias": settings.TOTAL_DIAS
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error listando ventas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas")
async def obtener_estadisticas_ventas():
    """
    Obtiene estadísticas generales de ventas
    
    Returns:
        dict: Estadísticas consolidadas del histórico de ventas
    """
    try:
        # Total registros
        total = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
        
        # Registros con demanda cero
        demanda_cero = supabase_client.table('ventas_diarias') \
            .select('count', count='exact') \
            .eq('demanda', 0) \
            .execute()
        
        # SKUs únicos
        skus = supabase_client.table('ventas_diarias').select('sku').execute()
        skus_unicos = len(set(v['sku'] for v in skus.data))
        
        # Rango de fechas
        fechas = supabase_client.table('ventas_diarias') \
            .select('fecha') \
            .order('fecha') \
            .limit(1) \
            .execute()
        fecha_min = fechas.data[0]['fecha'] if fechas.data else None
        
        fechas_max = supabase_client.table('ventas_diarias') \
            .select('fecha') \
            .order('fecha', desc=True) \
            .limit(1) \
            .execute()
        fecha_max = fechas_max.data[0]['fecha'] if fechas_max.data else None
        
        return {
            "success": True,
            "data": {
                "total_registros": total.count,
                "registros_esperados": settings.TOTAL_REGISTROS_VENTAS,
                "cobertura_pct": round((total.count / settings.TOTAL_REGISTROS_VENTAS) * 100, 1),
                "demandas_cero": demanda_cero.count,
                "demandas_cero_pct": round((demanda_cero.count / total.count) * 100, 2) if total.count > 0 else 0,
                "demandas_cero_esperadas": settings.DEMANDAS_CERO,
                "skus_unicos": skus_unicos,
                "skus_esperados": settings.TOTAL_SKUS,
                "periodo": {
                    "fecha_inicio": fecha_min,
                    "fecha_fin": fecha_max,
                    "fecha_inicio_esperada": settings.PERIODO_INICIO,
                    "fecha_fin_esperada": settings.PERIODO_FIN
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas de ventas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-sku/{sku}")
async def obtener_ventas_por_sku(
    sku: str = Path(..., description="SKU del medicamento"),
    dias: int = Query(90, ge=7, le=90, description="Días de histórico")
):
    """
    Obtiene histórico de ventas para un SKU específico
    
    Args:
        sku: SKU del medicamento
        dias: Número de días de histórico
        
    Returns:
        dict: Ventas del SKU con estadísticas
    """
    try:
        # Validar que el SKU existe
        check = supabase_client.table('catalogo_medicamentos') \
            .select('sku, nombre_comercial') \
            .eq('sku', sku) \
            .execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail=f"SKU {sku} no encontrado")
        
        medicamento = check.data[0]
        
        # Obtener ventas
        result = supabase_client.table('ventas_diarias') \
            .select('*') \
            .eq('sku', sku) \
            .order('fecha', desc=True) \
            .limit(dias) \
            .execute()
        
        # Calcular estadísticas
        demandas = [v['demanda'] for v in result.data]
        
        estadisticas = {
            "total_registros": len(demandas),
            "demanda_total": sum(demandas),
            "demanda_promedio": round(sum(demandas) / len(demandas), 2) if demandas else 0,
            "demanda_maxima": max(demandas) if demandas else 0,
            "demanda_minima": min(demandas) if demandas else 0,
            "dias_sin_demanda": demandas.count(0)
        }
        
        return {
            "success": True,
            "data": {
                "sku": sku,
                "nombre_comercial": medicamento['nombre_comercial'],
                "ventas": result.data,
                "estadisticas": estadisticas
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo ventas de {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tendencia-demanda")
async def obtener_tendencia_demanda(
    dias: int = Query(30, ge=7, le=90, description="Días de histórico"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU específico")
):
    """
    Obtiene tendencia de demanda agregada por día
    
    Args:
        dias: Días de histórico
        sku: SKU específico (opcional)
        
    Returns:
        dict: Demanda agregada por día para gráficas
    """
    try:
        fecha_inicio = (date.today() - timedelta(days=dias)).isoformat()
        
        query = supabase_client.table('ventas_diarias') \
            .select('fecha, demanda') \
            .gte('fecha', fecha_inicio)
        
        if sku:
            query = query.eq('sku', sku)
        
        result = query.execute()
        
        # Agregar por fecha
        por_fecha = {}
        for venta in result.data:
            fecha = venta['fecha']
            if fecha not in por_fecha:
                por_fecha[fecha] = {'demanda_total': 0, 'registros': 0}
            por_fecha[fecha]['demanda_total'] += venta['demanda']
            por_fecha[fecha]['registros'] += 1
        
        # Convertir a lista ordenada
        tendencia = [
            {
                "fecha": fecha,
                "demanda_total": datos['demanda_total'],
                "demanda_promedio": round(datos['demanda_total'] / datos['registros'], 2)
            }
            for fecha, datos in sorted(por_fecha.items())
        ]
        
        return {
            "success": True,
            "data": {
                "tendencia": tendencia,
                "dias": dias,
                "sku_filtro": sku
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo tendencia de demanda: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-demanda")
async def obtener_top_demanda(
    dias: int = Query(30, ge=7, le=90, description="Días de histórico"),
    limit: int = Query(10, ge=1, le=50, description="Cantidad de SKUs")
):
    """
    Obtiene SKUs con mayor demanda en el período
    
    Args:
        dias: Días de histórico
        limit: Cantidad de SKUs a retornar
        
    Returns:
        dict: Top SKUs por demanda total
    """
    try:
        fecha_inicio = (date.today() - timedelta(days=dias)).isoformat()
        
        # Obtener todas las ventas del período
        result = supabase_client.table('ventas_diarias') \
            .select('sku, demanda') \
            .gte('fecha', fecha_inicio) \
            .execute()
        
        # Agregar por SKU
        por_sku = {}
        for venta in result.data:
            sku = venta['sku']
            if sku not in por_sku:
                por_sku[sku] = 0
            por_sku[sku] += venta['demanda']
        
        # Ordenar y tomar top
        top_skus = sorted(por_sku.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        # Obtener nombres de medicamentos
        skus_list = [sku for sku, _ in top_skus]
        medicamentos = supabase_client.table('catalogo_medicamentos') \
            .select('sku, nombre_comercial, categoria_abc, es_esencial') \
            .in_('sku', skus_list) \
            .execute()
        
        med_dict = {m['sku']: m for m in medicamentos.data}
        
        resultado = [
            {
                "sku": sku,
                "demanda_total": demanda,
                "nombre_comercial": med_dict.get(sku, {}).get('nombre_comercial', 'N/A'),
                "categoria_abc": med_dict.get(sku, {}).get('categoria_abc', 'N/A'),
                "es_esencial": med_dict.get(sku, {}).get('es_esencial', False)
            }
            for sku, demanda in top_skus
        ]
        
        return {
            "success": True,
            "data": {
                "top_demanda": resultado,
                "dias": dias,
                "total_skus": len(por_sku)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo top demanda: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
