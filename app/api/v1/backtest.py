"""
Endpoints para Resultados de Backtesting (OE2)
Acceso a los 360 registros de validación walk-forward (120 SKUs × 3 horizontes)
Algoritmo: XGBoost - MAE promedio: 379.69, MAPE promedio: 3.85%
"""

from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from datetime import datetime
from app.database import supabase_client
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def listar_backtest_results(
    horizonte: Optional[int] = Query(None, description="Filtrar por horizonte (7, 14, 28)"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU"),
    limit: int = Query(100, ge=1, le=360),
    offset: int = Query(0, ge=0)
):
    """
    Lista resultados de backtesting walk-forward
    
    Métricas verificadas (OE2):
    - Total: 360 registros (120 SKUs × 3 horizontes)
    - Algoritmo: XGBoost
    - MAE promedio: 379.69 unidades
    - MAPE promedio: 3.85%
    - Horizonte óptimo: 14 días
    
    Args:
        horizonte: Filtrar por horizonte (7, 14, 28 días)
        sku: Filtrar por SKU específico
        limit: Máximo de resultados
        offset: Offset para paginación
        
    Returns:
        dict: Resultados de backtesting con métricas
    """
    try:
        query = supabase_client.table('backtest_results') \
            .select('*, catalogo_medicamentos(nombre_comercial)')
        
        # Aplicar filtros
        if horizonte:
            if horizonte not in [7, 14, 28]:
                raise HTTPException(
                    status_code=400, 
                    detail="Horizonte debe ser 7, 14 o 28 días"
                )
            query = query.eq('horizon', horizonte)
        
        if sku:
            query = query.eq('sku', sku)
        
        # Ordenar y paginar
        query = query.order('sku').order('horizon').range(offset, offset + limit - 1)
        
        result = query.execute()
        
        # Count total
        count_query = supabase_client.table('backtest_results').select('count', count='exact')
        if horizonte:
            count_query = count_query.eq('horizon', horizonte)
        if sku:
            count_query = count_query.eq('sku', sku)
        count_result = count_query.execute()
        
        return {
            "success": True,
            "data": {
                "resultados": result.data,
                "total": count_result.count,
                "limit": limit,
                "offset": offset,
                "metricas_esperadas": {
                    "total_registros": settings.TOTAL_BACKTEST_RECORDS,
                    "mae_promedio": settings.XGBOOST_MAE_PROMEDIO,
                    "mape_promedio": settings.XGBOOST_MAPE_PROMEDIO,
                    "horizonte_optimo": settings.HORIZONTE_OPTIMO
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listando backtest results: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metricas-agregadas")
async def obtener_metricas_agregadas():
    """
    Obtiene métricas agregadas de backtesting por horizonte
    
    Valores verificados (OE2):
    - 7 días:  MAE=428.37, MAPE=4.40%
    - 14 días: MAE=394.28, MAPE=4.01% (ÓPTIMO)
    - 28 días: MAE=316.41, MAPE=3.14%
    - Promedio: MAE=379.69, MAPE=3.85%
    
    Returns:
        dict: Métricas promedio por horizonte
    """
    try:
        result = supabase_client.table('backtest_results') \
            .select('horizon, mae, mape, bias') \
            .execute()
        
        # Agrupar por horizonte
        por_horizonte = {}
        for r in result.data:
            h = r['horizon']
            if h not in por_horizonte:
                por_horizonte[h] = {'mae': [], 'mape': [], 'bias': [], 'count': 0}
            
            if r.get('mae') is not None:
                por_horizonte[h]['mae'].append(r['mae'])
            if r.get('mape') is not None:
                por_horizonte[h]['mape'].append(r['mape'])
            if r.get('bias') is not None:
                por_horizonte[h]['bias'].append(r['bias'])
            por_horizonte[h]['count'] += 1
        
        # Calcular promedios
        metricas = {}
        for h, valores in por_horizonte.items():
            metricas[f"{h}d"] = {
                "horizonte_dias": h,
                "mae_promedio": round(sum(valores['mae']) / len(valores['mae']), 2) if valores['mae'] else None,
                "mape_promedio": round(sum(valores['mape']) / len(valores['mape']), 2) if valores['mape'] else None,
                "bias_promedio": round(sum(valores['bias']) / len(valores['bias']), 2) if valores['bias'] else None,
                "n_registros": valores['count']
            }
        
        # Calcular promedio global
        all_mae = []
        all_mape = []
        for v in por_horizonte.values():
            all_mae.extend(v['mae'])
            all_mape.extend(v['mape'])
        
        promedio_global = {
            "mae_promedio_global": round(sum(all_mae) / len(all_mae), 2) if all_mae else None,
            "mape_promedio_global": round(sum(all_mape) / len(all_mape), 2) if all_mape else None,
            "total_registros": len(result.data)
        }
        
        return {
            "success": True,
            "data": {
                "por_horizonte": metricas,
                "promedio_global": promedio_global,
                "horizonte_optimo": f"{settings.HORIZONTE_OPTIMO}d",
                "valores_verificados_tesis": {
                    "mae_promedio_oficial": settings.XGBOOST_MAE_PROMEDIO,
                    "mape_promedio_oficial": settings.XGBOOST_MAPE_PROMEDIO,
                    "scoring_xgboost": f"{settings.XGBOOST_SCORING}/100"
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas agregadas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-sku/{sku}")
async def obtener_backtest_por_sku(
    sku: str = Path(..., description="SKU del medicamento")
):
    """
    Obtiene resultados de backtesting para un SKU específico
    
    Args:
        sku: SKU del medicamento
        
    Returns:
        dict: Resultados de los 3 horizontes para el SKU
    """
    try:
        # Validar SKU
        check = supabase_client.table('catalogo_medicamentos') \
            .select('sku, nombre_comercial') \
            .eq('sku', sku) \
            .execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail=f"SKU {sku} no encontrado")
        
        medicamento = check.data[0]
        
        # Obtener resultados para los 3 horizontes
        result = supabase_client.table('backtest_results') \
            .select('*') \
            .eq('sku', sku) \
            .order('horizon') \
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404, 
                detail=f"No hay resultados de backtesting para SKU {sku}"
            )
        
        # Organizar por horizonte
        por_horizonte = {}
        for r in result.data:
            por_horizonte[f"{r['horizon']}d"] = {
                "horizonte_dias": r['horizon'],
                "mae": r.get('mae'),
                "mape": r.get('mape'),
                "bias": r.get('bias'),
                "n_predictions": r.get('n_predictions')
            }
        
        return {
            "success": True,
            "data": {
                "sku": sku,
                "nombre_comercial": medicamento['nombre_comercial'],
                "resultados": por_horizonte,
                "total_horizontes": len(result.data),
                "recomendacion": "Usar horizonte 14d (óptimo según OE2)"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo backtest de {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validacion-coherencia")
async def validar_coherencia_backtest():
    """
    Valida coherencia de datos de backtesting contra valores de tesis
    
    Returns:
        dict: Resultado de validación con discrepancias
    """
    try:
        # Contar registros totales
        total = supabase_client.table('backtest_results') \
            .select('count', count='exact') \
            .execute()
        
        # Contar por horizonte
        horizontes = {}
        for h in [7, 14, 28]:
            count = supabase_client.table('backtest_results') \
                .select('count', count='exact') \
                .eq('horizon', h) \
                .execute()
            horizontes[f"{h}d"] = count.count
        
        # SKUs únicos
        skus = supabase_client.table('backtest_results') \
            .select('sku') \
            .execute()
        skus_unicos = len(set(r['sku'] for r in skus.data))
        
        # Validaciones
        validaciones = {
            "total_registros": {
                "actual": total.count,
                "esperado": settings.TOTAL_BACKTEST_RECORDS,
                "valido": total.count == settings.TOTAL_BACKTEST_RECORDS
            },
            "skus_unicos": {
                "actual": skus_unicos,
                "esperado": settings.TOTAL_SKUS,
                "valido": skus_unicos == settings.TOTAL_SKUS
            },
            "registros_por_horizonte": {
                "actual": horizontes,
                "esperado": {"7d": 120, "14d": 120, "28d": 120},
                "valido": all(h == 120 for h in horizontes.values())
            }
        }
        
        todas_validas = all(v["valido"] for v in validaciones.values())
        
        return {
            "success": True,
            "data": {
                "coherencia_total": todas_validas,
                "validaciones": validaciones,
                "mensaje": "✅ Datos coherentes con tesis" if todas_validas else "⚠️ Discrepancias detectadas"
            }
        }
        
    except Exception as e:
        logger.error(f"Error validando coherencia: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
