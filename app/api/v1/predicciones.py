"""
Endpoints para Predicciones ML
"""

from fastapi import APIRouter, HTTPException, Query, Path, Body
from typing import Optional
from datetime import date, datetime
from app.database import supabase_client, supabase_admin
from app.models.prediccion import PrediccionCreate, HorizontePrediccion
from app.services.prediccion_service import PrediccionService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{sku}")
async def obtener_ultima_prediccion(
    sku: str = Path(..., description="SKU del medicamento"),
    horizonte: Optional[int] = Query(14, description="Horizonte en días (7, 14, 28)")
):
    """
    Obtiene última predicción para un SKU y horizonte
    
    Args:
        sku: SKU del medicamento
        horizonte: Horizonte de predicción (default: 14)
        
    Returns:
        dict: Predicción más reciente
    """
    try:
        result = supabase_client.table('predicciones') \
            .select('*, catalogo_medicamentos(nombre_comercial)') \
            .eq('sku', sku) \
            .eq('horizonte_dias', horizonte) \
            .order('fecha_prediccion', desc=True) \
            .limit(1) \
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404, 
                detail=f"No hay predicciones para SKU {sku} con horizonte {horizonte}d"
            )
        
        prediccion = result.data[0]
        
        # Calcular stock proyectado usando función PostgreSQL
        stock_proyectado = await PrediccionService.calcular_stock_proyectado(sku, horizonte)
        prediccion['stock_proyectado'] = stock_proyectado
        
        return {
            "success": True,
            "data": prediccion
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo predicción {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sku}/historico")
async def obtener_historico_predicciones(
    sku: str = Path(..., description="SKU del medicamento"),
    horizonte: Optional[int] = Query(None, description="Filtrar por horizonte"),
    limit: int = Query(30, ge=1, le=365)
):
    """
    Obtiene histórico de predicciones para un SKU
    
    Args:
        sku: SKU del medicamento
        horizonte: Filtrar por horizonte específico (opcional)
        limit: Número de predicciones a retornar
        
    Returns:
        dict: Histórico de predicciones
    """
    try:
        query = supabase_client.table('predicciones') \
            .select('*') \
            .eq('sku', sku)
        
        if horizonte:
            query = query.eq('horizonte_dias', horizonte)
        
        query = query.order('fecha_prediccion', desc=True).limit(limit)
        
        result = query.execute()
        
        return {
            "success": True,
            "data": {
                "predicciones": result.data,
                "total": len(result.data),
                "sku": sku
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo histórico {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def crear_prediccion(
    prediccion: PrediccionCreate
):
    """
    Crea nueva predicción (generada por modelo ML)
    Trigger automáticamente actualiza inventario
    
    Args:
        prediccion: Datos de la predicción
        
    Returns:
        dict: Predicción creada
    """
    try:
        # Validar que el SKU existe
        check = supabase_client.table('catalogo_medicamentos').select('sku').eq('sku', prediccion.sku).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail=f"SKU {prediccion.sku} no encontrado")
        
        # Preparar datos
        data = prediccion.model_dump()
        data['fecha_prediccion'] = data['fecha_prediccion'].isoformat()
        
        # Insertar predicción
        result = supabase_admin.table('predicciones') \
            .insert(data) \
            .execute()
        
        logger.info(f"Predicción creada para {prediccion.sku}, horizonte {prediccion.horizonte_dias}d")
        
        return {
            "success": True,
            "data": result.data[0] if result.data else None,
            "message": "Predicción creada exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando predicción: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas/agregadas")
async def obtener_metricas_agregadas():
    """
    Obtiene métricas de performance del modelo agregadas
    
    Returns:
        dict: MAE, MAPE promedio por horizonte
    """
    try:
        # Obtener todas las predicciones
        result = supabase_client.table('predicciones') \
            .select('horizonte_dias, mae, mape, sesgo') \
            .not_.is_('mae', 'null') \
            .execute()
        
        # Agrupar por horizonte
        metricas_por_horizonte = {}
        for pred in result.data:
            horizonte = pred['horizonte_dias']
            if horizonte not in metricas_por_horizonte:
                metricas_por_horizonte[horizonte] = {
                    'mae_list': [],
                    'mape_list': [],
                    'sesgo_list': []
                }
            
            metricas_por_horizonte[horizonte]['mae_list'].append(pred['mae'])
            if pred.get('mape') is not None:
                metricas_por_horizonte[horizonte]['mape_list'].append(pred['mape'])
            if pred.get('sesgo') is not None:
                metricas_por_horizonte[horizonte]['sesgo_list'].append(pred['sesgo'])
        
        # Calcular promedios
        metricas_finales = {}
        for horizonte, valores in metricas_por_horizonte.items():
            metricas_finales[f"{horizonte}d"] = {
                "mae_promedio": round(sum(valores['mae_list']) / len(valores['mae_list']), 2),
                "mape_promedio": round(sum(valores['mape_list']) / len(valores['mape_list']), 2) if valores['mape_list'] else None,
                "sesgo_promedio": round(sum(valores['sesgo_list']) / len(valores['sesgo_list']), 2) if valores['sesgo_list'] else None,
                "n_predicciones": len(valores['mae_list'])
            }
        
        return {
            "success": True,
            "data": {
                "metricas_por_horizonte": metricas_finales,
                "horizonte_optimo": "14d",
                "fecha_calculo": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas agregadas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analisis/comparacion-horizontes")
async def comparar_horizontes(
    sku: str = Query(..., description="SKU a comparar")
):
    """
    Compara predicciones de diferentes horizontes para un SKU
    
    Args:
        sku: SKU del medicamento
        
    Returns:
        dict: Predicciones por horizonte con análisis
    """
    try:
        # Obtener últimas predicciones de cada horizonte
        predicciones = {}
        for horizonte in [7, 14, 28]:
            result = supabase_client.table('predicciones') \
                .select('*') \
                .eq('sku', sku) \
                .eq('horizonte_dias', horizonte) \
                .order('fecha_prediccion', desc=True) \
                .limit(1) \
                .execute()
            
            if result.data:
                pred = result.data[0]
                stock_proyectado = await PrediccionService.calcular_stock_proyectado(sku, horizonte)
                pred['stock_proyectado'] = stock_proyectado
                predicciones[f"{horizonte}d"] = pred
        
        if not predicciones:
            raise HTTPException(status_code=404, detail=f"No hay predicciones para SKU {sku}")
        
        return {
            "success": True,
            "data": {
                "sku": sku,
                "predicciones": predicciones,
                "recomendacion": "Usar horizonte 14d (óptimo según OE2)"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparando horizontes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))