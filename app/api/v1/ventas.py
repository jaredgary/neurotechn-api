"""
Endpoints para Ventas Diarias
Versión 2.2 - Fix para Pronósticos

CORRECCIONES:
- top-demanda: usa fechas de datos disponibles, no date.today()
- Nuevo endpoint: demanda-total para gráfico de pronósticos
- Respuestas incluyen nombre_generico para display completo
"""

from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from datetime import date, datetime, timedelta
from app.database import supabase_client
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def get_fecha_maxima_datos():
    """Obtiene la fecha máxima de los datos disponibles"""
    try:
        result = supabase_client.table('ventas_diarias') \
            .select('fecha') \
            .order('fecha', desc=True) \
            .limit(1) \
            .execute()
        if result.data:
            fecha_str = result.data[0]['fecha'][:10]  # Solo YYYY-MM-DD
            return datetime.fromisoformat(fecha_str).date()
        return date.today()
    except:
        return date.today()


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
    Lista ventas diarias con filtros.
    """
    try:
        query = supabase_client.table('ventas_diarias').select('*')
        
        if sku:
            query = query.eq('sku', sku)
        if fecha_inicio:
            query = query.gte('fecha', fecha_inicio.isoformat())
        if fecha_fin:
            query = query.lte('fecha', fecha_fin.isoformat())
        if demanda_minima is not None:
            query = query.gte('demanda', demanda_minima)
        
        query = query.order('fecha', desc=True).order('sku').range(offset, offset + limit - 1)
        result = query.execute()
        
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
        
        # Calcular período dinámicamente
        fechas_query = supabase_client.table('ventas_diarias').select('fecha').execute()
        if fechas_query.data:
            todas_fechas = [f['fecha'] for f in fechas_query.data]
            fecha_min = min(todas_fechas)
            fecha_max = max(todas_fechas)
            total_dias = (datetime.fromisoformat(fecha_max[:10]) - 
                         datetime.fromisoformat(fecha_min[:10])).days + 1
        else:
            fecha_min = None
            fecha_max = None
            total_dias = 0
        
        return {
            "success": True,
            "data": {
                "ventas": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset,
                "periodo": {
                    "inicio": fecha_min,
                    "fin": fecha_max,
                    "total_dias": total_dias
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error listando ventas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas")
async def obtener_estadisticas_ventas():
    """
    Obtiene estadísticas generales de ventas.
    """
    try:
        total = supabase_client.table('ventas_diarias').select('count', count='exact').execute()
        demanda_cero = supabase_client.table('ventas_diarias') \
            .select('count', count='exact') \
            .eq('demanda', 0) \
            .execute()
        
        skus = supabase_client.table('ventas_diarias').select('sku').execute()
        skus_unicos = len(set(v['sku'] for v in skus.data)) if skus.data else 0
        
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
        
        if fecha_min and fecha_max:
            dias_periodo = (
                datetime.fromisoformat(fecha_max[:10]) - 
                datetime.fromisoformat(fecha_min[:10])
            ).days + 1
        else:
            dias_periodo = 0
        
        registros_esperados = skus_unicos * dias_periodo if skus_unicos > 0 and dias_periodo > 0 else 0
        
        return {
            "success": True,
            "data": {
                "total_registros": total.count,
                "registros_esperados": registros_esperados,
                "cobertura_pct": round((total.count / registros_esperados) * 100, 1) if registros_esperados > 0 else 100.0,
                "demandas_cero": demanda_cero.count,
                "demandas_cero_pct": round((demanda_cero.count / total.count) * 100, 2) if total.count > 0 else 0,
                "skus_unicos": skus_unicos,
                "periodo": {
                    "fecha_inicio": fecha_min,
                    "fecha_fin": fecha_max,
                    "total_dias": dias_periodo
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas de ventas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-sku/{sku}")
async def obtener_ventas_por_sku(
    sku: str = Path(..., description="SKU del medicamento"),
    dias: int = Query(90, ge=7, le=365, description="Días de histórico")
):
    """
    Obtiene histórico de ventas para un SKU específico
    """
    try:
        check = supabase_client.table('catalogo_medicamentos') \
            .select('sku, nombre_comercial') \
            .eq('sku', sku) \
            .execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail=f"SKU {sku} no encontrado")
        
        medicamento = check.data[0]
        
        result = supabase_client.table('ventas_diarias') \
            .select('*') \
            .eq('sku', sku) \
            .order('fecha', desc=True) \
            .limit(dias) \
            .execute()
        
        demandas = [v['demanda'] for v in result.data]
        
        estadisticas = {
            "total_registros": len(demandas),
            "demanda_total": sum(demandas) if demandas else 0,
            "demanda_promedio": round(sum(demandas) / len(demandas), 2) if demandas else 0,
            "demanda_maxima": max(demandas) if demandas else 0,
            "demanda_minima": min(demandas) if demandas else 0,
            "dias_sin_demanda": demandas.count(0) if demandas else 0
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
    dias: int = Query(30, ge=7, le=365, description="Días de histórico"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU específico")
):
    """
    Obtiene tendencia de demanda agregada por día
    """
    try:
        # ✅ CORREGIDO: Usar fecha máxima de datos, no date.today()
        fecha_max_datos = get_fecha_maxima_datos()
        fecha_inicio = (fecha_max_datos - timedelta(days=dias)).isoformat()
        
        query = supabase_client.table('ventas_diarias') \
            .select('fecha, demanda') \
            .gte('fecha', fecha_inicio)
        
        if sku:
            query = query.eq('sku', sku)
        
        result = query.execute()
        
        por_fecha = {}
        for venta in result.data:
            fecha = venta['fecha'][:10] if venta['fecha'] else None
            if fecha:
                if fecha not in por_fecha:
                    por_fecha[fecha] = {'demanda_total': 0, 'registros': 0}
                por_fecha[fecha]['demanda_total'] += venta['demanda']
                por_fecha[fecha]['registros'] += 1
        
        tendencia = [
            {
                "fecha": fecha,
                "demanda_total": datos['demanda_total'],
                "demanda_promedio": round(datos['demanda_total'] / datos['registros'], 2) if datos['registros'] > 0 else 0
            }
            for fecha, datos in sorted(por_fecha.items())
        ]
        
        return {
            "success": True,
            "data": {
                "tendencia": tendencia,
                "dias": dias,
                "sku_filtro": sku,
                "total_puntos": len(tendencia)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo tendencia de demanda: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-demanda")
async def obtener_top_demanda(
    dias: int = Query(30, ge=7, le=365, description="Días de histórico"),
    limit: int = Query(10, ge=1, le=100, description="Cantidad de SKUs")
):
    """
    Obtiene SKUs con mayor demanda en el período.
    
    ✅ CORREGIDO: Usa fecha máxima de datos disponibles, no date.today()
    ✅ CORREGIDO: Incluye nombre_generico para display completo
    ✅ CORREGIDO: Estructura de respuesta con 'items' para frontend
    """
    try:
        # ✅ CORREGIDO: Usar fecha máxima de datos, no date.today()
        fecha_max_datos = get_fecha_maxima_datos()
        fecha_inicio = (fecha_max_datos - timedelta(days=dias)).isoformat()
        
        logger.info(f"Top demanda: fecha_max_datos={fecha_max_datos}, fecha_inicio={fecha_inicio}, dias={dias}")
        
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
        
        # Obtener nombres de medicamentos (incluye nombre_generico)
        skus_list = [sku for sku, _ in top_skus]
        if skus_list:
            medicamentos = supabase_client.table('catalogo_medicamentos') \
                .select('sku, nombre_comercial, nombre_generico, categoria_abc, es_esencial') \
                .in_('sku', skus_list) \
                .execute()
            
            med_dict = {m['sku']: m for m in medicamentos.data}
        else:
            med_dict = {}
        
        # ✅ CORREGIDO: Estructura compatible con frontend
        resultado = [
            {
                "sku": sku,
                "demanda_total": demanda,
                "nombre_comercial": med_dict.get(sku, {}).get('nombre_comercial', 'N/A'),
                "nombre_generico": med_dict.get(sku, {}).get('nombre_generico', ''),
                "categoria_abc": med_dict.get(sku, {}).get('categoria_abc', 'N/A'),
                "es_esencial": med_dict.get(sku, {}).get('es_esencial', False)
            }
            for sku, demanda in top_skus
        ]
        
        return {
            "success": True,
            "data": {
                # ✅ CORREGIDO: Usa "items" para compatibilidad con frontend
                "items": resultado,
                "total": len(por_sku),
                "dias": dias,
                "fecha_desde": fecha_inicio,
                "fecha_hasta": fecha_max_datos.isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo top demanda: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/demanda-total")
async def obtener_demanda_total():
    """
    Obtiene demanda total proyectada por horizontes (7, 14, 28 días).
    
    ✅ NUEVO ENDPOINT para gráfico de Pronósticos
    Calcula la demanda total de los últimos N días de datos disponibles.
    """
    try:
        # Obtener fecha máxima de datos
        fecha_max_datos = get_fecha_maxima_datos()
        
        horizontes = {
            7: 0,
            14: 0,
            28: 0
        }
        
        for dias in [7, 14, 28]:
            fecha_inicio = (fecha_max_datos - timedelta(days=dias)).isoformat()
            
            result = supabase_client.table('ventas_diarias') \
                .select('demanda') \
                .gte('fecha', fecha_inicio) \
                .execute()
            
            total = sum(v['demanda'] for v in result.data) if result.data else 0
            horizontes[dias] = total
        
        return {
            "success": True,
            "data": {
                "horizonte_7d": horizontes[7],
                "horizonte_14d": horizontes[14],
                "horizonte_28d": horizontes[28],
                "fecha_referencia": fecha_max_datos.isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo demanda total: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
