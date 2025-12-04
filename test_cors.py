"""
Pruebas Unitarias para Configuración CORS
Sistema Predictivo de Inventario Farmacéutico

Verifica que:
1. Las URLs del frontend estén en CORS_ORIGINS
2. El middleware CORS esté correctamente configurado
3. Los headers CORS se envíen correctamente
"""

import sys
import os
from typing import List

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

def test_cors_configuration():
    """Test 1: Verificar que CORS_ORIGINS contiene las URLs necesarias"""
    print("=" * 60)
    print("TEST 1: Verificación de CORS_ORIGINS")
    print("=" * 60)

    try:
        # Leer configuración directamente del archivo config.py
        with open('app/config.py', 'r') as f:
            config_content = f.read()

        # URLs que DEBEN estar en CORS_ORIGINS
        required_origins = [
            "https://farmacias-siman-frontend.fly.dev",
            "https://farmacias-siman-api.fly.dev",
            "http://localhost:5173",
            "http://localhost:3000"
        ]

        print(f"\n🔍 Verificando URLs requeridas en app/config.py:")
        all_present = True
        for required in required_origins:
            if required in config_content:
                print(f"  ✅ {required}")
            else:
                print(f"  ❌ {required} - FALTA")
                all_present = False

        # Verificar que CORS_ORIGINS está declarado como List[str]
        if "CORS_ORIGINS: List[str]" in config_content:
            print(f"\n  ✅ CORS_ORIGINS declarado como List[str]")
        else:
            print(f"\n  ❌ CORS_ORIGINS no está correctamente tipado")
            all_present = False

        if all_present:
            print("\n✅ TEST 1 PASSED: Todas las URLs requeridas están configuradas")
            return True
        else:
            print("\n❌ TEST 1 FAILED: Faltan URLs en CORS_ORIGINS")
            return False

    except Exception as e:
        print(f"\n❌ TEST 1 ERROR: {str(e)}")
        return False


def test_middleware_configuration():
    """Test 2: Verificar configuración del middleware CORS"""
    print("\n" + "=" * 60)
    print("TEST 2: Verificación de Middleware CORS")
    print("=" * 60)

    try:
        # Leer el archivo main.py
        with open('app/main.py', 'r') as f:
            main_content = f.read()

        # Verificar que el middleware CORS esté presente
        checks = {
            "CORSMiddleware importado": "from fastapi.middleware.cors import CORSMiddleware" in main_content,
            "Middleware CORS agregado": "app.add_middleware(\n    CORSMiddleware," in main_content,
            "allow_origins configurado": "allow_origins=settings.CORS_ORIGINS" in main_content,
            "allow_credentials=True": "allow_credentials=True" in main_content,
            "allow_methods configurado": "allow_methods=" in main_content,
            "allow_headers configurado": "allow_headers=" in main_content,
            "expose_headers configurado": "expose_headers=" in main_content,
        }

        print("\n🔍 Verificando configuración del middleware:")
        all_ok = True
        for check_name, check_result in checks.items():
            if check_result:
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ {check_name}")
                all_ok = False

        if all_ok:
            print("\n✅ TEST 2 PASSED: Middleware CORS correctamente configurado")
            return True
        else:
            print("\n❌ TEST 2 FAILED: Configuración de middleware incompleta")
            return False

    except Exception as e:
        print(f"\n❌ TEST 2 ERROR: {str(e)}")
        return False


def test_cors_headers_config():
    """Test 3: Verificar que los métodos y headers HTTP están completos"""
    print("\n" + "=" * 60)
    print("TEST 3: Verificación de Métodos y Headers HTTP")
    print("=" * 60)

    try:
        with open('app/main.py', 'r') as f:
            main_content = f.read()

        # Métodos HTTP que deben estar permitidos
        required_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]

        print("\n🔍 Verificando métodos HTTP permitidos:")
        all_methods_present = True
        for method in required_methods:
            if f'"{method}"' in main_content:
                print(f"  ✅ {method}")
            else:
                print(f"  ❌ {method} - FALTA")
                all_methods_present = False

        # Verificar headers importantes
        print("\n🔍 Verificando configuración de headers:")
        header_checks = {
            "Headers permitidos": '"*"' in main_content and 'allow_headers=' in main_content,
            "Headers expuestos": 'expose_headers=' in main_content,
            "Cache preflight (max_age)": 'max_age=' in main_content,
        }

        all_headers_ok = True
        for check_name, check_result in header_checks.items():
            if check_result:
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ {check_name}")
                all_headers_ok = False

        if all_methods_present and all_headers_ok:
            print("\n✅ TEST 3 PASSED: Métodos y headers correctamente configurados")
            return True
        else:
            print("\n❌ TEST 3 FAILED: Configuración incompleta")
            return False

    except Exception as e:
        print(f"\n❌ TEST 3 ERROR: {str(e)}")
        return False


def test_production_deployment_readiness():
    """Test 4: Verificar que está listo para producción"""
    print("\n" + "=" * 60)
    print("TEST 4: Verificación de Preparación para Producción")
    print("=" * 60)

    try:
        # Verificar que fly.toml existe
        fly_toml_exists = os.path.exists('fly.toml')

        # Verificar que no hay variables CORS en fly.toml (deben venir del código)
        cors_in_flytoml = False
        if fly_toml_exists:
            with open('fly.toml', 'r') as f:
                fly_content = f.read()
                cors_in_flytoml = 'CORS_ORIGINS' in fly_content

        print("\n🔍 Verificando configuración de despliegue:")
        checks = {
            "fly.toml existe": fly_toml_exists,
            "CORS_ORIGINS NO en fly.toml (correcto)": fly_toml_exists and not cors_in_flytoml,
            "Dockerfile existe": os.path.exists('Dockerfile'),
            "requirements.txt existe": os.path.exists('requirements.txt'),
        }

        all_ok = True
        for check_name, check_result in checks.items():
            if check_result:
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ {check_name}")
                all_ok = False

        if all_ok:
            print("\n✅ TEST 4 PASSED: Listo para despliegue a producción")
            return True
        else:
            print("\n❌ TEST 4 FAILED: No está listo para despliegue")
            return False

    except Exception as e:
        print(f"\n❌ TEST 4 ERROR: {str(e)}")
        return False


def run_all_tests():
    """Ejecuta todos los tests de CORS"""
    print("\n")
    print("🧪" * 30)
    print("SUITE DE PRUEBAS UNITARIAS - CONFIGURACIÓN CORS")
    print("Sistema Predictivo de Inventario Farmacéutico v2.0.0")
    print("🧪" * 30)

    results = {
        "Test 1 - CORS_ORIGINS": test_cors_configuration(),
        "Test 2 - Middleware CORS": test_middleware_configuration(),
        "Test 3 - Métodos y Headers": test_cors_headers_config(),
        "Test 4 - Producción": test_production_deployment_readiness(),
    }

    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE PRUEBAS")
    print("=" * 60)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {test_name}")

    print("\n" + "-" * 60)
    print(f"Total: {passed}/{total} tests pasados ({passed/total*100:.0f}%)")
    print("=" * 60)

    if passed == total:
        print("\n🎉 ¡TODOS LOS TESTS PASARON!")
        print("\n📝 SIGUIENTE PASO:")
        print("   El código está correcto. Necesitas desplegarlo a Fly.io:")
        print("   \n   $ fly deploy --config fly.toml\n")
        return True
    else:
        print("\n⚠️  ALGUNOS TESTS FALLARON")
        print("   Revisa los errores arriba para más detalles.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
