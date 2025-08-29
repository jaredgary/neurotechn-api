# generate_synthetic_data.py
"""
Generador de datos sintéticos realistas para Farmacias Siman
Contexto: San Pedro Sula, medicamentos esenciales, 90 días históricos
Parches críticos:
- Inventario usa las ventas ya generadas (no regenera)
- upsert con on_conflict para respetar PK/unique
- semillas aleatorias para reproducibilidad
"""

import os
import random
import string
from datetime import date, timedelta, datetime
from typing import List, Dict, Tuple
import pandas as pd
import numpy as np
from supabase import create_client, Client

# -----------------------------
# Configuración
# -----------------------------
# Puedes sobreescribir por variables de entorno, deja defaults prácticos
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tpsctsbuaekmityqhxnn.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # Usar service key, no anon

if not SUPABASE_SERVICE_KEY:
    print("ERROR: Set SUPABASE_SERVICE_KEY environment variable")
    raise SystemExit(1)

# Reproducibilidad
SEED = int(os.getenv("SYNTHETIC_SEED", "42"))
random.seed(SEED)
np.random.seed(SEED)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -----------------------------
# Medicamentos esenciales (ATC reales)
# -----------------------------
MEDICAMENTOS_ESENCIALES = [
    # Analgésicos y antiinflamatorios
    ("ACETAMINOFEN-500MG", "Acetaminofén 500mg", "N02BE01", 5),
    ("IBUPROFENO-400MG", "Ibuprofeno 400mg", "M01AE01", 7),
    ("ASPIRINA-100MG", "Aspirina 100mg", "N02BA01", 14),
    ("DICLOFENACO-50MG", "Diclofenaco 50mg", "M01AB05", 10),

    # Antibióticos
    ("AMOXICILINA-500MG", "Amoxicilina 500mg", "J01CA04", 3),
    ("AZITROMICINA-500MG", "Azitromicina 500mg", "J01FA10", 5),
    ("CEFALEXINA-500MG", "Cefalexina 500mg", "J01DB01", 7),
    ("CIPROFLOXACINA-500MG", "Ciprofloxacina 500mg", "J01MA02", 14),

    # Cardiovasculares
    ("ENALAPRIL-10MG", "Enalapril 10mg", "C09AA02", 30),
    ("AMLODIPINA-5MG", "Amlodipina 5mg", "C08CA01", 30),
    ("ATENOLOL-50MG", "Atenolol 50mg", "C07AB03", 45),
    ("HIDROCLOROTIAZIDA-25MG", "Hidroclorotiazida 25mg", "C03AA03", 30),

    # Diabetes
    ("METFORMINA-850MG", "Metformina 850mg", "A10BA02", 30),
    ("GLIBENCLAMIDA-5MG", "Glibenclamida 5mg", "A10BB01", 30),
    ("INSULINA-REGULAR", "Insulina Regular", "A10AB01", 2),

    # Gastrointestinales
    ("OMEPRAZOL-20MG", "Omeprazol 20mg", "A02BC01", 14),
    ("RANITIDINA-150MG", "Ranitidina 150mg", "A02BA02", 21),
    ("LOPERAMIDA-2MG", "Loperamida 2mg", "A07DA03", 30),

    # Respiratorios
    ("SALBUTAMOL-100MCG", "Salbutamol 100mcg", "R03AC02", 7),
    ("LORATADINA-10MG", "Loratadina 10mg", "R06AX13", 21),
    ("DEXTROMETORFANO-15MG", "Dextrometorfano 15mg", "R05DA09", 14),

    # Vitaminas y minerales
    ("ACIDO-FOLICO-5MG", "Ácido Fólico 5mg", "B03BB01", 60),
    ("COMPLEJO-B", "Complejo B", "A11EA", 45),
    ("VITAMINA-C-500MG", "Vitamina C 500mg", "A11GA01", 30),
    ("CALCIO-600MG", "Calcio 600mg", "A12AA04", 30),

    # Ginecológicos
    ("ACIDO-FOLICO-PRENATAL", "Ácido Fólico Prenatal", "B03BB01", 30),
    ("HIERRO-SULFATO-300MG", "Sulfato Ferroso 300mg", "B03AA07", 30),

    # Dermatológicos
    ("CLOTRIMAZOL-1%", "Clotrimazol 1% crema", "D01AC01", 21),
    ("HIDROCORTISONA-1%", "Hidrocortisona 1% crema", "D07AA02", 14),

    # Neurológicos
    ("CARBAMAZEPINA-200MG", "Carbamazepina 200mg", "N03AF01", 30),
    ("FENITOINA-100MG", "Fenitoína 100mg", "N03AB02", 30),

    # Oftalmológicos
    ("DEXAMETASONA-OFTALMICA", "Dexametasona Oftálmica", "S01BA01", 14),
    ("TOBRAMICINA-OFTALMICA", "Tobramicina Oftálmica", "S01AA12", 7),
]

# -----------------------------
# Generadores
# -----------------------------
def generate_sku_atc_data() -> List[Tuple]:
    """Genera datos para tabla sku_atc"""
    data = [(sku, nombre, atc, lead_time) for sku, nombre, atc, lead_time in MEDICAMENTOS_ESENCIALES]
    print(f"Generated {len(data)} SKUs")
    return data


def generate_sales_pattern(sku: str, atc: str, days: int = 90) -> List[int]:
    """Genera patrón de ventas realista basado en tipo de medicamento"""
    base_demand = {
        'N02': 50, 'M01': 25, 'J01': 15, 'C09': 30, 'C08': 25,
        'A10': 20, 'A02': 40, 'R03': 12, 'B03': 8, 'D01': 15,
    }

    atc_prefix = atc[:3]
    daily_mean = base_demand.get(atc_prefix, 20)

    is_chronic = atc_prefix in ['C09', 'C08', 'A10', 'C07']
    is_seasonal = atc_prefix in ['R03', 'R06', 'D01']
    is_acute = atc_prefix in ['J01', 'N02', 'M01']

    sales: List[int] = []

    for day in range(days):
        weekday = day % 7
        weekend_factor = 0.4 if weekday == 6 else 0.7 if weekday == 5 else 1.0

        if is_chronic:
            trend = daily_mean * (0.95 + 0.1 * random.random())
            noise_factor = 0.15
        elif is_seasonal:
            seasonal = 1.5 if day > 60 else 0.8
            trend = daily_mean * seasonal * (0.8 + 0.4 * random.random())
            noise_factor = 0.3
        elif is_acute:
            trend = daily_mean * (0.5 + random.random())
            noise_factor = 0.4
        else:
            trend = daily_mean * (0.8 + 0.4 * random.random())
            noise_factor = 0.25

        daily_sales = trend * weekend_factor
        daily_sales *= (1 + noise_factor * (random.random() - 0.5))

        if random.random() < 0.05:
            daily_sales *= (1.5 + random.random())

        sales.append(max(0, int(daily_sales)))

    return sales


def generate_ventas_diarias() -> List[Tuple[date, str, int, bool, str]]:
    """Genera 90 días de ventas para todos los SKUs"""
    data: List[Tuple[date, str, int, bool, str]] = []
    start_date = date.today() - timedelta(days=90)
    for sku, nombre, atc, _ in MEDICAMENTOS_ESENCIALES:
        sales_pattern = generate_sales_pattern(sku, atc, 90)
        for day_offset, units in enumerate(sales_pattern):
            fecha = start_date + timedelta(days=day_offset)
            canal = "delivery" if random.random() < 0.15 else "mostrador"
            promo = random.random() < 0.08
            data.append((fecha, sku, units, promo, canal))
    print(f"Generated {len(data)} sales records")
    return data


def generate_inventario_diario(ventas_data: List[Tuple[date, str, int, bool, str]]) -> List[Tuple[date, str, int, int]]:
    """Genera inventarios coherentes con las ventas YA generadas (no regenera ventas)"""
    print("Generating inventory data...")

    ventas_by_sku: Dict[str, List[int]] = {}
    for _, sku, units, _, _ in ventas_data:
        ventas_by_sku.setdefault(sku, []).append(units)

    data: List[Tuple[date, str, int, int]] = []
    for sku, nombre, atc, lead_time in MEDICAMENTOS_ESENCIALES:
        ventas_sku = ventas_by_sku.get(sku, [0])
        avg_daily_sales = sum(ventas_sku) / len(ventas_sku)
        std_sales = np.std(ventas_sku) if len(ventas_sku) > 1 else avg_daily_sales * 0.3
        stock_seguridad = int(avg_daily_sales * lead_time * 1.2 + std_sales * 2)

        factor = 0.5 + random.random() * 2.5
        stock_actual = int(stock_seguridad * factor)

        start_date = date.today() - timedelta(days=30)
        stock = stock_actual
        for day_offset in range(31):  # 30 días + hoy
            fecha = start_date + timedelta(days=day_offset)
            if day_offset > 0:
                variation = -0.05 + random.random() * 0.20
                stock = max(0, int(stock * (1 + variation)))
            data.append((fecha, sku, stock, stock_seguridad))

    print(f"Generated {len(data)} inventory records")
    return data


def generate_lote_id() -> str:
    """Genera ID de lote realista"""
    year = random.choice(['23', '24', '25'])
    month = f"{random.randint(1,12):02d}"
    serial = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"L{year}{month}{serial}"


def generate_lotes_caducidad() -> List[Tuple[str, str, int, date]]:
    """Genera lotes con fechas de caducidad realistas"""
    print("Generating batch expiration data...")
    data: List[Tuple[str, str, int, date]] = []

    for sku, nombre, atc, _ in MEDICAMENTOS_ESENCIALES:
        if 'INSULINA' in sku:
            shelf_life_days = (180, 365)
        elif atc.startswith('J01'):
            shelf_life_days = (365, 730)
        elif atc.startswith('R03'):
            shelf_life_days = (730, 1095)
        elif 'CREMA' in nombre or 'OFTALMICA' in nombre:
            shelf_life_days = (365, 545)
        else:
            shelf_life_days = (730, 1460)

        num_lotes = random.randint(2, 4)
        for _ in range(num_lotes):
            lote_id = generate_lote_id()
            days_until_exp = random.randint(*shelf_life_days)
            fecha_cad = date.today() + timedelta(days=days_until_exp)

            if atc.startswith('A10'):
                units = random.randint(20, 100)
            elif atc.startswith('J01'):
                units = random.randint(30, 150)
            else:
                units = random.randint(50, 500)

            data.append((lote_id, sku, units, fecha_cad))

    print(f"Generated {len(data)} batch records")
    return data


# -----------------------------
# Inserción en Supabase
# -----------------------------
def insert_data_to_supabase():
    """Inserta todos los datos en Supabase (usa service_role)"""
    print("Starting data insertion to Supabase...")

    # 1) SKU_ATC
    print("Inserting SKU data...")
    sku_data = generate_sku_atc_data()
    # upsert respetando PK sku
    sku_records = [
        {"sku": sku, "nombre_producto": nombre, "atc_code": atc, "lead_time_dias": lead_time}
        for (sku, nombre, atc, lead_time) in sku_data
    ]
    supabase.table("sku_atc").upsert(sku_records, on_conflict="sku").execute()
    print(f"✓ Inserted/Upserted {len(sku_data)} SKUs")

    # 2) VENTAS_DIARIAS
    print("Generating & inserting sales data...")
    ventas_data = generate_ventas_diarias()
    batch_size = 1000
    for i in range(0, len(ventas_data), batch_size):
        batch = ventas_data[i:i + batch_size]
        batch_records = [{
            "fecha": fecha.isoformat(),
            "sku": sku,
            "unidades_vendidas": units,
            "promo_flag": promo,
            "canal": canal
        } for (fecha, sku, units, promo, canal) in batch]
        # upsert con PK compuesta (fecha,sku)
        supabase.table("ventas_diarias").upsert(batch_records, on_conflict="fecha,sku").execute()
        print(f"  Inserted sales batch {i//batch_size + 1}")
    print(f"✓ Inserted/Upserted {len(ventas_data)} sales records")

    # 3) INVENTARIO_DIARIO (usa ventas generadas)
    print("Generating & inserting inventory data...")
    inventario_data = generate_inventario_diario(ventas_data)
    batch_size = 500
    for i in range(0, len(inventario_data), batch_size):
        batch = inventario_data[i:i + batch_size]
        batch_records = [{
            "fecha": fecha.isoformat(),
            "sku": sku,
            "unidades_stock": stock,
            "stock_seguridad": stock_seg
        } for (fecha, sku, stock, stock_seg) in batch]
        supabase.table("inventario_diario").upsert(batch_records, on_conflict="fecha,sku").execute()
        print(f"  Inserted inventory batch {i//batch_size + 1}")
    print(f"✓ Inserted/Upserted {len(inventario_data)} inventory records")

    # 4) LOTES_CADUCIDAD
    print("Generating & inserting batch data...")
    lotes_data = generate_lotes_caducidad()
    lotes_records = [{
        "lote_id": lote_id,
        "sku": sku,
        "unidades": units,
        "fecha_caducidad": fecha_cad.isoformat()
    } for (lote_id, sku, units, fecha_cad) in lotes_data]
    # upsert por lote_id
    supabase.table("lotes_caducidad").upsert(lotes_records, on_conflict="lote_id").execute()
    print(f"✓ Inserted/Upserted {len(lotes_data)} batch records")

    # Verificación final
    print("\n📊 Verification:")
    sku_count = supabase.table("sku_atc").select("sku", count="exact").execute()
    ventas_count = supabase.table("ventas_diarias").select("fecha", count="exact").execute()
    inv_count = supabase.table("inventario_diario").select("fecha", count="exact").execute()
    lotes_count = supabase.table("lotes_caducidad").select("lote_id", count="exact").execute()

    print(f"  SKUs in DB: {sku_count.count}")
    print(f"  Sales records: {ventas_count.count}")
    print(f"  Inventory records: {inv_count.count}")
    print(f"  Batch records: {lotes_count.count}")

    print("\n🎉 DATA GENERATION COMPLETED SUCCESSFULLY!")
    print(f"Total logical records generated: {len(sku_data) + len(ventas_data) + len(inventario_data) + len(lotes_data)}")


if __name__ == "__main__":
    print("🏥 SIMAN PHARMACY - Synthetic Data Generator")
    print("=" * 50)
    insert_data_to_supabase()
    print("\n✅ Ready for ML model training!")
