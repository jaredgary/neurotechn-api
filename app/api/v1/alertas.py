"""
Endpoints para gestión de Alertas
"""

from fastapi import APIRouter, HTTPException, Query, Path, Body
from typing import Optional, List
from datetime import datetime
from app.database import supabase_client, supabase_admin
from app.models.alerta import (
    Alerta, AlertaUpdate, NivelRiesgo, EstadoAlerta
)
from app.services.alerta_service import AlertaService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_alertas(
    estado: Optional[EstadoAlerta] = Query(None, description="Filtrar por estado"),
    nivel_riesgo: Optional[NivelRiesgo] = Query(None, description="Filtrar por nivel de riesgo"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU"),
    limit: int = Query(120, ge=1, le=150, description="Número de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación")
):
    """
    Lista alertas con filtros y paginación
    
    Args:
        estado: Filtrar por estado (pendiente/atendida/descartada)
        nivel_riesgo: Filtrar por nivel (CRITICAL/HIGH/MEDIUM)
        sku: Filtrar por SKU específico
        limit: Máximo de resultados (1-150)
        offset: Offset para paginación
        
    Returns:
        dict: Lista de alertas con información del medicamento
    """
    try:
        # Construir query
        query = supabase_client.table('alertas') \
            .select(
                '*, catalogo_medicamentos('
                'nombre_comercial, grupo_terapeutico, categoria_abc, es_esencial'
                ')'
            )
        
        # Aplicar filtros
        if estado:
            query = query.eq('estado', estado.value)
        if nivel_riesgo:
            query = query.eq('nivel_riesgo', nivel_riesgo.value)
        if sku:
            query = query.eq('sku', sku)
        
        # Ordenar por urgencia y fecha
        query = query.order('score_urgencia', desc=True) \
                    .order('fecha_generacion', desc=True) \
                    .range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Obtener total count
        count_query = supabase_client.table('alertas').select('count', count='exact')
        if estado:
            count_query = count_query.eq('estado', estado.value)
        if nivel_riesgo:
            count_query = count_query.eq('nivel_riesgo', nivel_riesgo.value)
        if sku:
            count_query = count_query.eq('sku', sku)
        
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "alertas": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset
            }
        }
        
    except Exception as e:
        logger.error(f"Error listando alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{alerta_id}")
async def obtener_alerta(
    alerta_id: int = Path(..., description="ID de la alerta")
):
    """
    Obtiene detalle completo de una alerta
    
    Args:
        alerta_id: ID de la alerta
        
    Returns:
        dict: Alerta con medicamento, inventario y factores explicativos
    """
    try:
        # Obtener alerta con relaciones
        result = supabase_client.table('alertas') \
            .select(
                '*, '
                'catalogo_medicamentos(*), '
                'inventarios_actuales(stock_actual, stock_proyectado_14d, fecha_vencimiento)'
            ) \
            .eq('id', alerta_id) \
            .single() \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Alerta {alerta_id} no encontrada")
        
        alerta = result.data
        
        # Obtener factores explicativos si no están en la alerta
        if not alerta.get('factores_explicativos'):
            factores = await AlertaService.obtener_factores_explicativos(alerta['sku'])
            alerta['factores_explicativos'] = factores
        
        return {
            "success": True,
            "data": alerta
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo alerta {alerta_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{alerta_id}/atender")
async def atender_alerta(
    alerta_id: int = Path(..., description="ID de la alerta"),
    data: dict = Body(
        ...,
        example={
            "accion_tomada": "Pedido realizado a proveedor por 144 unidades",
            "atendida_por": "María José Hernández"
        }
    )
):
    """
    Marca una alerta como atendida
    
    Args:
        alerta_id: ID de la alerta
        data: Información de la acción tomada
        
    Returns:
        dict: Alerta actualizada
    """
    try:
        # Validar que la alerta existe
        check = supabase_client.table('alertas').select('id').eq('id', alerta_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail=f"Alerta {alerta_id} no encontrada")
        
        # Actualizar alerta
        update_data = {
            "estado": "atendida",
            "accion_tomada": data.get("accion_tomada"),
            "atendida_por": data.get("atendida_por"),
            "fecha_atencion": datetime.now().isoformat()
        }
        
        result = supabase_admin.table('alertas') \
            .update(update_data) \
            .eq('id', alerta_id) \
            .execute()
        
        logger.info(f"Alerta {alerta_id} atendida por {data.get('atendida_por')}")
        
        return {
            "success": True,
            "data": result.data[0] if result.data else None,
            "message": "Alerta marcada como atendida exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error atendiendo alerta {alerta_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{alerta_id}/descartar")
async def descartar_alerta(
    alerta_id: int = Path(..., description="ID de la alerta"),
    motivo: Optional[str] = Body(None, embed=True, description="Motivo del descarte")
):
    """
    Marca una alerta como descartada
    
    Args:
        alerta_id: ID de la alerta
        motivo: Motivo opcional del descarte
        
    Returns:
        dict: Alerta actualizada
    """
    try:
        # Validar que la alerta existe
        check = supabase_client.table('alertas').select('id').eq('id', alerta_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail=f"Alerta {alerta_id} no encontrada")
        
        # Actualizar alerta
        update_data = {
            "estado": "descartada",
            "accion_tomada": motivo or "Alerta descartada por usuario"
        }
        
        result = supabase_admin.table('alertas') \
            .update(update_data) \
            .eq('id', alerta_id) \
            .execute()
        
        logger.info(f"Alerta {alerta_id} descartada")
        
        return {
            "success": True,
            "data": result.data[0] if result.data else None,
            "message": "Alerta descartada exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error descartando alerta {alerta_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generar")
async def generar_alertas():
    """
    Genera alertas automáticas para todos los SKUs en riesgo
    Utiliza la función PostgreSQL generar_alertas_batch()
    
    Returns:
        dict: Número de alertas generadas y lista de alertas
    """
    try:
        resultado = await AlertaService.generar_alertas_automaticas()
        
        logger.info(f"Generadas {resultado['alertas_generadas']} alertas automáticas")
        
        return {
            "success": True,
            "data": resultado,
            "message": f"{resultado['alertas_generadas']} alertas generadas exitosamente"
        }
        
    except Exception as e:
        logger.error(f"Error generando alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas/distribucion")
async def obtener_distribucion_alertas():
    """
    Obtiene distribución de alertas por nivel de riesgo y estado
    
    Returns:
        dict: Estadísticas de distribución
    """
    try:
        # Alertas por nivel de riesgo
        por_nivel = {}
        for nivel in ['CRITICAL', 'HIGH', 'MEDIUM']:
            result = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('nivel_riesgo', nivel) \
                .eq('estado', 'pendiente') \
                .execute()
            por_nivel[nivel] = result.count
        
        # Alertas por estado
        por_estado = {}
        for estado in ['pendiente', 'atendida', 'descartada']:
            result = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('estado', estado) \
                .execute()
            por_estado[estado] = result.count
        
        return {
            "success": True,
            "data": {
                "por_nivel_riesgo": por_nivel,
                "por_estado": por_estado,
                "total": sum(por_estado.values())
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo distribución de alertas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))