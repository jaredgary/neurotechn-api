-- =========================================================================
-- SISTEMA DE GESTIÓN PREDICTIVA DE INVENTARIO FARMACÉUTICO
-- MVP FARMACIAS SIMAN - SAN PEDRO SULA
-- =========================================================================
-- Versión: 1.0.0
-- Última actualización: 2024
-- Descripción: Schema optimizado para modelo predictivo XGBoost con 
--              horizonte de pronóstico 7/14/28 días
-- =========================================================================

-- =========================================================================
-- SECCIÓN 1: CONFIGURACIÓN INICIAL Y EXTENSIONES
-- =========================================================================

-- Habilitar extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- Para UUIDs
CREATE EXTENSION IF NOT EXISTS "vector";    -- Para embeddings semánticos
CREATE EXTENSION IF NOT EXISTS "pg_cron";   -- Para tareas programadas
CREATE EXTENSION IF NOT EXISTS "pg_net";    -- Para llamadas HTTP
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- Para monitoreo de queries

-- Crear tipos enumerados para alertas
DO $$
BEGIN
    -- Tipo de alerta con categorías expandidas
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_alerta') THEN
        CREATE TYPE tipo_alerta AS ENUM (
            'QUIEBRE_STOCK',      -- Stock crítico o agotado
            'VENCIMIENTO',        -- Medicamento próximo a vencer
            'SOBRESTOCK',         -- Exceso de inventario
            'DEMANDA_ANOMALA',    -- Picos o caídas inusuales
            'REPOSICION_URGENTE'  -- Necesidad inmediata de reorden
        );
    END IF;
    
    -- Severidad de alerta
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'severidad_alerta') THEN
        CREATE TYPE severidad_alerta AS ENUM ('BAJA', 'MEDIA', 'ALTA', 'CRITICA');
    END IF;
    
    -- Estado de procesamiento de alertas
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_alerta') THEN
        CREATE TYPE estado_alerta AS ENUM (
            'PENDIENTE',    -- Alerta nueva sin revisar
            'EN_REVISION',  -- Siendo evaluada
            'RESUELTA',     -- Acción tomada
            'DESCARTADA'    -- Falso positivo o no requiere acción
        );
    END IF;
END$$;

-- =========================================================================
-- SECCIÓN 2: TABLAS PRINCIPALES DEL MODELO
-- =========================================================================

-- Tabla maestra de productos con clasificación ATC
CREATE TABLE IF NOT EXISTS public.sku_atc (
    sku TEXT PRIMARY KEY,
    nombre_producto TEXT NOT NULL,
    atc_code TEXT NOT NULL,
    atc_nivel1 TEXT GENERATED ALWAYS AS (substring(atc_code, 1, 1)) STORED,
    atc_nivel2 TEXT GENERATED ALWAYS AS (substring(atc_code, 1, 3)) STORED,
    atc_nivel3 TEXT GENERATED ALWAYS AS (substring(atc_code, 1, 4)) STORED,
    lead_time_dias INT NOT NULL DEFAULT 7 CHECK (lead_time_dias >= 0),
    punto_reorden INT DEFAULT 0 CHECK (punto_reorden >= 0),
    stock_maximo INT CHECK (stock_maximo > 0),
    costo_unitario NUMERIC(10,2) CHECK (costo_unitario >= 0),
    precio_venta NUMERIC(10,2) CHECK (precio_venta >= 0),
    es_esencial BOOLEAN DEFAULT FALSE,  -- Medicamento esencial según OMS
    proveedor_principal TEXT,
    embedding VECTOR(384),  -- Para búsqueda semántica
    fecha_alta DATE DEFAULT CURRENT_DATE,
    activo BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb  -- Información adicional flexible
);

-- Comentarios de columnas para documentación
COMMENT ON COLUMN public.sku_atc.es_esencial IS 'Indica si el medicamento está en la lista de medicamentos esenciales de la OMS';
COMMENT ON COLUMN public.sku_atc.embedding IS 'Vector de embedding para búsqueda semántica de productos similares';
COMMENT ON COLUMN public.sku_atc.metadata IS 'Información adicional como contraindicaciones, presentación, etc.';

-- Tabla de ventas diarias con información enriquecida
CREATE TABLE IF NOT EXISTS public.ventas_diarias (
    fecha DATE NOT NULL,
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    unidades_vendidas INT NOT NULL DEFAULT 0 CHECK (unidades_vendidas >= 0),
    monto_total NUMERIC(12,2) DEFAULT 0 CHECK (monto_total >= 0),
    promo_flag BOOLEAN DEFAULT FALSE,
    descuento_aplicado NUMERIC(5,2) DEFAULT 0 CHECK (descuento_aplicado >= 0 AND descuento_aplicado <= 100),
    canal TEXT DEFAULT 'TIENDA',  -- TIENDA, ONLINE, TELEFONO
    hora_pico INT CHECK (hora_pico >= 0 AND hora_pico <= 23),  -- Hora con más ventas
    temperatura_dia NUMERIC(4,1),  -- Factor externo: temperatura
    es_feriado BOOLEAN DEFAULT FALSE,
    CONSTRAINT ventas_diarias_pkey PRIMARY KEY (fecha, sku),
    CONSTRAINT ventas_fecha_valida CHECK (fecha <= CURRENT_DATE)
);

-- Tabla de inventario diario con métricas adicionales
CREATE TABLE IF NOT EXISTS public.inventario_diario (
    fecha DATE NOT NULL,
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    unidades_stock INT NOT NULL DEFAULT 0 CHECK (unidades_stock >= 0),
    stock_seguridad INT NOT NULL DEFAULT 0 CHECK (stock_seguridad >= 0),
    stock_transito INT DEFAULT 0 CHECK (stock_transito >= 0),  -- Pedidos en camino
    dias_cobertura NUMERIC(5,2) GENERATED ALWAYS AS (
        CASE 
            WHEN unidades_stock > 0 THEN unidades_stock::NUMERIC / NULLIF(stock_seguridad::NUMERIC, 0) * 7
            ELSE 0 
        END
    ) STORED,
    ubicacion_almacen TEXT DEFAULT 'PRINCIPAL',
    CONSTRAINT inventario_diario_pkey PRIMARY KEY (fecha, sku),
    CONSTRAINT inventario_fecha_valida CHECK (fecha <= CURRENT_DATE + INTERVAL '1 day')
);

-- Tabla de lotes con trazabilidad completa
CREATE TABLE IF NOT EXISTS public.lotes_caducidad (
    lote_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    unidades INT NOT NULL CHECK (unidades >= 0),
    unidades_iniciales INT NOT NULL CHECK (unidades_iniciales >= 0),
    fecha_caducidad DATE NOT NULL,
    fecha_recepcion DATE NOT NULL DEFAULT CURRENT_DATE,
    numero_factura TEXT,
    proveedor TEXT,
    costo_lote NUMERIC(12,2) CHECK (costo_lote >= 0),
    dias_hasta_vencimiento INT GENERATED ALWAYS AS (
        (fecha_caducidad - CURRENT_DATE)::INT
    ) STORED,
    CONSTRAINT lote_caducidad_valida CHECK (fecha_caducidad > fecha_recepcion)
);

-- =========================================================================
-- SECCIÓN 3: TABLAS DEL MODELO PREDICTIVO
-- =========================================================================

-- Registro de ejecuciones del modelo con métricas detalladas
CREATE TABLE IF NOT EXISTS public.ejecuciones_modelo (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    modelo TEXT NOT NULL DEFAULT 'xgboost',
    version TEXT NOT NULL DEFAULT '1.0.0',
    horizonte_dias INT NOT NULL CHECK (horizonte_dias IN (7, 14, 28)),
    ventana_entrenamiento_dias INT NOT NULL DEFAULT 90 CHECK (ventana_entrenamiento_dias >= 30),
    ts_inicio TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_fin TIMESTAMPTZ,
    duracion_segundos INT GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (ts_fin - ts_inicio))::INT
    ) STORED,
    skus_procesados INT DEFAULT 0,
    exito BOOLEAN DEFAULT FALSE,
    parametros JSONB NOT NULL DEFAULT '{}'::jsonb,
    metricas_globales JSONB DEFAULT '{}'::jsonb,
    mensaje_error TEXT,
    notas TEXT
);

-- Métricas de backtesting por SKU
CREATE TABLE IF NOT EXISTS public.metricas_backtesting (
    run_id UUID NOT NULL REFERENCES public.ejecuciones_modelo(run_id) ON DELETE CASCADE,
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    mape NUMERIC(8,4) CHECK (mape >= 0),  -- Mean Absolute Percentage Error
    mae NUMERIC(10,2) CHECK (mae >= 0),   -- Mean Absolute Error
    rmse NUMERIC(10,2) CHECK (rmse >= 0), -- Root Mean Square Error
    smape NUMERIC(8,4) CHECK (smape >= 0 AND smape <= 200), -- Symmetric MAPE
    sesgo NUMERIC(8,4),  -- Bias (puede ser negativo)
    r2_score NUMERIC(6,4) CHECK (r2_score <= 1),  -- R-squared
    coverage_probability NUMERIC(5,2) CHECK (coverage_probability >= 0 AND coverage_probability <= 100),
    n_observaciones INT CHECK (n_observaciones > 0),
    CONSTRAINT metricas_backtesting_pkey PRIMARY KEY (run_id, sku)
);

-- Pronósticos históricos con intervalos de confianza
CREATE TABLE IF NOT EXISTS public.forecast_historico (
    run_id UUID NOT NULL REFERENCES public.ejecuciones_modelo(run_id) ON DELETE CASCADE,
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    fecha_objetivo DATE NOT NULL,
    unidades_pronosticadas NUMERIC(10,2) NOT NULL CHECK (unidades_pronosticadas >= 0),
    limite_inferior NUMERIC(10,2) DEFAULT 0 CHECK (limite_inferior >= 0),
    limite_superior NUMERIC(10,2) CHECK (limite_superior >= limite_inferior),
    probabilidad_quiebre NUMERIC(5,2) CHECK (probabilidad_quiebre >= 0 AND probabilidad_quiebre <= 100),
    features_importancia JSONB,  -- Importancia de características para este pronóstico
    CONSTRAINT forecast_historico_pkey PRIMARY KEY (run_id, sku, fecha_objetivo),
    CONSTRAINT forecast_fecha_futura CHECK (fecha_objetivo >= CURRENT_DATE)
);

-- =========================================================================
-- SECCIÓN 4: SISTEMA DE ALERTAS MEJORADO
-- =========================================================================

-- Tabla de alertas con trazabilidad completa
CREATE TABLE IF NOT EXISTS public.alertas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts_creacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_actualizacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sku TEXT NOT NULL REFERENCES public.sku_atc(sku) ON DELETE RESTRICT,
    tipo_alerta tipo_alerta NOT NULL,
    severidad severidad_alerta NOT NULL,
    estado estado_alerta NOT NULL DEFAULT 'PENDIENTE',
    fecha_objetivo DATE,
    lote_id TEXT REFERENCES public.lotes_caducidad(lote_id) ON DELETE SET NULL,
    valor_metrica NUMERIC(12,2),  -- Valor que disparó la alerta
    umbral_metrica NUMERIC(12,2),  -- Umbral configurado
    descripcion TEXT NOT NULL,
    accion_sugerida TEXT,
    impacto_estimado NUMERIC(12,2),  -- Impacto económico estimado
    -- Campos de resolución
    resuelta BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    resolucion_comentario TEXT,
    tiempo_resolucion_horas INT GENERATED ALWAYS AS (
        CASE 
            WHEN acknowledged_at IS NOT NULL 
            THEN EXTRACT(EPOCH FROM (acknowledged_at - ts_creacion))/3600
            ELSE NULL 
        END::INT
    ) STORED,
    -- Metadata adicional
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Tabla de configuración de umbrales para alertas
CREATE TABLE IF NOT EXISTS public.config_alertas (
    id SERIAL PRIMARY KEY,
    tipo_alerta tipo_alerta NOT NULL,
    atc_nivel2 TEXT,  -- Aplicar a familia específica o NULL para todos
    umbral_critico NUMERIC(10,2) NOT NULL,
    umbral_alto NUMERIC(10,2) NOT NULL,
    umbral_medio NUMERIC(10,2) NOT NULL,
    umbral_bajo NUMERIC(10,2) NOT NULL,
    activo BOOLEAN DEFAULT TRUE,
    descripcion TEXT,
    UNIQUE(tipo_alerta, atc_nivel2)
);

-- =========================================================================
-- SECCIÓN 5: TABLAS DE AUDITORÍA Y LOGS
-- =========================================================================

-- Log de cambios en inventario para auditoría
CREATE TABLE IF NOT EXISTS public.audit_inventario (
    id BIGSERIAL PRIMARY KEY,
    ts_cambio TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sku TEXT NOT NULL,
    tipo_movimiento TEXT NOT NULL, -- ENTRADA, SALIDA, AJUSTE, TRANSFERENCIA
    cantidad INT NOT NULL,
    stock_anterior INT,
    stock_posterior INT,
    motivo TEXT,
    usuario_id UUID,
    referencia_documento TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- =========================================================================
-- SECCIÓN 6: ÍNDICES OPTIMIZADOS PARA PERFORMANCE
-- =========================================================================

-- Índices principales para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_sku_atc_activo_esencial 
    ON public.sku_atc(activo, es_esencial) WHERE activo = TRUE;

CREATE INDEX IF NOT EXISTS idx_sku_atc_atc_niveles 
    ON public.sku_atc(atc_nivel1, atc_nivel2, atc_nivel3);

-- Índices para ventas
CREATE INDEX IF NOT EXISTS idx_ventas_sku_fecha 
    ON public.ventas_diarias(sku, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_ventas_fecha_rango 
    ON public.ventas_diarias(fecha) 
    WHERE fecha >= CURRENT_DATE - INTERVAL '90 days';

CREATE INDEX IF NOT EXISTS idx_ventas_promo 
    ON public.ventas_diarias(promo_flag, fecha) 
    WHERE promo_flag = TRUE;

-- Índices para inventario
CREATE INDEX IF NOT EXISTS idx_inventario_sku_fecha 
    ON public.inventario_diario(sku, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_inventario_stock_critico 
    ON public.inventario_diario(sku, fecha, unidades_stock) 
    WHERE unidades_stock < stock_seguridad;

-- Índices para lotes
CREATE INDEX IF NOT EXISTS idx_lotes_sku_caduca 
    ON public.lotes_caducidad(sku, fecha_caducidad);

CREATE INDEX IF NOT EXISTS idx_lotes_proximos_vencer 
    ON public.lotes_caducidad(fecha_caducidad, sku) 
    WHERE fecha_caducidad <= CURRENT_DATE + INTERVAL '30 days';

-- Índices para pronósticos
CREATE INDEX IF NOT EXISTS idx_forecast_lookup 
    ON public.forecast_historico(sku, fecha_objetivo);

CREATE INDEX IF NOT EXISTS idx_forecast_run_sku_fecha 
    ON public.forecast_historico(run_id, sku, fecha_objetivo);

CREATE INDEX IF NOT EXISTS idx_forecast_quiebre_alto 
    ON public.forecast_historico(sku, fecha_objetivo, probabilidad_quiebre) 
    WHERE probabilidad_quiebre > 70;

-- Índices para alertas
CREATE INDEX IF NOT EXISTS idx_alerta_estado 
    ON public.alertas(estado, tipo_alerta, severidad, ts_creacion DESC);

CREATE INDEX IF NOT EXISTS idx_alerta_pendientes 
    ON public.alertas(sku, tipo_alerta, estado) 
    WHERE estado IN ('PENDIENTE', 'EN_REVISION');

CREATE INDEX IF NOT EXISTS idx_alerta_severidad_alta 
    ON public.alertas(severidad, estado, ts_creacion DESC) 
    WHERE severidad IN ('ALTA', 'CRITICA');

-- Índice para búsqueda semántica (usando IVFFlat para mejor performance)
CREATE INDEX IF NOT EXISTS idx_sku_atc_embedding 
    ON public.sku_atc 
    USING ivfflat (embedding vector_cosine_ops) 
    WITH (lists = 100);

-- Índices para auditoría
CREATE INDEX IF NOT EXISTS idx_audit_inventario_sku_fecha 
    ON public.audit_inventario(sku, ts_cambio DESC);

-- =========================================================================
-- SECCIÓN 7: VISTAS INTELIGENTES PARA DASHBOARDS
-- =========================================================================

-- Vista del último run válido con pronósticos
CREATE OR REPLACE VIEW public.v_latest_run AS
SELECT 
    e.run_id,
    e.modelo,
    e.version,
    e.horizonte_dias,
    e.ts_inicio,
    e.ts_fin,
    e.skus_procesados,
    e.exito
FROM public.ejecuciones_modelo e
WHERE e.exito = TRUE
    AND EXISTS (
        SELECT 1 
        FROM public.forecast_historico f 
        WHERE f.run_id = e.run_id
    )
ORDER BY e.ts_inicio DESC
LIMIT 1;

-- Vista de pronósticos más recientes
CREATE OR REPLACE VIEW public.v_forecast_latest AS
SELECT 
    f.*,
    s.nombre_producto,
    s.atc_code,
    s.es_esencial
FROM public.forecast_historico f
JOIN public.v_latest_run lr ON lr.run_id = f.run_id
JOIN public.sku_atc s ON s.sku = f.sku
WHERE s.activo = TRUE;

-- Vista de demanda futura agregada por horizontes (7, 14, 28 días)
CREATE OR REPLACE VIEW public.v_demanda_futura_7_14_28 AS
WITH forecast_data AS (
    SELECT 
        sku, 
        fecha_objetivo, 
        unidades_pronosticadas,
        probabilidad_quiebre
    FROM public.v_forecast_latest
    WHERE fecha_objetivo BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '28 days'
)
SELECT
    f.sku,
    s.nombre_producto,
    s.atc_code,
    s.es_esencial,
    COALESCE(SUM(CASE 
        WHEN f.fecha_objetivo <= CURRENT_DATE + INTERVAL '7 days' 
        THEN f.unidades_pronosticadas 
        ELSE 0 
    END), 0) AS demanda_7d,
    COALESCE(SUM(CASE 
        WHEN f.fecha_objetivo <= CURRENT_DATE + INTERVAL '14 days' 
        THEN f.unidades_pronosticadas 
        ELSE 0 
    END), 0) AS demanda_14d,
    COALESCE(SUM(f.unidades_pronosticadas), 0) AS demanda_28d,
    MAX(f.probabilidad_quiebre) AS max_prob_quiebre_28d
FROM forecast_data f
JOIN public.sku_atc s ON s.sku = f.sku
WHERE s.activo = TRUE
GROUP BY f.sku, s.nombre_producto, s.atc_code, s.es_esencial;

-- Vista de productos próximos a vencer
CREATE OR REPLACE VIEW public.v_caducidades_proximas AS
SELECT
    l.sku,
    s.nombre_producto,
    s.es_esencial,
    l.lote_id,
    l.fecha_caducidad,
    l.dias_hasta_vencimiento,
    l.unidades,
    l.unidades * s.costo_unitario AS valor_en_riesgo,
    CASE
        WHEN l.dias_hasta_vencimiento <= 7 THEN 'CRITICO'
        WHEN l.dias_hasta_vencimiento <= 30 THEN 'ALTO'
        WHEN l.dias_hasta_vencimiento <= 60 THEN 'MEDIO'
        ELSE 'BAJO'
    END AS nivel_urgencia,
    SUM(l.unidades) OVER (PARTITION BY l.sku) AS total_unidades_por_vencer
FROM public.lotes_caducidad l
JOIN public.sku_atc s ON s.sku = l.sku
WHERE l.fecha_caducidad <= CURRENT_DATE + INTERVAL '90 days'
    AND l.unidades > 0
    AND s.activo = TRUE
ORDER BY l.dias_hasta_vencimiento, s.es_esencial DESC;

-- Vista de estado actual del inventario con métricas
CREATE OR REPLACE VIEW public.v_estado_inventario AS
WITH ultimo_inventario AS (
    SELECT DISTINCT ON (sku) 
        sku,
        fecha,
        unidades_stock,
        stock_seguridad,
        stock_transito,
        dias_cobertura
    FROM public.inventario_diario
    WHERE fecha >= CURRENT_DATE - INTERVAL '7 days'
    ORDER BY sku, fecha DESC
),
ventas_recientes AS (
    SELECT 
        sku,
        AVG(unidades_vendidas) AS venta_promedio_diaria,
        STDDEV(unidades_vendidas) AS desviacion_ventas,
        MAX(unidades_vendidas) AS venta_maxima,
        SUM(unidades_vendidas) AS total_vendido_30d
    FROM public.ventas_diarias
    WHERE fecha >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY sku
)
SELECT
    i.sku,
    s.nombre_producto,
    s.atc_code,
    s.es_esencial,
    i.fecha AS fecha_ultimo_inventario,
    i.unidades_stock,
    i.stock_seguridad,
    i.stock_transito,
    i.dias_cobertura,
    v.venta_promedio_diaria,
    v.desviacion_ventas,
    CASE 
        WHEN v.venta_promedio_diaria > 0 
        THEN (i.unidades_stock::NUMERIC / v.venta_promedio_diaria)::INT
        ELSE 999 
    END AS dias_inventario_disponible,
    CASE
        WHEN i.unidades_stock <= 0 THEN 'SIN_STOCK'
        WHEN i.unidades_stock < i.stock_seguridad THEN 'CRITICO'
        WHEN i.unidades_stock < i.stock_seguridad * 1.5 THEN 'BAJO'
        WHEN i.unidades_stock > s.stock_maximo * 0.9 THEN 'SOBRESTOCK'
        ELSE 'NORMAL'
    END AS estado_stock,
    i.unidades_stock * s.costo_unitario AS valor_inventario
FROM ultimo_inventario i
JOIN public.sku_atc s ON s.sku = i.sku
LEFT JOIN ventas_recientes v ON v.sku = i.sku
WHERE s.activo = TRUE;

-- Vista de KPIs del modelo predictivo
CREATE OR REPLACE VIEW public.v_kpi_modelo AS
WITH ultimo_run AS (
    SELECT * FROM public.v_latest_run
),
metricas_agregadas AS (
    SELECT
        m.run_id,
        COUNT(DISTINCT m.sku) AS skus_evaluados,
        ROUND(AVG(m.mape)::NUMERIC, 2) AS mape_promedio,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY m.mape)::NUMERIC, 2) AS mape_mediana,
        ROUND(AVG(m.mae)::NUMERIC, 2) AS mae_promedio,
        ROUND(AVG(m.rmse)::NUMERIC, 2) AS rmse_promedio,
        ROUND(AVG(m.sesgo)::NUMERIC, 2) AS sesgo_promedio,
        ROUND(AVG(m.r2_score)::NUMERIC, 3) AS r2_promedio,
        COUNT(CASE WHEN m.mape < 20 THEN 1 END) AS skus_mape_bajo_20,
        COUNT(CASE WHEN m.mape < 30 THEN 1 END) AS skus_mape_bajo_30
    FROM public.metricas_backtesting m
    JOIN ultimo_run ur ON ur.run_id = m.run_id
    GROUP BY m.run_id
)
SELECT
    ur.run_id,
    ur.modelo,
    ur.version,
    ur.horizonte_dias,
    ur.ts_inicio,
    ur.ts_fin,
    ma.skus_evaluados,
    ma.mape_promedio,
    ma.mape_mediana,
    ma.mae_promedio,
    ma.rmse_promedio,
    ma.sesgo_promedio,
    ma.r2_promedio,
    ROUND((ma.skus_mape_bajo_20::NUMERIC / NULLIF(ma.skus_evaluados, 0) * 100), 1) AS pct_skus_mape_bajo_20,
    ROUND((ma.skus_mape_bajo_30::NUMERIC / NULLIF(ma.skus_evaluados, 0) * 100), 1) AS pct_skus_mape_bajo_30,
    CASE
        WHEN ma.mape_promedio < 20 THEN 'EXCELENTE'
        WHEN ma.mape_promedio < 30 THEN 'BUENO'
        WHEN ma.mape_promedio < 40 THEN 'ACEPTABLE'
        ELSE 'REQUIERE_MEJORA'
    END AS calidad_modelo
FROM ultimo_run ur
LEFT JOIN metricas_agregadas ma ON ma.run_id = ur.run_id;

-- Vista de alertas activas con priorización
CREATE OR REPLACE VIEW public.v_alertas_activas AS
SELECT 
    a.id,
    a.ts_creacion,
    a.sku,
    s.nombre_producto,
    s.es_esencial,
    a.tipo_alerta,
    a.severidad,
    a.estado,
    a.fecha_objetivo,
    a.descripcion,
    a.accion_sugerida,
    a.impacto_estimado,
    a.valor_metrica,
    a.umbral_metrica,
    EXTRACT(EPOCH FROM (NOW() - a.ts_creacion))/3600 AS horas_pendiente,
    -- Score de prioridad (0-100)
    (
        CASE a.severidad 
            WHEN 'CRITICA' THEN 40
            WHEN 'ALTA' THEN 30
            WHEN 'MEDIA' THEN 20
            ELSE 10
        END +
        CASE WHEN s.es_esencial THEN 20 ELSE 0 END +
        CASE a.tipo_alerta
            WHEN 'QUIEBRE_STOCK' THEN 20
            WHEN 'REPOSICION_URGENTE' THEN 20
            WHEN 'VENCIMIENTO' THEN 15
            WHEN 'DEMANDA_ANOMALA' THEN 10
            ELSE 5
        END +
        CASE 
            WHEN EXTRACT(EPOCH FROM (NOW() - a.ts_creacion))/3600 > 24 THEN 10
            WHEN EXTRACT(EPOCH FROM (NOW() - a.ts_creacion))/3600 > 12 THEN 5
            ELSE 0
        END
    ) AS score_prioridad
FROM public.alertas a
JOIN public.sku_atc s ON s.sku = a.sku
WHERE a.estado IN ('PENDIENTE', 'EN_REVISION')
    AND s.activo = TRUE
ORDER BY score_prioridad DESC, a.ts_creacion;

-- Vista de análisis ABC de productos
CREATE OR REPLACE VIEW public.v_analisis_abc AS
WITH ventas_valor AS (
    SELECT 
        v.sku,
        s.nombre_producto,
        s.atc_code,
        s.es_esencial,
        SUM(v.unidades_vendidas) AS unidades_totales,
        SUM(v.monto_total) AS valor_total,
        AVG(v.unidades_vendidas) AS promedio_diario
    FROM public.ventas_diarias v
    JOIN public.sku_atc s ON s.sku = v.sku
    WHERE v.fecha >= CURRENT_DATE - INTERVAL '90 days'
        AND s.activo = TRUE
    GROUP BY v.sku, s.nombre_producto, s.atc_code, s.es_esencial
),
clasificacion AS (
    SELECT
        *,
        SUM(valor_total) OVER () AS valor_total_global,
        SUM(valor_total) OVER (ORDER BY valor_total DESC) AS valor_acumulado,
        ROW_NUMBER() OVER (ORDER BY valor_total DESC) AS ranking
    FROM ventas_valor
)
SELECT
    sku,
    nombre_producto,
    atc_code,
    es_esencial,
    unidades_totales,
    valor_total,
    promedio_diario,
    ROUND((valor_total / NULLIF(valor_total_global, 0) * 100)::NUMERIC, 2) AS pct_valor_total,
    ROUND((valor_acumulado / NULLIF(valor_total_global, 0) * 100)::NUMERIC, 2) AS pct_acumulado,
    CASE
        WHEN valor_acumulado / NULLIF(valor_total_global, 0) <= 0.8 THEN 'A'
        WHEN valor_acumulado / NULLIF(valor_total_global, 0) <= 0.95 THEN 'B'
        ELSE 'C'
    END AS categoria_abc,
    ranking
FROM clasificacion
ORDER BY valor_total DESC;

-- Vista de resumen ejecutivo para dashboard principal
CREATE OR REPLACE VIEW public.v_resumen_ejecutivo AS
WITH metricas_inventario AS (
    SELECT
        COUNT(DISTINCT sku) AS total_skus,
        COUNT(DISTINCT CASE WHEN estado_stock = 'SIN_STOCK' THEN sku END) AS skus_sin_stock,
        COUNT(DISTINCT CASE WHEN estado_stock = 'CRITICO' THEN sku END) AS skus_criticos,
        COUNT(DISTINCT CASE WHEN estado_stock = 'SOBRESTOCK' THEN sku END) AS skus_sobrestock,
        SUM(valor_inventario) AS valor_total_inventario
    FROM public.v_estado_inventario
),
metricas_alertas AS (
    SELECT
        COUNT(*) AS total_alertas_activas,
        COUNT(CASE WHEN severidad = 'CRITICA' THEN 1 END) AS alertas_criticas,
        COUNT(CASE WHEN severidad = 'ALTA' THEN 1 END) AS alertas_altas,
        AVG(horas_pendiente) AS promedio_horas_pendiente
    FROM public.v_alertas_activas
),
metricas_caducidad AS (
    SELECT
        COUNT(DISTINCT sku) AS skus_proximos_vencer,
        SUM(valor_en_riesgo) AS valor_riesgo_vencimiento
    FROM public.v_caducidades_proximas
    WHERE dias_hasta_vencimiento <= 30
),
metricas_modelo AS (
    SELECT
        mape_promedio,
        pct_skus_mape_bajo_30,
        calidad_modelo
    FROM public.v_kpi_modelo
    LIMIT 1
)
SELECT
    -- Métricas de inventario
    mi.total_skus,
    mi.skus_sin_stock,
    mi.skus_criticos,
    mi.skus_sobrestock,
    ROUND((mi.skus_sin_stock::NUMERIC / NULLIF(mi.total_skus, 0) * 100), 1) AS pct_sin_stock,
    mi.valor_total_inventario,
    -- Métricas de alertas
    ma.total_alertas_activas,
    ma.alertas_criticas,
    ma.alertas_altas,
    ROUND(ma.promedio_horas_pendiente::NUMERIC, 1) AS promedio_horas_resolucion,
    -- Métricas de caducidad
    mc.skus_proximos_vencer,
    mc.valor_riesgo_vencimiento,
    -- Métricas del modelo
    mm.mape_promedio,
    mm.pct_skus_mape_bajo_30,
    mm.calidad_modelo,
    -- Timestamp
    NOW() AS fecha_actualizacion
FROM metricas_inventario mi
CROSS JOIN metricas_alertas ma
CROSS JOIN metricas_caducidad mc
LEFT JOIN metricas_modelo mm ON TRUE;

-- =========================================================================
-- SECCIÓN 8: FUNCIONES Y PROCEDIMIENTOS ALMACENADOS
-- =========================================================================

-- Función para reconocer alertas
CREATE OR REPLACE FUNCTION public.ack_alert(
    p_id UUID,
    p_comentario TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE public.alertas
    SET 
        estado = 'RESUELTA',
        resuelta = TRUE,
        acknowledged_by = auth.uid(),
        acknowledged_at = NOW(),
        resolucion_comentario = p_comentario,
        ts_actualizacion = NOW()
    WHERE id = p_id
        AND estado IN ('PENDIENTE', 'EN_REVISION');
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Alerta no encontrada o ya resuelta: %', p_id;
    END IF;
END;
$$;

-- Función para generar alertas de quiebre de stock
CREATE OR REPLACE FUNCTION public.generar_alertas_quiebre()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    alertas_generadas INTEGER := 0;
    r RECORD;
BEGIN
    -- Generar alertas para productos con stock crítico
    FOR r IN (
        SELECT 
            ei.sku,
            ei.unidades_stock,
            ei.stock_seguridad,
            ei.dias_inventario_disponible,
            s.nombre_producto,
            s.es_esencial,
            df.max_prob_quiebre_28d
        FROM public.v_estado_inventario ei
        JOIN public.sku_atc s ON s.sku = ei.sku
        LEFT JOIN public.v_demanda_futura_7_14_28 df ON df.sku = ei.sku
        WHERE ei.estado_stock IN ('SIN_STOCK', 'CRITICO')
            AND NOT EXISTS (
                SELECT 1 FROM public.alertas a
                WHERE a.sku = ei.sku
                    AND a.tipo_alerta = 'QUIEBRE_STOCK'
                    AND a.estado IN ('PENDIENTE', 'EN_REVISION')
                    AND a.ts_creacion >= NOW() - INTERVAL '24 hours'
            )
    )
    LOOP
        INSERT INTO public.alertas (
            sku,
            tipo_alerta,
            severidad,
            estado,
            fecha_objetivo,
            valor_metrica,
            umbral_metrica,
            descripcion,
            accion_sugerida,
            impacto_estimado
        ) VALUES (
            r.sku,
            'QUIEBRE_STOCK',
            CASE 
                WHEN r.unidades_stock = 0 THEN 'CRITICA'
                WHEN r.es_esencial THEN 'ALTA'
                ELSE 'MEDIA'
            END,
            'PENDIENTE',
            CURRENT_DATE + INTERVAL '1 day' * r.dias_inventario_disponible,
            r.unidades_stock,
            r.stock_seguridad,
            FORMAT('Stock crítico para %s. Stock actual: %s unidades, Stock seguridad: %s unidades',
                r.nombre_producto, r.unidades_stock, r.stock_seguridad),
            'Generar orden de compra urgente al proveedor principal',
            r.stock_seguridad * 10 -- Estimación simple del impacto
        );
        
        alertas_generadas := alertas_generadas + 1;
    END LOOP;
    
    RETURN alertas_generadas;
END;
$$;

-- Función para generar alertas de vencimiento
CREATE OR REPLACE FUNCTION public.generar_alertas_vencimiento()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    alertas_generadas INTEGER := 0;
    r RECORD;
BEGIN
    -- Generar alertas para productos próximos a vencer
    FOR r IN (
        SELECT 
            sku,
            lote_id,
            nombre_producto,
            fecha_caducidad,
            dias_hasta_vencimiento,
            unidades,
            valor_en_riesgo,
            nivel_urgencia
        FROM public.v_caducidades_proximas
        WHERE dias_hasta_vencimiento <= 30
            AND NOT EXISTS (
                SELECT 1 FROM public.alertas a
                WHERE a.lote_id = v_caducidades_proximas.lote_id
                    AND a.tipo_alerta = 'VENCIMIENTO'
                    AND a.estado IN ('PENDIENTE', 'EN_REVISION')
            )
    )
    LOOP
        INSERT INTO public.alertas (
            sku,
            tipo_alerta,
            severidad,
            estado,
            fecha_objetivo,
            lote_id,
            valor_metrica,
            descripcion,
            accion_sugerida,
            impacto_estimado
        ) VALUES (
            r.sku,
            'VENCIMIENTO',
            CASE r.nivel_urgencia
                WHEN 'CRITICO' THEN 'CRITICA'
                WHEN 'ALTO' THEN 'ALTA'
                ELSE 'MEDIA'
            END,
            'PENDIENTE',
            r.fecha_caducidad,
            r.lote_id,
            r.unidades,
            FORMAT('Lote %s de %s vence en %s días. %s unidades en riesgo',
                r.lote_id, r.nombre_producto, r.dias_hasta_vencimiento, r.unidades),
            CASE 
                WHEN r.dias_hasta_vencimiento <= 7 THEN 'Aplicar descuento inmediato o devolver al proveedor'
                WHEN r.dias_hasta_vencimiento <= 15 THEN 'Promoción especial para acelerar rotación'
                ELSE 'Priorizar en despacho FIFO'
            END,
            r.valor_en_riesgo
        );
        
        alertas_generadas := alertas_generadas + 1;
    END LOOP;
    
    RETURN alertas_generadas;
END;
$$;

-- Función principal para llamar al API de forecast
CREATE OR REPLACE FUNCTION public.call_forecast()
RETURNS VOID 
LANGUAGE plpgsql 
SECURITY DEFINER 
SET search_path = public
SET statement_timeout = '30s'
AS $$
BEGIN
    -- Llamar al endpoint de forecast
    PERFORM net.http_post(
        url := current_setting('app.forecast_api_url', true),
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-API-Key', current_setting('app.forecast_api_key', true)
        ),
        body := jsonb_build_object(
            'trigger', 'scheduled',
            'timestamp', NOW(),
            'horizonte_dias', 28
        )
    );
    
    -- Generar alertas después del forecast
    PERFORM public.generar_alertas_quiebre();
    PERFORM public.generar_alertas_vencimiento();
    
EXCEPTION
    WHEN OTHERS THEN
        -- Log del error
        INSERT INTO public.audit_inventario (
            ts_cambio,
            sku,
            tipo_movimiento,
            cantidad,
            motivo,
            metadata
        ) VALUES (
            NOW(),
            'SYSTEM',
            'ERROR_FORECAST',
            0,
            'Error en ejecución de forecast',
            jsonb_build_object(
                'error', SQLERRM,
                'detail', SQLSTATE
            )
        );
        RAISE;
END;
$$;

-- Función de limpieza de datos antiguos
CREATE OR REPLACE FUNCTION public.cleanup_old_data()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    registros_eliminados INTEGER;
BEGIN
    -- Eliminar ejecuciones de modelo antiguas (> 90 días)
    DELETE FROM public.ejecuciones_modelo
    WHERE ts_inicio < NOW() - INTERVAL '90 days';
    
    GET DIAGNOSTICS registros_eliminados = ROW_COUNT;
    
    -- Eliminar alertas resueltas antiguas (> 180 días)
    DELETE FROM public.alertas
    WHERE estado = 'RESUELTA'
        AND ts_actualizacion < NOW() - INTERVAL '180 days';
    
    -- Eliminar logs de auditoría antiguos (> 365 días)
    DELETE FROM public.audit_inventario
    WHERE ts_cambio < NOW() - INTERVAL '365 days';
    
    -- Vacuum para recuperar espacio
    VACUUM ANALYZE;
    
    -- Log de la limpieza
    INSERT INTO public.audit_inventario (
        ts_cambio,
        sku,
        tipo_movimiento,
        cantidad,
        motivo,
        metadata
    ) VALUES (
        NOW(),
        'SYSTEM',
        'LIMPIEZA',
        registros_eliminados,
        'Limpieza programada de datos antiguos',
        jsonb_build_object(
            'ejecuciones_eliminadas', registros_eliminados,
            'timestamp', NOW()
        )
    );
END;
$$;

-- =========================================================================
-- SECCIÓN 9: POLÍTICAS DE SEGURIDAD (RLS)
-- =========================================================================

-- Habilitar RLS en todas las tablas
ALTER TABLE public.sku_atc ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ventas_diarias ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventario_diario ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lotes_caducidad ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ejecuciones_modelo ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.metricas_backtesting ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.forecast_historico ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alertas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.config_alertas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_inventario ENABLE ROW LEVEL SECURITY;

-- Políticas de lectura para usuarios autenticados
DROP POLICY IF EXISTS "read_all_sku_atc" ON public.sku_atc;
CREATE POLICY "read_all_sku_atc" ON public.sku_atc 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_ventas" ON public.ventas_diarias;
CREATE POLICY "read_all_ventas" ON public.ventas_diarias 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_inventario" ON public.inventario_diario;
CREATE POLICY "read_all_inventario" ON public.inventario_diario 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_lotes" ON public.lotes_caducidad;
CREATE POLICY "read_all_lotes" ON public.lotes_caducidad 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_ejecuciones" ON public.ejecuciones_modelo;
CREATE POLICY "read_all_ejecuciones" ON public.ejecuciones_modelo 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_metricas" ON public.metricas_backtesting;
CREATE POLICY "read_all_metricas" ON public.metricas_backtesting 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_forecast" ON public.forecast_historico;
CREATE POLICY "read_all_forecast" ON public.forecast_historico 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_alertas" ON public.alertas;
CREATE POLICY "read_all_alertas" ON public.alertas 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "read_all_config" ON public.config_alertas;
CREATE POLICY "read_all_config" ON public.config_alertas 
    FOR SELECT TO authenticated USING (true);

-- Políticas de escritura para service_role
DROP POLICY IF EXISTS "write_by_service_forecast" ON public.forecast_historico;
CREATE POLICY "write_by_service_forecast" ON public.forecast_historico 
    FOR ALL TO service_role WITH CHECK (true);

DROP POLICY IF EXISTS "write_by_service_ejec" ON public.ejecuciones_modelo;
CREATE POLICY "write_by_service_ejec" ON public.ejecuciones_modelo 
    FOR ALL TO service_role WITH CHECK (true);

DROP POLICY IF EXISTS "write_by_service_metr" ON public.metricas_backtesting;
CREATE POLICY "write_by_service_metr" ON public.metricas_backtesting 
    FOR ALL TO service_role WITH CHECK (true);

DROP POLICY IF EXISTS "write_by_service_alert" ON public.alertas;
CREATE POLICY "write_by_service_alert" ON public.alertas 
    FOR ALL TO service_role WITH CHECK (true);

DROP POLICY IF EXISTS "write_by_service_audit" ON public.audit_inventario;
CREATE POLICY "write_by_service_audit" ON public.audit_inventario 
    FOR ALL TO service_role WITH CHECK (true);

-- Política especial para actualización de alertas por usuarios autenticados
DROP POLICY IF EXISTS "update_alertas_authenticated" ON public.alertas;
CREATE POLICY "update_alertas_authenticated" ON public.alertas 
    FOR UPDATE TO authenticated 
    USING (estado IN ('PENDIENTE', 'EN_REVISION'))
    WITH CHECK (acknowledged_by = auth.uid());

-- =========================================================================
-- SECCIÓN 10: PROGRAMACIÓN DE TAREAS (CRON JOBS)
-- =========================================================================

-- Programar forecast cada 4 horas
SELECT cron.schedule(
    'forecast_4h',
    '0 */4 * * *',
    $$ SELECT public.call_forecast(); $$
);

-- Programar limpieza semanal (domingos a las 2 AM)
SELECT cron.schedule(
    'cleanup_weekly',
    '0 2 * * 0',
    $$ SELECT public.cleanup_old_data(); $$
);

-- Programar generación de alertas cada hora
SELECT cron.schedule(
    'alertas_hourly',
    '0 * * * *',
    $$ 
    SELECT public.generar_alertas_quiebre();
    SELECT public.generar_alertas_vencimiento();
    $$
);

-- =========================================================================
-- SECCIÓN 11: DATOS DE CONFIGURACIÓN INICIAL
-- =========================================================================

-- Insertar configuración de umbrales de alertas por defecto
INSERT INTO public.config_alertas (tipo_alerta, atc_nivel2, umbral_critico, umbral_alto, umbral_medio, umbral_bajo, descripcion)
VALUES 
    ('QUIEBRE_STOCK', NULL, 0, 10, 20, 50, 'Umbrales generales para alertas de quiebre de stock'),
    ('VENCIMIENTO', NULL, 7, 15, 30, 60, 'Días antes del vencimiento para generar alertas'),
    ('SOBRESTOCK', NULL, 200, 150, 120, 100, 'Porcentaje sobre stock máximo'),
    ('DEMANDA_ANOMALA', NULL, 300, 200, 150, 120, 'Porcentaje de variación sobre promedio histórico')
ON CONFLICT (tipo_alerta, atc_nivel2) DO NOTHING;

-- =========================================================================
-- SECCIÓN 12: GRANTS Y PERMISOS
-- =========================================================================

-- Permisos para funciones
REVOKE ALL ON FUNCTION public.ack_alert(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ack_alert(UUID, TEXT) TO authenticated;

REVOKE ALL ON FUNCTION public.call_forecast() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.call_forecast() TO postgres, service_role;

REVOKE ALL ON FUNCTION public.cleanup_old_data() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.cleanup_old_data() TO postgres, service_role;

REVOKE ALL ON FUNCTION public.generar_alertas_quiebre() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.generar_alertas_quiebre() TO postgres, service_role;

REVOKE ALL ON FUNCTION public.generar_alertas_vencimiento() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.generar_alertas_vencimiento() TO postgres, service_role;

-- =========================================================================
-- FIN DEL SCRIPT
-- =========================================================================