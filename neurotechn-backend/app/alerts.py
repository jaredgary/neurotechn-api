from __future__ import annotations
import datetime as dt
from typing import Dict, List, Tuple
import pandas as pd
from .db import execute


def generate_alert_rows(
    inv_df: pd.DataFrame,
    lotes_df: pd.DataFrame,
    forecasts: Dict[str, List[Tuple[dt.date, float]]],
):
    inv = inv_df.set_index("sku").to_dict(orient="index")
    agg = {sku: {"7": 0.0, "14": 0.0, "28": 0.0} for sku in forecasts.keys()}
    for sku, items in forecasts.items():
        for (fecha, yhat) in items:
            d = (fecha - dt.date.today()).days
            if d <= 7:
                agg[sku]["7"] += yhat
            if d <= 14:
                agg[sku]["14"] += yhat
            if d <= 28:
                agg[sku]["28"] += yhat
    rows = []
    for sku in forecasts.keys():
        stock = float(inv.get(sku, {}).get("unidades_stock", 0))
        # QUIEBRE_STOCK
        if stock < agg[sku]["7"]:
            rows.append(
                (
                    sku,
                    "QUIEBRE_STOCK",
                    "ALTA",
                    dt.date.today() + dt.timedelta(days=7),
                    None,
                    f"stock={stock}, yhat_7={agg[sku]['7']:.1f}, yhat_14={agg[sku]['14']:.1f}, yhat_28={agg[sku]['28']:.1f}",
                )
            )
        elif stock < agg[sku]["14"]:
            rows.append(
                (
                    sku,
                    "QUIEBRE_STOCK",
                    "MEDIA",
                    dt.date.today() + dt.timedelta(days=14),
                    None,
                    f"stock={stock}, yhat_14={agg[sku]['14']:.1f}",
                )
            )
        elif stock < agg[sku]["28"]:
            rows.append(
                (
                    sku,
                    "QUIEBRE_STOCK",
                    "BAJA",
                    dt.date.today() + dt.timedelta(days=28),
                    None,
                    f"stock={stock}, yhat_28={agg[sku]['28']:.1f}",
                )
            )
        # VENCIMIENTO (FEFO 30d)
        cad = lotes_df[lotes_df["sku"] == sku]
        cad_30 = cad[cad["fecha_caducidad"] <= (dt.date.today() + dt.timedelta(days=30))]
        if not cad_30.empty:
            u_cad = float(cad_30["unidades"].sum())
            if u_cad > agg[sku]["28"]:
                first = cad_30.sort_values("fecha_caducidad").iloc[0]
                rows.append(
                    (
                        sku,
                        "VENCIMIENTO",
                        "MEDIA",
                        first["fecha_caducidad"],
                        first["lote_id"],
                        f"caduca_30d={int(u_cad)} > demanda_28d={agg[sku]['28']:.1f}",
                    )
                )
    return rows


def insert_alerts(alert_rows):
    if not alert_rows:
        return
    sql = """
      insert into public.alertas (sku, tipo_alerta, severidad, fecha_objetivo, lote_id, descripcion)
      values (%s,%s,%s,%s,%s,%s)
    """
    execute(sql, alert_rows, many=True)

