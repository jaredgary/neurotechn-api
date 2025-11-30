"""
Endpoints para Backtesting ML
Versión 2.0 - SaaS Genérico con Cálculo Dinámico

Permite ejecutar backtesting walk-forward y consultar resultados.
"""

from fastapi import APIRouter, HTTPException, Query, Path, BackgroundTasks
from typing import Optional
from datetime import datetime
from app.database import supabase_client
from app.config import settings
from app.services.ml_training import MLTrainingService, BacktestResultsStorage
import pandas as pd
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ejecutar")
async def ejecutar_backtesting(background_tasks: BackgroundTasks):
    """
    Ejecuta backtesting walk-forward para TODOS los SKUs en el sistema.

    El número de SKUs y registros es variable (calculado dinámicamente).
    Usa XGBoost con los horizontes configurados.

    Returns:
        dict: Status de ejecución
    """
    try:
        logger.info("🚀 Iniciando backtesting ML...")

        # Obtener datos de ventas
        ventas_result = supabase_client.table('ventas_diarias') \
            .select('sku, fecha, demanda') \
            .execute()

        if not ventas_result.data:
            raise HTTPException(
                status_code=400,
                detail="No hay datos de ventas. Cargue datos primero."
            )

        ventas_df = pd.DataFrame(ventas_result.data)

        logger.info(f"   📊 Datos cargados: {len(ventas_df)} registros")
        logger.info(f"   🏷️  SKUs únicos: {ventas_df['sku'].nunique()}")

        # Inicializar servicio ML
        ml_service = MLTrainingService(
            horizons=settings.PREDICTION_HORIZONS,
            initial_train_days=settings.INITIAL_TRAIN_DAYS,
            step_size=settings.STEP_SIZE_DAYS,
            n_estimators=settings.XGBOOST_N_ESTIMATORS,
            max_depth=settings.XGBOOST_MAX_DEPTH,
            learning_rate=settings.XGBOOST_LEARNING_RATE,
            random_state=settings.XGBOOST_RANDOM_STATE
        )

        # Ejecutar backtesting
        results_df = await ml_service.run_backtesting(ventas_df)

        if results_df.empty:
            raise HTTPException(
                status_code=500,
                detail="Backtesting no generó resultados. Verifique los datos."
            )

        # Guardar resultados en Supabase
        await BacktestResultsStorage.save_results(
            supabase_client,
            results_df,
            clear_existing=True
        )

        # Calcular métricas de resumen
        metricas = {
            "total_resultados": len(results_df),
            "skus_evaluados": int(results_df['sku'].nunique()),
            "mae_promedio": round(float(results_df['mae'].mean()), 2),
            "mape_promedio": round(float(results_df['mape'].mean()), 2),
            "horizontes": sorted(results_df['horizon'].unique().tolist())
        }

        logger.info(f"✅ Backtesting completado")
        logger.info(f"   MAE promedio: {metricas['mae_promedio']}")
        logger.info(f"   MAPE promedio: {metricas['mape_promedio']}%")

        return {
            "success": True,
            "message": "Backtesting ejecutado exitosamente",
            "data": metricas,
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "nota": "Métricas calculadas dinámicamente"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error ejecutando backtesting: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def listar_backtest_results(
    horizonte: Optional[int] = Query(None, description="Filtrar por horizonte (7, 14, 28)"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    Lista resultados de backtesting walk-forward.

    El total de registros varía según el número de SKUs en el sistema.

    Args:
        horizonte: Filtrar por horizonte (7, 14, 28 días)
        sku: Filtrar por SKU específico
        limit: Máximo de resultados
        offset: Offset para paginación

    Returns:
        dict: Resultados de backtesting
    """
    try:
        query = supabase_client.table('backtest_results') \
            .select('*, catalogo_medicamentos(nombre_comercial)')

        # Aplicar filtros
        if horizonte:
            if horizonte not in settings.PREDICTION_HORIZONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Horizonte debe ser uno de {settings.PREDICTION_HORIZONS}"
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
                "offset": offset
            },
            "meta": {
                "nota": "Total de registros varía según SKUs en el sistema"
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
    Obtiene métricas agregadas de backtesting por horizonte.

    TODAS las métricas se calculan dinámicamente.

    Returns:
        dict: Métricas promedio por horizonte
    """
    try:
        result = supabase_client.table('backtest_results') \
            .select('horizon, mae, mape, bias') \
            .execute()

        if not result.data:
            return {
                "success": False,
                "error": "No hay resultados de backtesting. Ejecute POST /api/v1/backtest/ejecutar primero.",
                "data": None
            }

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
        for h, valores in sorted(por_horizonte.items()):
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

        # Identificar horizonte óptimo (menor MAE)
        mejor_horizonte = None
        menor_mae = float('inf')
        for h, m in metricas.items():
            if m['mae_promedio'] and m['mae_promedio'] < menor_mae:
                menor_mae = m['mae_promedio']
                mejor_horizonte = h

        return {
            "success": True,
            "data": {
                "por_horizonte": metricas,
                "promedio_global": promedio_global,
                "horizonte_optimo": mejor_horizonte,
                "algoritmo": "XGBoost"
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente",
                "timestamp": datetime.now().isoformat()
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
    Obtiene resultados de backtesting para un SKU específico.

    Args:
        sku: SKU del medicamento

    Returns:
        dict: Resultados de backtesting para el SKU
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

        # Obtener resultados
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

        # Identificar mejor horizonte para este SKU
        mejor_horizonte = min(
            result.data,
            key=lambda x: x.get('mae', float('inf'))
        )['horizon']

        return {
            "success": True,
            "data": {
                "sku": sku,
                "nombre_comercial": medicamento['nombre_comercial'],
                "resultados": por_horizonte,
                "total_horizontes": len(result.data),
                "horizonte_optimo_sku": f"{mejor_horizonte}d"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo backtest de {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
