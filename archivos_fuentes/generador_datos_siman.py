# =============================================================================
# GENERADOR DE DATOS SINTÉTICOS FARMACIAS SIMAN
# =============================================================================
# Objetivo: Generar datos_farmacias_siman.csv + catalogo_medicamentos.csv
# Alineado con: Encuesta.xlsx, Matriz Disponibilidad/Calidad, OE1
# Autor: Gary González Zepeda
# Fecha: Octubre 2025
# =============================================================================

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURACIÓN GLOBAL
# =============================================================================

class ConfiguracionDatos:
    """Configuración centralizada para generación de datos sintéticos"""
    
    # Parámetros temporales
    NUM_SKUS = 120
    NUM_DIAS = 90
    FECHA_FIN = datetime(2024, 10, 30)  # Fecha final del período
    FECHA_INICIO = FECHA_FIN - timedelta(days=NUM_DIAS - 1)
    
    # Calidad de datos (según encuesta G1: 80-90%)
    CALIDAD_DATOS = 0.90
    
    # Semilla aleatoria para reproducibilidad
    RANDOM_SEED = 42

# =============================================================================
# CATÁLOGO DE MEDICAMENTOS ESENCIALES
# =============================================================================

def crear_catalogo_medicamentos():
    """
    Crear catálogo completo de 120 medicamentos esenciales
    
    Basado en:
    - Encuesta H4: Medicamentos con quiebres frecuentes mencionados
    - Clasificación ATC/DDD OMS
    - Categorización ABC (A=alta rotación, B=media, C=baja)
    - Lista Nacional de Medicamentos Esenciales Honduras (LNME)
    
    Returns:
    --------
    catalogo : pandas.DataFrame
        Catálogo completo con 120 SKUs
    """
    
    # =========================================================================
    # MEDICAMENTOS BASE (35 medicamentos representativos)
    # =========================================================================
    
    medicamentos_base = [
        # =========================
        # MENCIONADOS EN ENCUESTA H4 (con quiebres frecuentes reportados)
        # =========================
        {
            'nombre_comercial': 'Sudagrip',
            'nombre_generico': 'Paracetamol + Clorfenamina + Fenilefrina',
            'codigo_atc': 'R05X',
            'grupo_terapeutico': 'Antigripales',
            'presentacion': 'Tabletas',
            'concentracion': '500mg + 2mg + 5mg',
            'demanda_base': 95,
            'variabilidad': 0.50,
            'categoria_abc': 'A',
            'prob_quiebre': 0.08,  # 8% días con quiebre (mencionado por 2/3 usuarios)
            'lead_time_dias': 5,
            'stock_seguridad': 150,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Histadril',
            'nombre_generico': 'Difenhidramina',
            'codigo_atc': 'R06AA02',
            'grupo_terapeutico': 'Antihistamínicos',
            'presentacion': 'Tabletas',
            'concentracion': '50mg',
            'demanda_base': 70,
            'variabilidad': 0.45,
            'categoria_abc': 'B',
            'prob_quiebre': 0.08,
            'lead_time_dias': 4,
            'stock_seguridad': 100,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Acetaminofén MK',
            'nombre_generico': 'Paracetamol',
            'codigo_atc': 'N02BE01',
            'grupo_terapeutico': 'Analgésicos',
            'presentacion': 'Tabletas',
            'concentracion': '500mg',
            'demanda_base': 140,
            'variabilidad': 0.35,
            'categoria_abc': 'A',
            'prob_quiebre': 0.05,
            'lead_time_dias': 3,
            'stock_seguridad': 200,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Sertal Compuesto',
            'nombre_generico': 'Papaverina + Hioscina',
            'codigo_atc': 'A03FA01',
            'grupo_terapeutico': 'Antiespasmódicos',
            'presentacion': 'Tabletas',
            'concentracion': '30mg + 10mg',
            'demanda_base': 65,
            'variabilidad': 0.40,
            'categoria_abc': 'B',
            'prob_quiebre': 0.06,
            'lead_time_dias': 5,
            'stock_seguridad': 100,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'NAN Optipro',
            'nombre_generico': 'Fórmula infantil',
            'codigo_atc': 'V06DZ99',
            'grupo_terapeutico': 'Nutrición infantil',
            'presentacion': 'Polvo',
            'concentracion': '900g',
            'demanda_base': 110,
            'variabilidad': 0.30,
            'categoria_abc': 'A',
            'prob_quiebre': 0.04,
            'lead_time_dias': 7,
            'stock_seguridad': 150,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': False
        },
        
        # =========================
        # ANALGÉSICOS Y ANTIINFLAMATORIOS (CATEGORÍA A)
        # =========================
        {
            'nombre_comercial': 'Paracetamol',
            'nombre_generico': 'Paracetamol',
            'codigo_atc': 'N02BE01',
            'grupo_terapeutico': 'Analgésicos',
            'presentacion': 'Tabletas',
            'concentracion': '500mg',
            'demanda_base': 150,
            'variabilidad': 0.30,
            'categoria_abc': 'A',
            'prob_quiebre': 0.03,
            'lead_time_dias': 3,
            'stock_seguridad': 250,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Ibuprofeno',
            'nombre_generico': 'Ibuprofeno',
            'codigo_atc': 'M01AE01',
            'grupo_terapeutico': 'Antiinflamatorios',
            'presentacion': 'Tabletas',
            'concentracion': '400mg',
            'demanda_base': 120,
            'variabilidad': 0.35,
            'categoria_abc': 'A',
            'prob_quiebre': 0.03,
            'lead_time_dias': 3,
            'stock_seguridad': 200,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Diclofenaco',
            'nombre_generico': 'Diclofenaco sódico',
            'codigo_atc': 'M01AB05',
            'grupo_terapeutico': 'Antiinflamatorios',
            'presentacion': 'Tabletas',
            'concentracion': '50mg',
            'demanda_base': 95,
            'variabilidad': 0.30,
            'categoria_abc': 'A',
            'prob_quiebre': 0.04,
            'lead_time_dias': 4,
            'stock_seguridad': 150,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Naproxeno',
            'nombre_generico': 'Naproxeno sódico',
            'codigo_atc': 'M01AE02',
            'grupo_terapeutico': 'Antiinflamatorios',
            'presentacion': 'Tabletas',
            'concentracion': '250mg',
            'demanda_base': 85,
            'variabilidad': 0.35,
            'categoria_abc': 'B',
            'prob_quiebre': 0.04,
            'lead_time_dias': 4,
            'stock_seguridad': 120,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        
        # =========================
        # ANTIBIÓTICOS (CATEGORÍA A/B)
        # =========================
        {
            'nombre_comercial': 'Amoxicilina',
            'nombre_generico': 'Amoxicilina',
            'codigo_atc': 'J01CA04',
            'grupo_terapeutico': 'Antibióticos β-lactámicos',
            'presentacion': 'Cápsulas',
            'concentracion': '500mg',
            'demanda_base': 80,
            'variabilidad': 0.40,
            'categoria_abc': 'A',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 120,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Amoxicilina + Clavulánico',
            'nombre_generico': 'Amoxicilina + Ácido clavulánico',
            'codigo_atc': 'J01CR02',
            'grupo_terapeutico': 'Antibióticos β-lactámicos',
            'presentacion': 'Tabletas',
            'concentracion': '875mg + 125mg',
            'demanda_base': 70,
            'variabilidad': 0.40,
            'categoria_abc': 'B',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 100,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Azitromicina',
            'nombre_generico': 'Azitromicina',
            'codigo_atc': 'J01FA10',
            'grupo_terapeutico': 'Antibióticos macrólidos',
            'presentacion': 'Tabletas',
            'concentracion': '500mg',
            'demanda_base': 60,
            'variabilidad': 0.45,
            'categoria_abc': 'B',
            'prob_quiebre': 0.06,
            'lead_time_dias': 6,
            'stock_seguridad': 80,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Ciprofloxacino',
            'nombre_generico': 'Ciprofloxacino',
            'codigo_atc': 'J01MA02',
            'grupo_terapeutico': 'Antibióticos fluoroquinolonas',
            'presentacion': 'Tabletas',
            'concentracion': '500mg',
            'demanda_base': 65,
            'variabilidad': 0.35,
            'categoria_abc': 'B',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 90,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        
        # =========================
        # ANTIHISTAMÍNICOS Y ANTIGRIPALES (CATEGORÍA A/B)
        # =========================
        {
            'nombre_comercial': 'Loratadina',
            'nombre_generico': 'Loratadina',
            'codigo_atc': 'R06AE07',
            'grupo_terapeutico': 'Antihistamínicos',
            'presentacion': 'Tabletas',
            'concentracion': '10mg',
            'demanda_base': 70,
            'variabilidad': 0.30,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 4,
            'stock_seguridad': 100,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Cetirizina',
            'nombre_generico': 'Cetirizina',
            'codigo_atc': 'R06AE07',
            'grupo_terapeutico': 'Antihistamínicos',
            'presentacion': 'Tabletas',
            'concentracion': '10mg',
            'demanda_base': 75,
            'variabilidad': 0.30,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 4,
            'stock_seguridad': 110,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Dextrometorfano',
            'nombre_generico': 'Dextrometorfano HBr',
            'codigo_atc': 'R05DA09',
            'grupo_terapeutico': 'Antitusivos',
            'presentacion': 'Jarabe',
            'concentracion': '15mg/5ml',
            'demanda_base': 55,
            'variabilidad': 0.40,
            'categoria_abc': 'B',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 70,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': False
        },
        
        # =========================
        # GASTROINTESTINALES (CATEGORÍA A/B)
        # =========================
        {
            'nombre_comercial': 'Omeprazol',
            'nombre_generico': 'Omeprazol',
            'codigo_atc': 'A02BC01',
            'grupo_terapeutico': 'Inhibidores bomba protones',
            'presentacion': 'Cápsulas',
            'concentracion': '20mg',
            'demanda_base': 90,
            'variabilidad': 0.25,
            'categoria_abc': 'A',
            'prob_quiebre': 0.03,
            'lead_time_dias': 4,
            'stock_seguridad': 130,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Ranitidina',
            'nombre_generico': 'Ranitidina',
            'codigo_atc': 'A02BA02',
            'grupo_terapeutico': 'Antagonistas H2',
            'presentacion': 'Tabletas',
            'concentracion': '150mg',
            'demanda_base': 70,
            'variabilidad': 0.25,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 4,
            'stock_seguridad': 100,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Metoclopramida',
            'nombre_generico': 'Metoclopramida',
            'codigo_atc': 'A03FA01',
            'grupo_terapeutico': 'Antieméticos',
            'presentacion': 'Tabletas',
            'concentracion': '10mg',
            'demanda_base': 60,
            'variabilidad': 0.30,
            'categoria_abc': 'B',
            'prob_quiebre': 0.04,
            'lead_time_dias': 4,
            'stock_seguridad': 80,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Loperamida',
            'nombre_generico': 'Loperamida',
            'codigo_atc': 'A07DA03',
            'grupo_terapeutico': 'Antidiarreicos',
            'presentacion': 'Cápsulas',
            'concentracion': '2mg',
            'demanda_base': 50,
            'variabilidad': 0.45,
            'categoria_abc': 'C',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 60,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': False
        },
        
        # =========================
        # CARDIOVASCULARES (CATEGORÍA A - medicamentos crónicos)
        # =========================
        {
            'nombre_comercial': 'Enalapril',
            'nombre_generico': 'Enalapril maleato',
            'codigo_atc': 'C09AA02',
            'grupo_terapeutico': 'IECA',
            'presentacion': 'Tabletas',
            'concentracion': '10mg',
            'demanda_base': 110,
            'variabilidad': 0.15,
            'categoria_abc': 'A',
            'prob_quiebre': 0.02,
            'lead_time_dias': 4,
            'stock_seguridad': 180,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Losartán',
            'nombre_generico': 'Losartán potásico',
            'codigo_atc': 'C09CA01',
            'grupo_terapeutico': 'ARA-II',
            'presentacion': 'Tabletas',
            'concentracion': '50mg',
            'demanda_base': 105,
            'variabilidad': 0.15,
            'categoria_abc': 'A',
            'prob_quiebre': 0.02,
            'lead_time_dias': 4,
            'stock_seguridad': 170,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Atorvastatina',
            'nombre_generico': 'Atorvastatina',
            'codigo_atc': 'C10AA05',
            'grupo_terapeutico': 'Estatinas',
            'presentacion': 'Tabletas',
            'concentracion': '20mg',
            'demanda_base': 85,
            'variabilidad': 0.20,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 120,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Simvastatina',
            'nombre_generico': 'Simvastatina',
            'codigo_atc': 'C10AA01',
            'grupo_terapeutico': 'Estatinas',
            'presentacion': 'Tabletas',
            'concentracion': '20mg',
            'demanda_base': 95,
            'variabilidad': 0.20,
            'categoria_abc': 'A',
            'prob_quiebre': 0.02,
            'lead_time_dias': 4,
            'stock_seguridad': 140,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Aspirina',
            'nombre_generico': 'Ácido acetilsalicílico',
            'codigo_atc': 'B01AC06',
            'grupo_terapeutico': 'Antiagregantes',
            'presentacion': 'Tabletas',
            'concentracion': '100mg',
            'demanda_base': 100,
            'variabilidad': 0.20,
            'categoria_abc': 'A',
            'prob_quiebre': 0.02,
            'lead_time_dias': 3,
            'stock_seguridad': 150,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': False
        },
        
        # =========================
        # ANTIDIABÉTICOS (CATEGORÍA A - medicamentos crónicos)
        # =========================
        {
            'nombre_comercial': 'Metformina',
            'nombre_generico': 'Metformina HCl',
            'codigo_atc': 'A10BA02',
            'grupo_terapeutico': 'Antidiabéticos orales',
            'presentacion': 'Tabletas',
            'concentracion': '850mg',
            'demanda_base': 130,
            'variabilidad': 0.15,
            'categoria_abc': 'A',
            'prob_quiebre': 0.02,
            'lead_time_dias': 4,
            'stock_seguridad': 200,
            'lote_minimo': 100,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Glibenclamida',
            'nombre_generico': 'Glibenclamida',
            'codigo_atc': 'A10BB01',
            'grupo_terapeutico': 'Antidiabéticos orales',
            'presentacion': 'Tabletas',
            'concentracion': '5mg',
            'demanda_base': 90,
            'variabilidad': 0.20,
            'categoria_abc': 'A',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 130,
            'lote_minimo': 50,
            'es_esencial': True,
            'requiere_receta': True
        },
        
        # =========================
        # VITAMINAS Y SUPLEMENTOS (CATEGORÍA B/C)
        # =========================
        {
            'nombre_comercial': 'Vitamina B12',
            'nombre_generico': 'Cianocobalamina',
            'codigo_atc': 'A11EA',
            'grupo_terapeutico': 'Vitaminas',
            'presentacion': 'Tabletas',
            'concentracion': '1000mcg',
            'demanda_base': 65,
            'variabilidad': 0.25,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 90,
            'lote_minimo': 50,
            'es_esencial': False,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Vitamina D',
            'nombre_generico': 'Colecalciferol',
            'codigo_atc': 'A11CC05',
            'grupo_terapeutico': 'Vitaminas',
            'presentacion': 'Cápsulas',
            'concentracion': '2000 UI',
            'demanda_base': 75,
            'variabilidad': 0.20,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 100,
            'lote_minimo': 50,
            'es_esencial': False,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Complejo B',
            'nombre_generico': 'Vitaminas del complejo B',
            'codigo_atc': 'A11EA',
            'grupo_terapeutico': 'Vitaminas',
            'presentacion': 'Tabletas',
            'concentracion': 'Multivitamínico',
            'demanda_base': 70,
            'variabilidad': 0.25,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 95,
            'lote_minimo': 50,
            'es_esencial': False,
            'requiere_receta': False
        },
        {
            'nombre_comercial': 'Calcio + Vitamina D',
            'nombre_generico': 'Carbonato de calcio + Colecalciferol',
            'codigo_atc': 'A12AX',
            'grupo_terapeutico': 'Minerales + Vitaminas',
            'presentacion': 'Tabletas',
            'concentracion': '600mg + 400 UI',
            'demanda_base': 80,
            'variabilidad': 0.20,
            'categoria_abc': 'B',
            'prob_quiebre': 0.03,
            'lead_time_dias': 5,
            'stock_seguridad': 110,
            'lote_minimo': 50,
            'es_esencial': False,
            'requiere_receta': False
        },
        
        # =========================
        # RESPIRATORIOS Y OTROS (CATEGORÍA B/C)
        # =========================
        {
            'nombre_comercial': 'Salbutamol',
            'nombre_generico': 'Salbutamol',
            'codigo_atc': 'R03AC02',
            'grupo_terapeutico': 'Broncodilatadores',
            'presentacion': 'Inhalador',
            'concentracion': '100mcg/dosis',
            'demanda_base': 55,
            'variabilidad': 0.30,
            'categoria_abc': 'B',
            'prob_quiebre': 0.04,
            'lead_time_dias': 6,
            'stock_seguridad': 70,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Prednisona',
            'nombre_generico': 'Prednisona',
            'codigo_atc': 'H02AB06',
            'grupo_terapeutico': 'Corticosteroides',
            'presentacion': 'Tabletas',
            'concentracion': '5mg',
            'demanda_base': 50,
            'variabilidad': 0.30,
            'categoria_abc': 'B',
            'prob_quiebre': 0.05,
            'lead_time_dias': 5,
            'stock_seguridad': 65,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Tramadol',
            'nombre_generico': 'Tramadol HCl',
            'codigo_atc': 'N02AX02',
            'grupo_terapeutico': 'Analgésicos opioides',
            'presentacion': 'Cápsulas',
            'concentracion': '50mg',
            'demanda_base': 45,
            'variabilidad': 0.25,
            'categoria_abc': 'C',
            'prob_quiebre': 0.04,
            'lead_time_dias': 6,
            'stock_seguridad': 50,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Diazepam',
            'nombre_generico': 'Diazepam',
            'codigo_atc': 'N05BA01',
            'grupo_terapeutico': 'Ansiolíticos',
            'presentacion': 'Tabletas',
            'concentracion': '5mg',
            'demanda_base': 40,
            'variabilidad': 0.20,
            'categoria_abc': 'C',
            'prob_quiebre': 0.03,
            'lead_time_dias': 6,
            'stock_seguridad': 50,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        },
        {
            'nombre_comercial': 'Clonazepam',
            'nombre_generico': 'Clonazepam',
            'codigo_atc': 'N03AE01',
            'grupo_terapeutico': 'Ansiolíticos',
            'presentacion': 'Tabletas',
            'concentracion': '2mg',
            'demanda_base': 50,
            'variabilidad': 0.20,
            'categoria_abc': 'C',
            'prob_quiebre': 0.03,
            'lead_time_dias': 6,
            'stock_seguridad': 60,
            'lote_minimo': 30,
            'es_esencial': True,
            'requiere_receta': True
        }
    ]
    
    # =========================================================================
    # EXPANDIR A 120 SKUs CON VARIACIONES
    # =========================================================================
    
    skus_completos = []
    contador_sku = 1
    
    for med_base in medicamentos_base:
        # Presentación principal
        sku_principal = {
            'sku': f'MED{str(contador_sku).zfill(3)}',
            **med_base
        }
        skus_completos.append(sku_principal)
        contador_sku += 1
        
        # Agregar presentación alternativa (jarabe/suspensión) cada 3 medicamentos
        if (contador_sku - 1) % 3 == 0 and len(skus_completos) < 115:
            sku_jarabe = {
                'sku': f'MED{str(contador_sku).zfill(3)}',
                'nombre_comercial': f"{med_base['nombre_comercial']} Jarabe",
                'nombre_generico': med_base['nombre_generico'],
                'codigo_atc': med_base['codigo_atc'],
                'grupo_terapeutico': med_base['grupo_terapeutico'],
                'presentacion': 'Jarabe/Suspensión',
                'concentracion': f"{med_base['concentracion']}/5ml",
                'demanda_base': med_base['demanda_base'] * 0.5,
                'variabilidad': med_base['variabilidad'] * 1.1,
                'categoria_abc': 'B' if med_base['categoria_abc'] == 'A' else 'C',
                'prob_quiebre': med_base['prob_quiebre'] * 1.2,
                'lead_time_dias': med_base['lead_time_dias'] + 1,
                'stock_seguridad': int(med_base['stock_seguridad'] * 0.6),
                'lote_minimo': int(med_base['lote_minimo'] * 0.6),
                'es_esencial': med_base['es_esencial'],
                'requiere_receta': med_base['requiere_receta']
            }
            skus_completos.append(sku_jarabe)
            contador_sku += 1
        
        # Agregar versión genérica cada 5 medicamentos
        if (contador_sku - 1) % 5 == 0 and len(skus_completos) < 115:
            sku_generico = {
                'sku': f'MED{str(contador_sku).zfill(3)}',
                'nombre_comercial': f"{med_base['nombre_generico']} Genérico",
                'nombre_generico': med_base['nombre_generico'],
                'codigo_atc': med_base['codigo_atc'],
                'grupo_terapeutico': med_base['grupo_terapeutico'],
                'presentacion': med_base['presentacion'],
                'concentracion': med_base['concentracion'],
                'demanda_base': med_base['demanda_base'] * 0.7,
                'variabilidad': med_base['variabilidad'] * 0.9,
                'categoria_abc': med_base['categoria_abc'],
                'prob_quiebre': med_base['prob_quiebre'] * 0.8,
                'lead_time_dias': med_base['lead_time_dias'],
                'stock_seguridad': int(med_base['stock_seguridad'] * 0.7),
                'lote_minimo': int(med_base['lote_minimo'] * 0.7),
                'es_esencial': med_base['es_esencial'],
                'requiere_receta': med_base['requiere_receta']
            }
            skus_completos.append(sku_generico)
            contador_sku += 1
    
    # Completar hasta 120 con variaciones adicionales
    while len(skus_completos) < ConfiguracionDatos.NUM_SKUS:
        idx_base = len(skus_completos) % len(medicamentos_base)
        med_base = medicamentos_base[idx_base]
        
        variacion = len(skus_completos) // len(medicamentos_base) + 1
        
        sku_variacion = {
            'sku': f'MED{str(contador_sku).zfill(3)}',
            'nombre_comercial': f"{med_base['nombre_comercial']} V{variacion}",
            'nombre_generico': med_base['nombre_generico'],
            'codigo_atc': med_base['codigo_atc'],
            'grupo_terapeutico': med_base['grupo_terapeutico'],
            'presentacion': med_base['presentacion'],
            'concentracion': med_base['concentracion'],
            'demanda_base': med_base['demanda_base'] * (0.7 + np.random.uniform(0, 0.6)),
            'variabilidad': med_base['variabilidad'],
            'categoria_abc': 'A' if len(skus_completos) < 40 else ('B' if len(skus_completos) < 90 else 'C'),
            'prob_quiebre': med_base['prob_quiebre'],
            'lead_time_dias': med_base['lead_time_dias'],
            'stock_seguridad': int(med_base['stock_seguridad'] * (0.7 + np.random.uniform(0, 0.6))),
            'lote_minimo': med_base['lote_minimo'],
            'es_esencial': med_base['es_esencial'],
            'requiere_receta': med_base['requiere_receta']
        }
        skus_completos.append(sku_variacion)
        contador_sku += 1
    
    # Convertir a DataFrame
    catalogo_df = pd.DataFrame(skus_completos)
    
    # Agregar campos adicionales para enriquecer el catálogo
    catalogo_df['proveedor'] = catalogo_df.apply(
        lambda x: f"PROV-{hash(x['nombre_comercial']) % 10 + 1}", axis=1
    )
    catalogo_df['precio_unitario_lps'] = catalogo_df['demanda_base'].apply(
        lambda x: round(x * 0.5 + np.random.uniform(5, 50), 2)
    )
    catalogo_df['fecha_creacion'] = datetime.now().strftime('%Y-%m-%d')
    
    return catalogo_df

# =============================================================================
# GENERACIÓN DE DATOS DE VENTAS
# =============================================================================

def generar_datos_ventas(catalogo_df):
    """
    Generar datos de ventas diarias para 90 días
    
    Patrones simulados:
    - Estacionalidad semanal (lunes/viernes mayor demanda)
    - Tendencia temporal por categoría ABC
    - Ruido aleatorio según variabilidad
    - Eventos de pico (5% probabilidad)
    - Quiebres de stock según prob_quiebre
    
    Parameters:
    -----------
    catalogo_df : pandas.DataFrame
        Catálogo de medicamentos
        
    Returns:
    --------
    ventas_df : pandas.DataFrame
        Datos de ventas diarias
    """
    
    config = ConfiguracionDatos()
    np.random.seed(config.RANDOM_SEED)
    
    datos_ventas = []
    
    # Generar para cada día
    for dia in range(config.NUM_DIAS):
        fecha = config.FECHA_INICIO + timedelta(days=dia)
        fecha_str = fecha.strftime('%Y-%m-%d')
        
        # Factores temporales
        dia_semana = fecha.weekday()  # 0=Lunes, 6=Domingo
        es_lunes_viernes = dia_semana in [0, 4]
        es_fin_semana = dia_semana in [5, 6]
        
        # Factor estacional semanal
        if es_lunes_viernes:
            factor_semanal = 1.25  # +25% demanda
        elif es_fin_semana:
            factor_semanal = 0.65  # -35% demanda
        else:
            factor_semanal = 1.0
        
        # Generar ventas para cada SKU
        for _, sku_info in catalogo_df.iterrows():
            demanda = sku_info['demanda_base']
            
            # Aplicar estacionalidad semanal
            demanda *= factor_semanal
            
            # Tendencia temporal por categoría
            if sku_info['categoria_abc'] == 'A':
                tendencia = 1 + (dia * 0.002)  # +0.2% por día
            elif sku_info['categoria_abc'] == 'B':
                tendencia = 1 + (dia * 0.001)  # +0.1% por día
            else:
                tendencia = 1.0  # Sin tendencia
            
            demanda *= tendencia
            
            # Ruido aleatorio según variabilidad del medicamento
            ruido = 1 + np.random.uniform(-1, 1) * sku_info['variabilidad'] / 2
            demanda *= ruido
            
            # Eventos de pico (5% probabilidad)
            if np.random.random() < 0.05:
                demanda *= 1.7  # Pico +70%
            
            # Quiebres de stock según probabilidad configurada
            if np.random.random() < sku_info['prob_quiebre']:
                demanda = 0
            
            # Asegurar demanda >= 0 y redondear
            demanda = max(0, round(demanda))
            
            datos_ventas.append({
                'fecha': fecha_str,
                'sku': sku_info['sku'],
                'demanda': int(demanda)
            })
    
    ventas_df = pd.DataFrame(datos_ventas)
    
    return ventas_df

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """
    Script principal para generar datos sintéticos
    """
    
    print("\n" + "="*70)
    print("  GENERADOR DE DATOS SINTÉTICOS - FARMACIAS SIMAN")
    print("="*70)
    print("  Objetivo Específico 1: Identificación de Requisitos")
    print("  Alineado con: Encuesta.xlsx + Matriz Disponibilidad/Calidad")
    print("="*70)
    
    # Configuración
    config = ConfiguracionDatos()
    np.random.seed(config.RANDOM_SEED)
    
    # =========================================================================
    # PASO 1: GENERAR CATÁLOGO DE MEDICAMENTOS
    # =========================================================================
    
    print(f"\n📋 PASO 1: Generando catálogo de medicamentos...")
    catalogo_df = crear_catalogo_medicamentos()
    
    print(f"   ✓ SKUs generados: {len(catalogo_df)}")
    print(f"   ✓ Categoría A: {len(catalogo_df[catalogo_df['categoria_abc']=='A'])} SKUs")
    print(f"   ✓ Categoría B: {len(catalogo_df[catalogo_df['categoria_abc']=='B'])} SKUs")
    print(f"   ✓ Categoría C: {len(catalogo_df[catalogo_df['categoria_abc']=='C'])} SKUs")
    
    # Guardar catálogo
    catalogo_df.to_csv('catalogo_medicamentos.csv', index=False, encoding='utf-8')
    print(f"   ✓ Archivo guardado: catalogo_medicamentos.csv")
    
    # =========================================================================
    # PASO 2: GENERAR DATOS DE VENTAS
    # =========================================================================
    
    print(f"\n📊 PASO 2: Generando datos de ventas...")
    print(f"   - Período: {config.FECHA_INICIO.strftime('%Y-%m-%d')} a {config.FECHA_FIN.strftime('%Y-%m-%d')}")
    print(f"   - Días: {config.NUM_DIAS}")
    print(f"   - SKUs: {config.NUM_SKUS}")
    print(f"   - Registros esperados: {config.NUM_SKUS * config.NUM_DIAS}")
    
    ventas_df = generar_datos_ventas(catalogo_df)
    
    print(f"   ✓ Registros generados: {len(ventas_df)}")
    
    # Guardar ventas
    ventas_df.to_csv('datos_farmacias_siman.csv', index=False, encoding='utf-8')
    print(f"   ✓ Archivo guardado: datos_farmacias_siman.csv")
    
    # =========================================================================
    # PASO 3: ESTADÍSTICAS Y VALIDACIÓN
    # =========================================================================
    
    print(f"\n📈 PASO 3: Estadísticas y validación...")
    
    # Calidad de datos
    registros_con_demanda = len(ventas_df[ventas_df['demanda'] > 0])
    registros_sin_demanda = len(ventas_df[ventas_df['demanda'] == 0])
    calidad_real = (registros_con_demanda / len(ventas_df)) * 100
    
    print(f"\n   Calidad de datos:")
    print(f"   - Registros con demanda > 0: {registros_con_demanda} ({calidad_real:.1f}%)")
    print(f"   - Registros con demanda = 0: {registros_sin_demanda} ({100-calidad_real:.1f}%)")
    print(f"   - Meta según encuesta G1: {config.CALIDAD_DATOS*100:.0f}%")
    print(f"   - Estado: {'✓ CUMPLE' if calidad_real >= config.CALIDAD_DATOS*100 else '⚠ REVISAR'}")
    
    # Estadísticas por categoría
    print(f"\n   Demanda promedio por categoría ABC:")
    for cat in ['A', 'B', 'C']:
        skus_cat = catalogo_df[catalogo_df['categoria_abc'] == cat]['sku'].tolist()
        ventas_cat = ventas_df[ventas_df['sku'].isin(skus_cat)]
        demanda_promedio = ventas_cat[ventas_cat['demanda'] > 0]['demanda'].mean()
        print(f"   - Categoría {cat}: {demanda_promedio:.1f} unidades/día")
    
    # Top 5 medicamentos con más quiebres (según datos generados)
    quiebres_por_sku = ventas_df[ventas_df['demanda'] == 0].groupby('sku').size().sort_values(ascending=False)
    
    print(f"\n   Top 5 medicamentos con más quiebres (días sin venta):")
    for idx, (sku, dias_quiebre) in enumerate(quiebres_por_sku.head(5).items(), 1):
        nombre = catalogo_df[catalogo_df['sku'] == sku]['nombre_comercial'].values[0]
        print(f"   {idx}. {sku} ({nombre}): {dias_quiebre} días sin venta ({dias_quiebre/config.NUM_DIAS*100:.1f}%)")
    
    # Validación estructura
    print(f"\n   Validación de estructura:")
    print(f"   - Columnas datos_farmacias_siman.csv: {list(ventas_df.columns)}")
    print(f"   - Columnas catalogo_medicamentos.csv: {len(catalogo_df.columns)} columnas")
    print(f"   - Fechas únicas: {ventas_df['fecha'].nunique()} días")
    print(f"   - SKUs únicos en ventas: {ventas_df['sku'].nunique()}")
    print(f"   - Valores nulos en ventas: {ventas_df.isnull().sum().sum()}")
    
    # =========================================================================
    # PASO 4: RESUMEN FINAL
    # =========================================================================
    
    print("\n" + "="*70)
    print("  ✓ GENERACIÓN COMPLETADA EXITOSAMENTE")
    print("="*70)
    print(f"\n  Archivos generados:")
    print(f"  1. datos_farmacias_siman.csv ({len(ventas_df)} registros)")
    print(f"  2. catalogo_medicamentos.csv ({len(catalogo_df)} SKUs)")
    print(f"\n  Siguiente paso:")
    print(f"  - Ejecutar PROTOCOLO DE VALIDACIÓN WALK-FORWARD.py")
    print(f"  - Ejecutar SCRIPTS BACKTESTING AUTOMATIZADO.py")
    print("="*70 + "\n")
    
    return catalogo_df, ventas_df

# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    catalogo, ventas = main()