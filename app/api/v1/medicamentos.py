"""
Endpoints para Catálogo de Medicamentos
"""

from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from app.database import supabase_client
from app.models.medicamento import CategoriaABC
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_medicamentos(
    categoria_abc: Optional[CategoriaABC] = Query(None, description="Filtrar por categoría"),
    grupo_terapeutico: Optional[str] = Query(None, description="Filtrar por grupo terapéutico"),
    es_esencial: Optional[bool] = Query(None, description="Filtrar medicamentos esenciales"),
    requiere_receta: Optional[bool] = Query(None, description="Filtrar por requerimiento de receta"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Lista medicamentos del catálogo con filtros
    
    Args:
        categoria_abc: Categoría ABC (A/B/C)
        grupo_terapeutico: Grupo terapéutico (ej: "Antigripales")
        es_esencial: Filtrar esenciales
        requiere_receta: Filtrar por receta
        limit: Máximo de resultados
        offset: Offset para paginación
        
    Returns:
        dict: Lista de medicamentos
    """
    try:
        query = supabase_client.table('catalogo_medicamentos').select('*')
        
        # Aplicar filtros
        if categoria_abc:
            query = query.eq('categoria_abc', categoria_abc.value)
        if grupo_terapeutico:
            query = query.eq('grupo_terapeutico', grupo_terapeutico)
        if es_esencial is not None:
            query = query.eq('es_esencial', es_esencial)
        if requiere_receta is not None:
            query = query.eq('requiere_receta', requiere_receta)
        
        # Ordenar y paginar
        query = query.order('nombre_comercial').range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Obtener total
        count_query = supabase_client.table('catalogo_medicamentos').select('count', count='exact')
        if categoria_abc:
            count_query = count_query.eq('categoria_abc', categoria_abc.value)
        if grupo_terapeutico:
            count_query = count_query.eq('grupo_terapeutico', grupo_terapeutico)
        if es_esencial is not None:
            count_query = count_query.eq('es_esencial', es_esencial)
        if requiere_receta is not None:
            count_query = count_query.eq('requiere_receta', requiere_receta)
        
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "medicamentos": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset
            }
        }
        
    except Exception as e:
        logger.error(f"Error listando medicamentos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def buscar_medicamentos(
    q: str = Query(..., min_length=2, description="Término de búsqueda"),
    limit: int = Query(20, ge=1, le=50)
):
    """
    Búsqueda de medicamentos por nombre comercial o genérico
    
    Args:
        q: Término de búsqueda (mínimo 2 caracteres)
        limit: Máximo de resultados
        
    Returns:
        dict: Medicamentos que coinciden con la búsqueda
    """
    try:
        # Búsqueda en nombre_comercial
        result_comercial = supabase_client.table('catalogo_medicamentos') \
            .select('*') \
            .ilike('nombre_comercial', f'%{q}%') \
            .limit(limit) \
            .execute()
        
        # Búsqueda en nombre_generico
        result_generico = supabase_client.table('catalogo_medicamentos') \
            .select('*') \
            .ilike('nombre_generico', f'%{q}%') \
            .limit(limit) \
            .execute()
        
        # Combinar resultados únicos
        skus_vistos = set()
        resultados = []
        
        for item in result_comercial.data + result_generico.data:
            if item['sku'] not in skus_vistos:
                skus_vistos.add(item['sku'])
                resultados.append(item)
        
        return {
            "success": True,
            "data": {
                "medicamentos": resultados[:limit],
                "total": len(resultados),
                "query": q
            }
        }
        
    except Exception as e:
        logger.error(f"Error buscando medicamentos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sku}")
async def obtener_medicamento(
    sku: str = Path(..., description="SKU del medicamento")
):
    """
    Obtiene detalle completo de un medicamento
    Incluye inventario, predicciones y alertas activas
    
    Args:
        sku: SKU del medicamento
        
    Returns:
        dict: Información completa del medicamento
    """
    try:
        # Obtener medicamento del catálogo
        result = supabase_client.table('catalogo_medicamentos') \
            .select('*') \
            .eq('sku', sku) \
            .single() \
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail=f"Medicamento {sku} no encontrado")
        
        medicamento = result.data
        
        # Obtener inventario actual
        inv_result = supabase_client.table('inventarios_actuales') \
            .select('*') \
            .eq('sku', sku) \
            .execute()
        
        medicamento['inventario'] = inv_result.data[0] if inv_result.data else None
        
        # Obtener última predicción (horizonte 14d)
        pred_result = supabase_client.table('predicciones') \
            .select('*') \
            .eq('sku', sku) \
            .eq('horizonte_dias', 14) \
            .order('fecha_prediccion', desc=True) \
            .limit(1) \
            .execute()
        
        medicamento['ultima_prediccion'] = pred_result.data[0] if pred_result.data else None
        
        # Obtener alertas activas
        alertas_result = supabase_client.table('alertas') \
            .select('*') \
            .eq('sku', sku) \
            .eq('estado', 'pendiente') \
            .order('score_urgencia', desc=True) \
            .execute()
        
        medicamento['alertas_activas'] = alertas_result.data
        
        return {
            "success": True,
            "data": medicamento
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo medicamento {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categoria/esenciales")
async def obtener_medicamentos_esenciales():
    """
    Obtiene lista de medicamentos esenciales
    
    Returns:
        dict: Medicamentos esenciales ordenados por categoría ABC
    """
    try:
        result = supabase_client.table('catalogo_medicamentos') \
            .select('*, inventarios_actuales(stock_actual, stock_proyectado_14d)') \
            .eq('es_esencial', True) \
            .order('categoria_abc') \
            .order('nombre_comercial') \
            .execute()
        
        # Agrupar por categoría ABC
        por_categoria = {'A': [], 'B': [], 'C': []}
        for med in result.data:
            categoria = med.get('categoria_abc', 'C')
            por_categoria[categoria].append(med)
        
        return {
            "success": True,
            "data": {
                "medicamentos": result.data,
                "total": len(result.data),
                "por_categoria": por_categoria
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo medicamentos esenciales: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analisis/grupos-terapeuticos")
async def obtener_grupos_terapeuticos():
    """
    Obtiene lista de grupos terapéuticos disponibles con conteos
    
    Returns:
        dict: Grupos terapéuticos con número de SKUs
    """
    try:
        result = supabase_client.table('catalogo_medicamentos') \
            .select('grupo_terapeutico') \
            .execute()
        
        # Contar por grupo
        grupos = {}
        for item in result.data:
            grupo = item.get('grupo_terapeutico', 'Sin clasificar')
            grupos[grupo] = grupos.get(grupo, 0) + 1
        
        # Ordenar por cantidad
        grupos_ordenados = sorted(
            [{"grupo": k, "total_skus": v} for k, v in grupos.items()],
            key=lambda x: x['total_skus'],
            reverse=True
        )
        
        return {
            "success": True,
            "data": {
                "grupos_terapeuticos": grupos_ordenados,
                "total_grupos": len(grupos)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo grupos terapéuticos: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas/distribucion")
async def obtener_distribucion_catalogo():
    """
    Obtiene estadísticas de distribución del catálogo
    
    Returns:
        dict: Distribución por categoría ABC, esenciales, con receta
    """
    try:
        # Obtener todo el catálogo
        result = supabase_client.table('catalogo_medicamentos').select('*').execute()
        
        total = len(result.data)
        
        # Distribución por categoría ABC
        por_abc = {'A': 0, 'B': 0, 'C': 0}
        for med in result.data:
            categoria = med.get('categoria_abc', 'C')
            por_abc[categoria] += 1
        
        # Medicamentos esenciales
        esenciales = sum(1 for m in result.data if m.get('es_esencial'))
        
        # Requieren receta
        con_receta = sum(1 for m in result.data if m.get('requiere_receta'))
        
        # Precio promedio
        precios = [m['precio_unitario_lps'] for m in result.data if m.get('precio_unitario_lps')]
        precio_promedio = sum(precios) / len(precios) if precios else 0
        
        return {
            "success": True,
            "data": {
                "total_medicamentos": total,
                "por_categoria_abc": por_abc,
                "esenciales": esenciales,
                "requieren_receta": con_receta,
                "precio_unitario_promedio_lps": round(precio_promedio, 2)
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo distribución del catálogo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))