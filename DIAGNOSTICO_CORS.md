# 🔴 Diagnóstico: Error de Configuración CORS

**Fecha:** 2025-12-04
**Sistema:** Sistema Predictivo de Inventario Farmacéutico v2.0.0
**Estado:** ✅ Código correcto - ❌ Requiere despliegue

---

## 📊 Resultados de Pruebas Unitarias

```
🧪 SUITE DE PRUEBAS UNITARIAS - CONFIGURACIÓN CORS
============================================================
✅ PASSED - Test 1 - CORS_ORIGINS (4/4 URLs configuradas)
✅ PASSED - Test 2 - Middleware CORS (7/7 checks)
✅ PASSED - Test 3 - Métodos y Headers (6/6 + 3/3)
✅ PASSED - Test 4 - Producción (4/4 archivos)
============================================================
Total: 4/4 tests pasados (100%)
```

---

## 🎯 Diagnóstico del Problema

### ✅ Lo que está CORRECTO (Código Local):

1. **CORS_ORIGINS está correctamente configurado** en `app/config.py`:
   ```python
   CORS_ORIGINS: List[str] = [
       "http://localhost:3000",
       "http://localhost:5173",
       "http://localhost:8000",
       "https://farmacias-siman-frontend.fly.dev",  ✅
       "https://farmacias-siman-api.fly.dev",
       "https://farmacias-siman.fly.dev"
   ]
   ```

2. **Middleware CORS correctamente configurado** en `app/main.py:134-142`:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=settings.CORS_ORIGINS,
       allow_credentials=True,
       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
       allow_headers=["*"],
       expose_headers=["*"],
       max_age=3600
   )
   ```

3. **Todos los métodos HTTP** están permitidos: GET, POST, PUT, DELETE, OPTIONS, PATCH
4. **Headers configurados** correctamente: `allow_headers=["*"]`, `expose_headers=["*"]`
5. **Archivos de producción** listos: fly.toml, Dockerfile, requirements.txt

---

## ❌ El Problema Real

```
┌─────────────────────────────────────────────────────────────┐
│                  DESINCRONIZACIÓN DE CÓDIGO                  │
├─────────────────────────────────────────────────────────────┤
│  Código Git (Local)          vs    Fly.io (Producción)     │
├─────────────────────────────────────────────────────────────┤
│  ✅ v2.0.0                          ❌ v1.1.0 (antiguo)     │
│  ✅ CORS completo                   ❌ CORS incompleto      │
│  ✅ 6 dominios configurados         ❌ Dominios antiguos    │
│  ✅ Middleware mejorado             ❌ Middleware básico    │
└─────────────────────────────────────────────────────────────┘
```

### Causa Raíz:

El frontend en **`https://farmacias-siman-frontend.fly.dev`** está intentando conectarse al backend en **`https://farmacias-siman-api.fly.dev`**, pero:

1. El backend en Fly.io **todavía tiene desplegada la versión v1.1.0**
2. La versión v1.1.0 **NO tiene la URL del frontend en CORS_ORIGINS**
3. Por eso el navegador bloquea las peticiones con error CORS

---

## 🚀 Solución: Desplegar v2.0.0 a Fly.io

### Paso 1: Verificar Fly CLI

```bash
fly version
```

Si no está instalado: https://fly.io/docs/hands-on/install-flyctl/

### Paso 2: Autenticarse

```bash
fly auth login
```

### Paso 3: Desplegar el código actualizado

```bash
cd /home/user/neurotechn-api
fly deploy --config fly.toml
```

**Tiempo estimado:** 3-5 minutos

### Paso 4: Verificar el despliegue

```bash
# 1. Ver logs en tiempo real
fly logs

# 2. Verificar versión desplegada
curl https://farmacias-siman-api.fly.dev/ | grep version

# Debería mostrar: "version": "2.0.0"
```

### Paso 5: Verificar CORS desde el navegador

1. Abrir el frontend: `https://farmacias-siman-frontend.fly.dev`
2. Abrir DevTools (F12) → Console
3. Refrescar la página (Ctrl+R)
4. Verificar que NO aparecen errores de CORS

---

## 🧪 Verificación Post-Deploy

### Test 1: Health Check

```bash
curl -X GET https://farmacias-siman-api.fly.dev/health
```

**Respuesta esperada:**
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "version": "2.0.0"
  }
}
```

### Test 2: CORS Preflight (OPTIONS)

```bash
curl -X OPTIONS https://farmacias-siman-api.fly.dev/api/v1/dashboard/stats \
  -H "Origin: https://farmacias-siman-frontend.fly.dev" \
  -H "Access-Control-Request-Method: GET" \
  -v
```

**Headers esperados en la respuesta:**
```
access-control-allow-origin: https://farmacias-siman-frontend.fly.dev
access-control-allow-methods: GET, POST, PUT, DELETE, OPTIONS, PATCH
access-control-allow-credentials: true
access-control-max-age: 3600
```

### Test 3: Endpoint Real (GET)

```bash
curl -X GET https://farmacias-siman-api.fly.dev/api/v1/dashboard/stats \
  -H "Origin: https://farmacias-siman-frontend.fly.dev" \
  -v
```

**Debe retornar datos sin error 500**

---

## 📋 Checklist de Verificación

Después de desplegar, verificar:

- [ ] `fly logs` muestra arranque exitoso
- [ ] `GET /health` retorna `"status": "healthy"`
- [ ] `GET /` retorna `"version": "2.0.0"` (NO 1.1.0)
- [ ] Frontend carga sin errores CORS en consola
- [ ] `GET /api/v1/dashboard/stats` retorna datos (no 500)
- [ ] `GET /api/v1/sistema/metricas-ml` retorna datos o mensaje informativo
- [ ] DevTools → Network → Headers muestran `access-control-allow-origin`

---

## 🔍 Troubleshooting

### Problema: "fly: command not found"

**Solución:** Instalar Fly CLI
```bash
# Linux/macOS
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

### Problema: "Error: not authenticated"

**Solución:** Autenticarse
```bash
fly auth login
```

### Problema: Errores CORS persisten después de deploy

**Solución:** Verificar que la versión correcta está desplegada
```bash
# Debe retornar "2.0.0", NO "1.1.0"
curl https://farmacias-siman-api.fly.dev/ | grep version
```

Si sigue mostrando 1.1.0, forzar rebuild:
```bash
fly deploy --config fly.toml --no-cache
```

### Problema: Frontend muestra URL diferente en error CORS

**Síntoma:** El error de CORS muestra una URL que NO está en la lista

**Solución:** Agregar esa URL a `app/config.py` en `CORS_ORIGINS`:
```python
CORS_ORIGINS: List[str] = [
    # ... URLs existentes ...
    "https://nueva-url-aqui.com"  # Agregar aquí
]
```

Luego hacer commit y redeploy:
```bash
git add app/config.py
git commit -m "fix: Agregar nueva URL a CORS_ORIGINS"
git push
fly deploy
```

---

## 📊 Comparación de Versiones

| Aspecto | v1.1.0 (Producción Actual) | v2.0.0 (Código Local) |
|---------|----------------------------|-----------------------|
| **CORS_ORIGINS** | ❌ Incompleto | ✅ 6 dominios |
| **Middleware** | ❌ Básico | ✅ Mejorado con max_age |
| **Métodos HTTP** | ❌ Solo GET/POST | ✅ GET/POST/PUT/DELETE/OPTIONS/PATCH |
| **expose_headers** | ❌ No configurado | ✅ Configurado |
| **Variables hardcodeadas** | ❌ TOTAL_SKUS, etc. | ✅ Eliminadas |
| **Cálculo dinámico** | ❌ No | ✅ Sí |

---

## ✅ Resumen

### ✅ Código (Git) - 100% Correcto

- [x] CORS_ORIGINS con 6 dominios configurados
- [x] Middleware CORS completo
- [x] Métodos HTTP: GET, POST, PUT, DELETE, OPTIONS, PATCH
- [x] Headers permitidos y expuestos correctamente
- [x] Cache preflight: max_age=3600
- [x] Archivos de producción listos

### ❌ Producción (Fly.io) - Desactualizado

- [ ] Versión v1.1.0 (antigua)
- [ ] CORS incompleto
- [ ] Variables hardcodeadas obsoletas

### 🚀 Acción Requerida

**DESPLEGAR el código v2.0.0 a Fly.io:**

```bash
fly deploy --config fly.toml
```

**Después del deploy, el error de CORS desaparecerá automáticamente.**

---

**Generado por:** Pruebas Unitarias CORS (`test_cors.py`)
**Fecha:** 2025-12-04
**Status:** ✅ Tests: 4/4 Pasados | ❌ Deploy: Pendiente
