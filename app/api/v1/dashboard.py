"""
Endpoints para Dashboard principal
Versión: 2.1.0 - Con manejo robusto de errores

CORRECCIÓN: Manejo de tablas faltantes y JOINs que pueden fallar
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, date, timedelta
from app.database import supabase_client
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def safe_count(result) -> int:
    """Obtiene count de forma segura"""
    try:
        return result.count if result.count is not None else 0
    except:
        return 0


def safe_data(result) -> list:
    """Obtiene data de forma segura"""
    try:
        return result.data if result.data else []
    except:
        return []


@router.get("/stats")
async def obtener_estadisticas_dashboard():
    """
    Obtiene estadísticas principales para el dashboard.
    TODAS las métricas se calculan dinámicamente de los datos.
    Maneja graciosamente tablas faltantes.
    """
    try:
        stats = {
            "alertas_pendientes": 0,
            "alertas_criticas": 0,
            "alertas_high": 0,
            "skus_en_riesgo": 0,
            "esenciales_en_riesgo": 0,
            "total_medicamentos": 0,
            "categorias_abc": {"A": 0, "B": 0, "C": 0},
            "total_registros_ventas": 0,
            "periodo": {"inicio": None, "fin": None, "dias": 0}
        }

        # Total medicamentos (tabla principal)
        try:
            total_medicamentos = supabase_client.table('catalogo_medicamentos') \
                .select('count', count='exact') \
                .execute()
            stats["total_medicamentos"] = safe_count(total_medicamentos)
        except Exception as e:
            logger.warning(f"No se pudo obtener catalogo_medicamentos: {e}")

        # Categorías ABC
        try:
            catalogo_abc = supabase_client.table('catalogo_medicamentos') \
                .select('categoria_abc') \
                .execute()
            for med in safe_data(catalogo_abc):
                cat = med.get('categoria_abc')
                if cat in stats["categorias_abc"]:
                    stats["categorias_abc"][cat] += 1
        except Exception as e:
            logger.warning(f"No se pudo obtener categorías ABC: {e}")

        # Total registros de ventas
        try:
            total_ventas = supabase_client.table('ventas_diarias') \
                .select('count', count='exact') \
                .execute()
            stats["total_registros_ventas"] = safe_count(total_ventas)
        except Exception as e:
            logger.warning(f"No se pudo obtener ventas_diarias: {e}")

        # Período de datos
        try:
            ventas_fechas = supabase_client.table('ventas_diarias') \
                .select('fecha') \
                .order('fecha') \
                .limit(1) \
                .execute()
            
            ventas_fechas_fin = supabase_client.table('ventas_diarias') \
                .select('fecha') \
                .order('fecha', desc=True) \
                .limit(1) \
                .execute()

            if safe_data(ventas_fechas) and safe_data(ventas_fechas_fin):
                fecha_inicio = ventas_fechas.data[0]['fecha']
                fecha_fin = ventas_fechas_fin.data[0]['fecha']
                
                # Calcular días
                try:
                    inicio_dt = datetime.fromisoformat(fecha_inicio.replace('Z', '+00:00').split('T')[0])
                    fin_dt = datetime.fromisoformat(fecha_fin.replace('Z', '+00:00').split('T')[0])
                    dias = (fin_dt - inicio_dt).days + 1
                except:
                    dias = 0
                
                stats["periodo"] = {
                    "inicio": fecha_inicio[:10] if fecha_inicio else None,
                    "fin": fecha_fin[:10] if fecha_fin else None,
                    "dias": dias
                }
        except Exception as e:
            logger.warning(f"No se pudo obtener período: {e}")

        # Alertas (tabla opcional - puede no existir)
        try:
            alertas = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('estado', 'pendiente') \
                .execute()
            stats["alertas_pendientes"] = safe_count(alertas)

            alertas_criticas = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('estado', 'pendiente') \
                .eq('nivel_riesgo', 'CRITICAL') \
                .execute()
            stats["alertas_criticas"] = safe_count(alertas_criticas)

            alertas_high = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('estado', 'pendiente') \
                .eq('nivel_riesgo', 'HIGH') \
                .execute()
            stats["alertas_high"] = safe_count(alertas_high)
        except Exception as e:
            logger.warning(f"Tabla 'alertas' no disponible: {e}")

        # Inventarios (tabla opcional)
        try:
            inventarios_riesgo = supabase_client.table('inventarios_actuales') \
                .select('count', count='exact') \
                .lt('stock_proyectado_14d', 0) \
                .execute()
            stats["skus_en_riesgo"] = safe_count(inventarios_riesgo)
        except Exception as e:
            logger.warning(f"Tabla 'inventarios_actuales' no disponible: {e}")

        return {
            "success": True,
            "data": {
                **stats,
                "fecha_actualizacion": datetime.now().isoformat()
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente. Algunas tablas pueden no estar disponibles."
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alertas-recientes")
async def obtener_alertas_recientes(
    limit: int = Query(5, ge=1, le=50, description="Número de alertas a mostrar")
):
    """
    Obtiene las alertas más recientes.
    Maneja graciosamente si la tabla no existe.
    """
    try:
        # Primero verificar si la tabla existe consultando sin JOINs
        try:
            # Consulta simple sin JOINs
            alertas = supabase_client.table('alertas') \
                .select('*') \
                .eq('estado', 'pendiente') \
                .order('score_urgencia', desc=True) \
                .limit(limit) \
                .execute()
            
            alertas_data = safe_data(alertas)
            
            # Si hay alertas, enriquecer con datos del catálogo
            if alertas_data:
                # Obtener SKUs únicos
                skus = list(set(a.get('sku') for a in alertas_data if a.get('sku')))
                
                if skus:
                    # Obtener info de medicamentos
                    try:
                        medicamentos = supabase_client.table('catalogo_medicamentos') \
                            .select('sku, nombre_comercial, grupo_terapeutico, categoria_abc, es_esencial') \
                            .in_('sku', skus) \
                            .execute()
                        
                        med_dict = {m['sku']: m for m in safe_data(medicamentos)}
                        
                        # Enriquecer alertas
                        for alerta in alertas_data:
                            sku = alerta.get('sku')
                            if sku and sku in med_dict:
                                alerta['medicamento'] = med_dict[sku]
                    except Exception as e:
                        logger.warning(f"No se pudo enriquecer con catálogo: {e}")
            
            return {
                "success": True,
                "data": {
                    "alertas": alertas_data,
                    "total": len(alertas_data)
                }
            }
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Si la tabla no existe, devolver vacío en lugar de error
            if 'does not exist' in error_msg or 'relation' in error_msg or '42P01' in error_msg:
                logger.info("Tabla 'alertas' no existe. Devolviendo lista vacía.")
                return {
                    "success": True,
                    "data": {
                        "alertas": [],
                        "total": 0,
                        "mensaje": "No hay alertas configuradas. Ejecute el sistema de alertas primero."
                    }
                }
            
            # Otro error - re-lanzar
            raise e
        
    except Exception as e:
        logger.error(f"Error obteniendo alertas recientes: {str(e)}")
        
        # Devolver respuesta vacía en lugar de error 500
        return {
            "success": True,
            "data": {
                "alertas": [],
                "total": 0,
                "error_detalle": str(e),
                "mensaje": "No se pudieron cargar las alertas. Verifique la configuración de la base de datos."
            }
        }


@router.get("/inventarios-criticos")
async def obtener_inventarios_criticos(
    limit: int = Query(10, ge=1, le=50, description="Número de registros")
):
    """
    Obtiene inventarios con stock proyectado más bajo.
    Maneja graciosamente si la tabla no existe.
    """
    try:
        try:
            inventarios = supabase_client.table('inventarios_actuales') \
                .select('*') \
                .lt('stock_proyectado_14d', 0) \
                .order('stock_proyectado_14d') \
                .limit(limit) \
                .execute()
            
            inventarios_data = safe_data(inventarios)
            
            # Enriquecer con datos del catálogo
            if inventarios_data:
                skus = list(set(i.get('sku') for i in inventarios_data if i.get('sku')))
                
                if skus:
                    try:
                        medicamentos = supabase_client.table('catalogo_medicamentos') \
                            .select('sku, nombre_comercial, stock_seguridad, es_esencial, categoria_abc') \
                            .in_('sku', skus) \
                            .execute()
                        
                        med_dict = {m['sku']: m for m in safe_data(medicamentos)}
                        
                        for inv in inventarios_data:
                            sku = inv.get('sku')
                            if sku and sku in med_dict:
                                inv['medicamento'] = med_dict[sku]
                    except Exception as e:
                        logger.warning(f"No se pudo enriquecer inventarios: {e}")
            
            return {
                "success": True,
                "data": {
                    "inventarios": inventarios_data,
                    "total": len(inventarios_data)
                }
            }
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if 'does not exist' in error_msg or 'relation' in error_msg:
                return {
                    "success": True,
                    "data": {
                        "inventarios": [],
                        "total": 0,
                        "mensaje": "Tabla de inventarios no configurada."
                    }
                }
            raise e
        
    except Exception as e:
        logger.error(f"Error obteniendo inventarios críticos: {str(e)}")
        return {
            "success": True,
            "data": {
                "inventarios": [],
                "total": 0,
                "mensaje": "No se pudieron cargar los inventarios."
            }
        }


@router.get("/tendencias")
async def obtener_tendencias(
    dias: int = Query(30, ge=7, le=90, description="Días de histórico")
):
    """
    Obtiene tendencias de alertas en los últimos N días.
    Maneja graciosamente si la tabla no existe.
    """
    try:
        fecha_inicio = (date.today() - timedelta(days=dias)).isoformat()
        
        try:
            alertas = supabase_client.table('alertas') \
                .select('fecha_generacion, nivel_riesgo, estado') \
                .gte('fecha_generacion', fecha_inicio) \
                .execute()
            
            alertas_data = safe_data(alertas)
            
            # Agrupar por fecha y nivel de riesgo
            por_fecha = {}
            for alerta in alertas_data:
                fecha = alerta.get('fecha_generacion', '')[:10]
                if not fecha:
                    continue
                    
                if fecha not in por_fecha:
                    por_fecha[fecha] = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'total': 0}
                
                nivel = alerta.get('nivel_riesgo', 'MEDIUM')
                if nivel in por_fecha[fecha]:
                    por_fecha[fecha][nivel] += 1
                por_fecha[fecha]['total'] += 1
            
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
            
            # Distribución actual
            distribucion_actual = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0}
            
            try:
                alertas_actuales = supabase_client.table('alertas') \
                    .select('nivel_riesgo') \
                    .eq('estado', 'pendiente') \
                    .execute()
                
                for alerta in safe_data(alertas_actuales):
                    nivel = alerta.get('nivel_riesgo', 'MEDIUM')
                    if nivel in distribucion_actual:
                        distribucion_actual[nivel] += 1
            except:
                pass
            
            return {
                "success": True,
                "data": {
                    "tendencias_diarias": tendencias,
                    "distribucion_actual": distribucion_actual,
                    "periodo_dias": dias
                }
            }
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if 'does not exist' in error_msg or 'relation' in error_msg:
                return {
                    "success": True,
                    "data": {
                        "tendencias_diarias": [],
                        "distribucion_actual": {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0},
                        "periodo_dias": dias,
                        "mensaje": "No hay datos de tendencias disponibles."
                    }
                }
            raise e
        
    except Exception as e:
        logger.error(f"Error obteniendo tendencias: {str(e)}")
        return {
            "success": True,
            "data": {
                "tendencias_diarias": [],
                "distribucion_actual": {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0},
                "periodo_dias": dias
            }
        }


@router.get("/resumen-general")
async def obtener_resumen_general():
    """
    Obtiene resumen completo del sistema para el dashboard.
    Combina múltiples métricas en una sola respuesta.
    """
    try:
        # Estadísticas
        stats = await obtener_estadisticas_dashboard()
        
        # Alertas recientes (top 5)
        alertas_recientes = await obtener_alertas_recientes(limit=5)
        
        # Inventarios críticos (top 5)
        inventarios_criticos = await obtener_inventarios_criticos(limit=5)
        
        # Alertas atendidas hoy
        atendidas_hoy = 0
        try:
            hoy = date.today().isoformat()
            result = supabase_client.table('alertas') \
                .select('count', count='exact') \
                .eq('estado', 'atendida') \
                .gte('fecha_atencion', hoy) \
                .execute()
            atendidas_hoy = safe_count(result)
        except:
            pass
        
        return {
            "success": True,
            "data": {
                "estadisticas": stats.get('data', {}),
                "alertas_recientes": alertas_recientes.get('data', {}).get('alertas', []),
                "inventarios_criticos": inventarios_criticos.get('data', {}).get('inventarios', []),
                "alertas_atendidas_hoy": atendidas_hoy,
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo resumen general: {str(e)}")
        return {
            "success": True,
            "data": {
                "estadisticas": {},
                "alertas_recientes": [],
                "inventarios_criticos": [],
                "alertas_atendidas_hoy": 0,
                "timestamp": datetime.now().isoformat(),
                "mensaje": "Algunos datos no están disponibles."
            }
        }


@router.get("/performance-sistema")
async def obtener_performance_sistema():
    """
    Obtiene métricas de performance del sistema ML.
    TODAS las métricas se calculan dinámicamente.
    """
    try:
        metricas_ml = {}
        horizonte_optimo = "14d"
        utilidad = {"total_evaluadas": 0, "accionables": 0, "porcentaje_accionables": 0.0}
        
        # Métricas de backtest
        try:
            backtest = supabase_client.table('backtest_results') \
                .select('mae, mape, horizon') \
                .eq('algorithm', 'XGBoost') \
                .execute()

            if safe_data(backtest):
                metricas_por_horizonte = {}
                for record in backtest.data:
                    horizonte = record.get('horizon')
                    if horizonte is None:
                        continue
                        
                    if horizonte not in metricas_por_horizonte:
                        metricas_por_horizonte[horizonte] = {'mae_list': [], 'mape_list': []}

                    mae = record.get('mae')
                    mape = record.get('mape')
                    
                    if mae is not None and mae < 10000:
                        metricas_por_horizonte[horizonte]['mae_list'].append(mae)
                    if mape is not None and mape < 100:
                        metricas_por_horizonte[horizonte]['mape_list'].append(mape)

                for horizonte, valores in metricas_por_horizonte.items():
                    if valores['mae_list']:
                        metricas_ml[f"{horizonte}d"] = {
                            "mae_promedio": round(sum(valores['mae_list']) / len(valores['mae_list']), 2),
                            "mape_promedio": round(sum(valores['mape_list']) / len(valores['mape_list']), 2) if valores['mape_list'] else None
                        }

                if metricas_ml:
                    horizonte_optimo = min(
                        metricas_ml.items(),
                        key=lambda x: x[1]['mae_promedio']
                    )[0]
        except Exception as e:
            logger.warning(f"No se pudieron obtener métricas de backtest: {e}")

        # Utilidad de alertas
        try:
            alertas_eval = supabase_client.table('alert_evaluation_results') \
                .select('is_actionable') \
                .execute()

            if safe_data(alertas_eval):
                total = len(alertas_eval.data)
                accionables = sum(1 for a in alertas_eval.data if a.get('is_actionable'))
                utilidad = {
                    "total_evaluadas": total,
                    "accionables": accionables,
                    "porcentaje_accionables": round((accionables / total) * 100, 1) if total > 0 else 0.0
                }
        except Exception as e:
            logger.warning(f"No se pudo obtener utilidad de alertas: {e}")

        return {
            "success": True,
            "data": {
                "metricas_ml": metricas_ml,
                "horizonte_optimo": horizonte_optimo,
                "utilidad_alertas": utilidad
            },
            "meta": {
                "nota": "Métricas calculadas dinámicamente",
                "timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo performance: {str(e)}")
        return {
            "success": True,
            "data": {
                "metricas_ml": {},
                "horizonte_optimo": "14d",
                "utilidad_alertas": {"total_evaluadas": 0, "accionables": 0, "porcentaje_accionables": 0.0}
            }
        }
