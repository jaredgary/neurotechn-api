"""
Endpoints para gestión de Inventarios
"""

from fastapi import APIRouter, HTTPException, Query, Path, Body
from typing import Optional
from datetime import datetime, date, timedelta
from app.database import supabase_client, supabase_admin
from app.models.inventario import InventarioUpdate
from app.models.medicamento import CategoriaABC
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_inventarios(
    categoria_abc: Optional[CategoriaABC] = Query(None, description="Filtrar por categoría ABC"),
    es_esencial: Optional[bool] = Query(None, description="Filtrar medicamentos esenciales"),
    stock_bajo: Optional[bool] = Query(None, description="Solo mostrar stock bajo"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Lista inventarios con filtros
    
    Args:
        categoria_abc: Filtrar por categoría (A/B/C)
        es_esencial: Filtrar medicamentos esenciales
        stock_bajo: Mostrar solo stock proyectado < stock_seguridad
        limit: Máximo de resultados
        offset: Offset para paginación
        
    Returns:
        dict: Lista de inventarios con información del medicamento
    """
    try:
        # Construir query con join al catálogo
        query = supabase_client.table('inventarios_actuales') \
            .select(
                '*, catalogo_medicamentos('
                'nombre_comercial, nombre_generico, grupo_terapeutico, '
                'categoria_abc, es_esencial, stock_seguridad, lead_time_dias'
                ')'
            )
        
        # Aplicar filtros en el catálogo (usando inner join)
        if categoria_abc or es_esencial is not None:
            # Necesitamos filtrar primero el catálogo
            cat_query = supabase_client.table('catalogo_medicamentos').select('sku')
            if categoria_abc:
                cat_query = cat_query.eq('categoria_abc', categoria_abc.value)
            if es_esencial is not None:
                cat_query = cat_query.eq('es_esencial', es_esencial)
            
            cat_result = cat_query.execute()
            skus_filtrados = [r['sku'] for r in cat_result.data]
            
            if skus_filtrados:
                query = query.in_('sku', skus_filtrados)
            else:
                return {
                    "success": True,
                    "data": {
                        "inventarios": [],
                        "total": 0,
                        "limit": limit,
                        "offset": offset
                    }
                }
        
        # Filtrar por stock bajo (proyectado < seguridad)
        if stock_bajo:
            query = query.lt('stock_proyectado_14d', 0)
        
        # Ordenar y paginar
        query = query.order('stock_proyectado_14d') \
                    .range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Calcular total
        count_query = supabase_client.table('inventarios_actuales').select('count', count='exact')
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "inventarios": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset
            }
        }
        
    except Exception as e:
        logger.error(f"Error listando inventarios: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sku}")
async def obtener_inventario(
    sku: str = Path(..., description="SKU del medicamento")
):
    """
    Obtiene detalle completo de un inventario
    
    Args:
        sku: SKU del medicamento
        
    Returns:
        dict: Inventario con medicamento, predicciones y alertas
    """
    try:
        # Obtener inventario con medicamento
        result = supabase_client.table('inventarios_actuales') \
            .select('*, catalogo_medicamentos(*)') \
            .eq('sku', sku) \
            .single() \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Inventario para SKU {sku} no encontrado")
        
        inventario = result.data
        
        # Obtener última predicción (horizonte 14d)
        pred_result = supabase_client.table('predicciones') \
            .select('*') \
            .eq('sku', sku) \
            .eq('horizonte_dias', 14) \
            .order('fecha_prediccion', desc=True) \
            .limit(1) \
            .execute()
        
        inventario['ultima_prediccion'] = pred_result.data[0] if pred_result.data else None
        
        # Obtener alertas activas
        alertas_result = supabase_client.table('alertas') \
            .select('count', count='exact') \
            .eq('sku', sku) \
            .eq('estado', 'pendiente') \
            .execute()
        
        inventario['alertas_activas'] = alertas_result.count
        
        return {
            "success": True,
            "data": inventario
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo inventario {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{sku}")
async def actualizar_inventario(
    sku: str = Path(..., description="SKU del medicamento"),
    data: dict = Body(
        ...,
        example={
            "stock_actual": 500,
            "fecha_vencimiento": "2026-12-31",
            "lote": "LOTE-2025-5678"
        }
    )
):
    """
    Actualiza inventario de un medicamento
    Trigger automáticamente recalcula stocks proyectados
    
    Args:
        sku: SKU del medicamento
        data: Datos a actualizar
        
    Returns:
        dict: Inventario actualizado
    """
    try:
        # Validar que el SKU existe
        check = supabase_client.table('inventarios_actuales').select('sku').eq('sku', sku).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail=f"Inventario para SKU {sku} no encontrado")
        
        # Preparar datos de actualización
        update_data = {}
        if 'stock_actual' in data:
            update_data['stock_actual'] = data['stock_actual']
        if 'fecha_vencimiento' in data:
            update_data['fecha_vencimiento'] = data['fecha_vencimiento']
        if 'lote' in data:
            update_data['lote'] = data['lote']
        
        update_data['fecha_ultima_actualizacion'] = datetime.now().isoformat()
        
        # Actualizar
        result = supabase_admin.table('inventarios_actuales') \
            .update(update_data) \
            .eq('sku', sku) \
            .execute()
        
        logger.info(f"Inventario {sku} actualizado: {update_data}")
        
        return {
            "success": True,
            "data": result.data[0] if result.data else None,
            "message": "Inventario actualizado exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando inventario {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analisis/proximos-vencer")
async def obtener_proximos_vencer(
    dias: int = Query(60, ge=1, le=365, description="Días de anticipación")
):
    """
    Obtiene medicamentos con vencimiento próximo
    
    Args:
        dias: Días de anticipación (default: 60)
        
    Returns:
        dict: Lista de medicamentos próximos a vencer
    """
    try:
        fecha_limite = (date.today() + timedelta(days=dias)).isoformat()
        
        result = supabase_client.table('inventarios_actuales') \
            .select('*, catalogo_medicamentos(nombre_comercial, categoria_abc, precio_unitario_lps)') \
            .not_.is_('fecha_vencimiento', 'null') \
            .lte('fecha_vencimiento', fecha_limite) \
            .order('fecha_vencimiento') \
            .execute()
        
        # Calcular días restantes y valor en riesgo
        for item in result.data:
            if item.get('fecha_vencimiento'):
                vencimiento = datetime.fromisoformat(item['fecha_vencimiento'].replace('Z', '+00:00')).date()
                item['dias_restantes'] = (vencimiento - date.today()).days
                
                # Calcular valor en riesgo
                precio = item.get('catalogo_medicamentos', {}).get('precio_unitario_lps', 0)
                item['valor_riesgo_lps'] = item['stock_actual'] * precio
        
        return {
            "success": True,
            "data": {
                "medicamentos": result.data,
                "total": len(result.data),
                "dias_anticipacion": dias
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo medicamentos próximos a vencer: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analisis/stock-negativo")
async def obtener_stock_negativo():
    """
    Obtiene SKUs con stock proyectado negativo (en riesgo de quiebre)
    
    Returns:
        dict: Lista de SKUs en riesgo ordenados por urgencia
    """
    try:
        result = supabase_client.table('inventarios_actuales') \
            .select('*, catalogo_medicamentos(nombre_comercial, es_esencial, lead_time_dias)') \
            .lt('stock_proyectado_14d', 0) \
            .order('stock_proyectado_14d') \
            .execute()
        
        return {
            "success": True,
            "data": {
                "skus_en_riesgo": result.data,
                "total": len(result.data)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo SKUs con stock negativo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas/resumen")
async def obtener_resumen_inventarios():
    """
    Obtiene estadísticas generales de inventarios
    
    Returns:
        dict: Estadísticas consolidadas
    """
    try:
        # Total SKUs
        total = supabase_client.table('inventarios_actuales').select('count', count='exact').execute()
        
        # SKUs con stock negativo
        negativos = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .lt('stock_proyectado_14d', 0) \
            .execute()
        
        # SKUs con vencimiento próximo (60 días)
        fecha_limite = (date.today() + timedelta(days=60)).isoformat()
        vencimientos = supabase_client.table('inventarios_actuales') \
            .select('count', count='exact') \
            .not_.is_('fecha_vencimiento', 'null') \
            .lte('fecha_vencimiento', fecha_limite) \
            .execute()
        
        # Valor total inventario
        inventarios = supabase_client.table('inventarios_actuales') \
            .select('stock_actual, sku, catalogo_medicamentos(precio_unitario_lps)') \
            .execute()
        
        valor_total = sum(
            item['stock_actual'] * item.get('catalogo_medicamentos', {}).get('precio_unitario_lps', 0)
            for item in inventarios.data
        )
        
        return {
            "success": True,
            "data": {
                "total_skus": total.count,
                "skus_riesgo_quiebre": negativos.count,
                "skus_proximos_vencer": vencimientos.count,
                "valor_total_inventario_lps": round(valor_total, 2),
                "fecha_actualizacion": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo resumen de inventarios: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))