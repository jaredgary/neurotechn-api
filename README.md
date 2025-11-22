# 🏥 Sistema de Alertas Predictivas - Farmacias Siman

Sistema de información con capacidades predictivas para gestión de inventario farmacéutico usando Machine Learning (XGBoost).

**Proyecto de Tesis GTI - UNITEC Honduras**  
**Autor:** Gary González Zepeda  
**Fecha:** Noviembre 2025

---

## 📊 Descripción del Proyecto

Sistema de alertas predictivas de inventario para la cadena Farmacias Siman, piloto en sucursal Circunvalación, San Pedro Sula. Utiliza algoritmo XGBoost para predecir demanda y generar alertas automáticas de quiebre de stock.

### Métricas del Modelo ML
- **MAE**: 379.69 unidades
- **MAPE**: 3.85%
- **Horizonte óptimo**: 14 días
- **Scoring**: 97/100 puntos

### Cobertura del Piloto
- **SKUs**: 120 medicamentos (MED001-MED120)
- **Período de datos**: 2025-08-02 a 2025-10-30 (90 días)
- **Transacciones**: 10,800 registros
- **Grupos terapéuticos**: 25
- **Viabilidad del sistema**: 89/100 (ALTAMENTE VIABLE)

---

## 🚀 Stack Tecnológico

### Backend
- **Framework**: FastAPI 0.115.0
- **Lenguaje**: Python 3.11
- **Base de datos**: Supabase (PostgreSQL 15)
- **Deployment**: Fly.io (región Miami)

### Dependencias Principales
```
fastapi==0.115.0
uvicorn==0.32.0
supabase==2.9.0
pydantic==2.9.2
```

---

## 📁 Estructura del Proyecto
```
backend/
├── app/
│   ├── main.py              # Aplicación principal
│   ├── config.py            # Configuración
│   ├── database.py          # Conexión Supabase
│   ├── api/v1/              # Endpoints API
│   │   ├── router.py
│   │   ├── dashboard.py
│   │   ├── alertas.py
│   │   ├── inventarios.py
│   │   ├── predicciones.py
│   │   └── medicamentos.py
│   ├── models/              # Modelos Pydantic
│   │   ├── alerta.py
│   │   ├── inventario.py
│   │   ├── prediccion.py
│   │   └── medicamento.py
│   └── services/            # Lógica de negocio
│       ├── alerta_service.py
│       └── prediccion_service.py
├── scripts/
│   └── load_initial_data.py
├── requirements.txt
├── Dockerfile
├── fly.toml
└── README.md
```

---

## 🛠️ Instalación y Configuración

### 1. Clonar el repositorio
```bash
git clone <repository-url>
cd backend
```

### 2. Crear entorno virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```bash
cp .env.example .env
# Editar .env con tus credenciales de Supabase
```

### 5. Ejecutar localmente
```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Acceder a la documentación
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

---

## 🚀 Deployment en Fly.io

### 1. Instalar Fly CLI
```bash
curl -L https://fly.io/install.sh | sh
```

### 2. Login en Fly.io
```bash
fly auth login
```

### 3. Lanzar aplicación (primera vez)
```bash
fly launch --name farmacias-siman-api --region mia
```

### 4. Configurar secrets
```bash
fly secrets set SUPABASE_URL="https://your-project.supabase.co"
fly secrets set SUPABASE_KEY="your-anon-key"
fly secrets set SUPABASE_SERVICE_KEY="your-service-role-key"
```

### 5. Desplegar
```bash
fly deploy
```

### 6. Ver logs
```bash
fly logs
```

### 7. Abrir en navegador
```bash
fly open
```

---

## 📡 Endpoints Principales

### Dashboard
```
GET /api/v1/dashboard/stats
GET /api/v1/dashboard/alertas-recientes
GET /api/v1/dashboard/inventarios-criticos
GET /api/v1/dashboard/tendencias
```

### Alertas
```
GET /api/v1/alertas
GET /api/v1/alertas/{id}
PATCH /api/v1/alertas/{id}/atender
PATCH /api/v1/alertas/{id}/descartar
POST /api/v1/alertas/generar
```

### Inventarios
```
GET /api/v1/inventarios
GET /api/v1/inventarios/{sku}
PATCH /api/v1/inventarios/{sku}
GET /api/v1/inventarios/analisis/proximos-vencer
GET /api/v1/inventarios/analisis/stock-negativo
```

### Predicciones
```
GET /api/v1/predicciones/{sku}
GET /api/v1/predicciones/{sku}/historico
POST /api/v1/predicciones
GET /api/v1/predicciones/metricas/agregadas
```

### Medicamentos
```
GET /api/v1/medicamentos
GET /api/v1/medicamentos/search?q=acetaminofen
GET /api/v1/medicamentos/{sku}
GET /api/v1/medicamentos/categoria/esenciales
```

---

## 🧪 Testing

### Ejecutar tests
```bash
pytest
```

### Test de cobertura
```bash
pytest --cov=app tests/
```

---

## 📊 Base de Datos

### Conexión Supabase
El sistema utiliza Supabase (PostgreSQL 15) con:
- **9 tablas principales**
- **18 índices optimizados**
- **5 funciones PL/pgSQL**
- **3 roles**: admin, farmacia, readonly

### Funciones PostgreSQL Clave
```sql
calcular_stock_proyectado(sku, dias)  -- Calcula stock futuro
generar_alertas_batch()               -- Genera alertas automáticas
calcular_score_urgencia(dias)         -- Calcula urgencia 0-1
obtener_factores_explicativos(sku)   -- Retorna JSON con drivers
```

---

## 🔒 Seguridad

- **RLS (Row Level Security)** habilitado en todas las tablas
- **3 roles**: admin, farmacia, readonly
- **CORS** configurado para orígenes permitidos
- **Secrets** manejados con Fly.io secrets
- **Variables sensibles** nunca en código

---

## 📝 Logs

Los logs se generan en formato estructurado:
```
2025-11-22 10:30:15 - INFO - → GET /api/v1/dashboard/stats
2025-11-22 10:30:15 - INFO - ← GET /api/v1/dashboard/stats status=200 time=0.123s
```

Ver logs en producción:
```bash
fly logs --app farmacias-siman-api
```

---

## 🐛 Troubleshooting

### Error: "Connection refused" a Supabase
- Verificar que `SUPABASE_URL` y `SUPABASE_KEY` estén correctos
- Verificar conectividad de red

### Error: "RLS policy violation"
- Usar `SUPABASE_SERVICE_KEY` para operaciones admin
- Verificar que las políticas RLS estén correctamente configuradas

### Error: "Memory limit exceeded" en Fly.io
```bash
fly scale memory 512  # Aumentar a 512MB
```

---

## 📚 Referencias

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Supabase Python Client](https://supabase.com/docs/reference/python)
- [Fly.io Documentation](https://fly.io/docs)

---

## 👨‍💻 Autor

**Gary González Zepeda**  
Maestría en Gestión de Tecnologías de la Información (GTI)  
UNITEC Honduras

---

## 📄 Licencia

Este proyecto es parte de una tesis académica de UNITEC Honduras.

---

**Última actualización**: 2025-11-22