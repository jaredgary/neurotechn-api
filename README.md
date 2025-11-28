# 🏥 Sistema de Alertas Predictivas - Farmacias Siman

## Backend FastAPI - Versión 1.1.0

API REST para el sistema de información con capacidades predictivas de inventario farmacéutico.

---

## 📊 Métricas del Proyecto (Verificadas)

| Métrica | Valor | Fuente |
|---------|-------|--------|
| **Total SKUs** | 120 (MED001-MED120) | catalogo_medicamentos.csv |
| **Registros ventas** | 10,800 | datos_farmacias_siman.csv |
| **Período** | 2025-08-02 a 2025-10-30 | 90 días |
| **XGBoost MAE** | 379.69 unidades | benchmarking_results.csv |
| **XGBoost MAPE** | 3.85% | benchmarking_results.csv |
| **Alertas accionables** | 71.7% (172/240) | alert_evaluation_results.csv |
| **Viabilidad global** | 89/100 | MARCO_EVALUACIÓN_VIABILIDAD.pdf |

---

## 🚀 Instalación

### Requisitos
- Python 3.11+
- Cuenta Supabase (gratuita)
- (Opcional) Cuenta Fly.io para deployment

### 1. Clonar y configurar
```bash
# Clonar repositorio
git clone <url-repositorio>
cd backend

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar variables de entorno
```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar con tus credenciales de Supabase
nano .env
```

Variables obligatorias:
```env
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu-anon-key
SUPABASE_SERVICE_KEY=tu-service-role-key
```

### 3. Ejecutar en desarrollo
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Acceder a documentación
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 📁 Estructura del Proyecto

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # Aplicación FastAPI
│   ├── config.py            # Configuración con métricas verificadas
│   ├── database.py          # Conexión Supabase
│   ├── api/
│   │   └── v1/
│   │       ├── router.py    # Router principal (45 endpoints)
│   │       ├── dashboard.py # Estadísticas (RF-003)
│   │       ├── alertas.py   # Gestión alertas (RF-001, RF-002, RF-005)
│   │       ├── inventarios.py
│   │       ├── medicamentos.py
│   │       ├── predicciones.py
│   │       ├── ventas.py    # NUEVO: 10,800 registros
│   │       ├── backtest.py  # NUEVO: OE2 - 360 registros
│   │       ├── evaluacion_alertas.py  # NUEVO: OE4 - 240 registros
│   │       └── sistema.py   # NUEVO: Calidad datos y viabilidad
│   ├── models/
│   │   └── __init__.py      # Modelos Pydantic
│   └── services/
│       └── __init__.py      # Lógica de negocio
├── requirements.txt
├── Dockerfile
├── fly.toml                 # Configuración Fly.io
├── .env.example
├── .gitignore
└── README.md
```

---

## 🔌 Endpoints Disponibles (45 total)

### Dashboard (6)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/stats` | Estadísticas principales |
| GET | `/api/v1/dashboard/alertas-recientes` | Top alertas urgentes |
| GET | `/api/v1/dashboard/inventarios-criticos` | SKUs en riesgo |
| GET | `/api/v1/dashboard/tendencias` | Tendencias de alertas |
| GET | `/api/v1/dashboard/resumen-general` | Resumen consolidado |
| GET | `/api/v1/dashboard/performance-sistema` | Métricas ML |

### Alertas (7)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/alertas` | Listar con filtros |
| GET | `/api/v1/alertas/{id}` | Detalle de alerta |
| PATCH | `/api/v1/alertas/{id}/atender` | Marcar como atendida |
| PATCH | `/api/v1/alertas/{id}/descartar` | Descartar alerta |
| POST | `/api/v1/alertas/generar` | Generar automáticas |
| GET | `/api/v1/alertas/estadisticas/distribucion` | Distribución |

### Inventarios (7)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/inventarios` | Listar con filtros |
| GET | `/api/v1/inventarios/{sku}` | Detalle de SKU |
| PATCH | `/api/v1/inventarios/{sku}` | Actualizar stock |
| GET | `/api/v1/inventarios/analisis/proximos-vencer` | Vencimientos |
| GET | `/api/v1/inventarios/analisis/stock-negativo` | En riesgo |
| GET | `/api/v1/inventarios/estadisticas/resumen` | Resumen |

### Medicamentos (7)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/medicamentos` | Catálogo completo |
| GET | `/api/v1/medicamentos/search` | Búsqueda |
| GET | `/api/v1/medicamentos/{sku}` | Detalle |
| GET | `/api/v1/medicamentos/categoria/esenciales` | Esenciales |
| GET | `/api/v1/medicamentos/analisis/grupos-terapeuticos` | Grupos ATC |
| GET | `/api/v1/medicamentos/estadisticas/distribucion` | Distribución ABC |

### Predicciones ML (5)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/predicciones/{sku}` | Última predicción |
| GET | `/api/v1/predicciones/{sku}/historico` | Histórico |
| POST | `/api/v1/predicciones` | Crear predicción |
| GET | `/api/v1/predicciones/metricas/agregadas` | Métricas modelo |
| GET | `/api/v1/predicciones/analisis/comparacion-horizontes` | Comparar |

### Ventas (5) - NUEVO
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/ventas` | Listar ventas |
| GET | `/api/v1/ventas/estadisticas` | Estadísticas generales |
| GET | `/api/v1/ventas/por-sku/{sku}` | Ventas por SKU |
| GET | `/api/v1/ventas/tendencia-demanda` | Tendencia agregada |
| GET | `/api/v1/ventas/top-demanda` | Top SKUs |

### Backtest (4) - NUEVO
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/backtest` | Listar resultados |
| GET | `/api/v1/backtest/metricas-agregadas` | MAE/MAPE por horizonte |
| GET | `/api/v1/backtest/por-sku/{sku}` | Por SKU |
| GET | `/api/v1/backtest/validacion-coherencia` | Validar vs tesis |

### Evaluación Alertas (6) - NUEVO
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/evaluacion-alertas` | Listar evaluaciones |
| GET | `/api/v1/evaluacion-alertas/metricas-consolidadas` | OE4 completo |
| GET | `/api/v1/evaluacion-alertas/por-horizonte` | 7d vs 14d |
| GET | `/api/v1/evaluacion-alertas/distribucion-riesgo` | Por nivel |
| GET | `/api/v1/evaluacion-alertas/por-sku/{sku}` | Por SKU |
| GET | `/api/v1/evaluacion-alertas/validacion-coherencia` | Validar vs tesis |

### Sistema (3) - NUEVO
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/sistema/calidad-datos` | FD-001 a FD-004 |
| GET | `/api/v1/sistema/viabilidad` | 89/100 pts |
| GET | `/api/v1/sistema/metricas-tesis` | Todas las métricas OE1-OE4 |

---

## 🚢 Deployment en Fly.io

### 1. Instalar CLI
```bash
# macOS
brew install flyctl

# Windows
iwr https://fly.io/install.ps1 -useb | iex

# Linux
curl -L https://fly.io/install.sh | sh
```

### 2. Login y crear app
```bash
fly auth login
fly launch --no-deploy
```

### 3. Configurar secrets
```bash
fly secrets set SUPABASE_URL=https://tu-proyecto.supabase.co
fly secrets set SUPABASE_KEY=tu-anon-key
fly secrets set SUPABASE_SERVICE_KEY=tu-service-role-key
```

### 4. Deploy
```bash
fly deploy
```

### 5. Verificar
```bash
fly status
fly logs
```

---

## 🧪 Testing

```bash
# Ejecutar tests
pytest

# Con cobertura
pytest --cov=app
```

---

## 📚 Documentación Adicional

- **Tesis completa**: Ver archivo Tesis.pdf
- **Manual de Fondo UNITEC**: Estructura académica
- **Manual de Forma UNITEC**: Formato APA

---

## 👨‍💻 Autor

**Gary González Zepeda**  
Maestría en Gestión de Tecnologías de la Información (GTI)  
UNITEC Honduras - 2025

---

## 📄 Licencia

Proyecto académico - Uso educativo
