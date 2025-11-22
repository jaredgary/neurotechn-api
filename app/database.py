"""
Conexión a base de datos Supabase
"""

from supabase import create_client, Client
from app.config import settings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


@lru_cache()
def get_supabase_client() -> Client:
    """
    Crea y cachea cliente de Supabase
    
    Returns:
        Client: Cliente de Supabase
    """
    try:
        supabase = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY
        )
        logger.info("✓ Conexión a Supabase establecida")
        return supabase
    except Exception as e:
        logger.error(f"✗ Error conectando a Supabase: {str(e)}")
        raise


@lru_cache()
def get_supabase_admin() -> Client:
    """
    Crea cliente de Supabase con privilegios admin (service_role)
    
    Returns:
        Client: Cliente de Supabase con service_role
    """
    try:
        supabase = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY
        )
        logger.info("✓ Conexión admin a Supabase establecida")
        return supabase
    except Exception as e:
        logger.error(f"✗ Error conectando a Supabase (admin): {str(e)}")
        raise


# Instancias globales
supabase_client = get_supabase_client()
supabase_admin = get_supabase_admin()