"""
Conexión a Base de Datos Supabase
Sistema de Alertas Predictivas - Farmacias Siman

Clientes disponibles:
- supabase_client: Cliente con anon key (respeta RLS)
- supabase_admin: Cliente con service_role (bypasa RLS para ETL/ML)
"""

from supabase import create_client, Client
from app.config import settings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Error de conexión a base de datos"""
    pass


@lru_cache()
def get_supabase_client() -> Client:
    """
    Crea y cachea cliente de Supabase (anon key)
    
    Este cliente respeta las políticas RLS (Row Level Security)
    Usar para operaciones normales de lectura/escritura
    
    Returns:
        Client: Cliente de Supabase con anon key
        
    Raises:
        DatabaseConnectionError: Si no se puede conectar
    """
    try:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise DatabaseConnectionError(
                "SUPABASE_URL y SUPABASE_KEY son obligatorios. "
                "Verificar archivo .env"
            )
        
        supabase = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY
        )
        logger.info("✅ Conexión a Supabase establecida (anon key)")
        return supabase
        
    except Exception as e:
        logger.error(f"❌ Error conectando a Supabase: {str(e)}")
        raise DatabaseConnectionError(f"No se pudo conectar a Supabase: {str(e)}")


@lru_cache()
def get_supabase_admin() -> Client:
    """
    Crea cliente de Supabase con privilegios admin (service_role)
    
    Este cliente BYPASA las políticas RLS
    Usar SOLO para:
    - Operaciones ETL/carga de datos
    - Generación de alertas automáticas
    - Operaciones de mantenimiento
    
    ⚠️ ADVERTENCIA: No exponer este cliente en endpoints públicos
    
    Returns:
        Client: Cliente de Supabase con service_role key
        
    Raises:
        DatabaseConnectionError: Si no se puede conectar
    """
    try:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
            raise DatabaseConnectionError(
                "SUPABASE_URL y SUPABASE_SERVICE_KEY son obligatorios. "
                "Verificar archivo .env"
            )
        
        supabase = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY
        )
        logger.info("✅ Conexión admin a Supabase establecida (service_role)")
        return supabase
        
    except Exception as e:
        logger.error(f"❌ Error conectando a Supabase (admin): {str(e)}")
        raise DatabaseConnectionError(f"No se pudo conectar a Supabase (admin): {str(e)}")


def test_connection() -> dict:
    """
    Prueba la conexión a Supabase
    
    Returns:
        dict: Resultado de la prueba con conteos de tablas principales
    """
    try:
        client = get_supabase_client()
        
        # Probar tablas principales
        tablas = {}
        for tabla in ['catalogo_medicamentos', 'ventas_diarias', 'inventarios_actuales', 'alertas']:
            try:
                result = client.table(tabla).select('count', count='exact').execute()
                tablas[tabla] = result.count
            except Exception as e:
                tablas[tabla] = f"Error: {str(e)}"
        
        return {
            "status": "connected",
            "tablas": tablas,
            "url": settings.SUPABASE_URL[:50] + "..."
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# Instancias globales (lazy initialization)
try:
    supabase_client = get_supabase_client()
except DatabaseConnectionError:
    supabase_client = None
    logger.warning("⚠️ Cliente Supabase no disponible - verificar configuración")

try:
    supabase_admin = get_supabase_admin()
except DatabaseConnectionError:
    supabase_admin = None
    logger.warning("⚠️ Cliente admin Supabase no disponible - verificar configuración")
