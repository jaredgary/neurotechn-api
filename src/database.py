# src/database.py
"""
Repositorio de datos para el MVP NeuroTecHN (Supabase)
- Lectura segura con RLS (roles de Supabase)
- Escrituras solo con service role (server-side)
- Paginación real en alertas con .range(offset, offset+limit-1)
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd
from loguru import logger
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

from src.config import get_settings


class DataRepository:
    """Repositorio de datos (CRUD + utilidades) contra Supabase."""

    def __init__(self) -> None:
        settings = get_settings()
        try:
            # Cliente server-side con service_key (NO exponer al cliente)
            self.client: Client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_KEY,
                options=ClientOptions(
                    auto_refresh_token=False,
                    persist_session=False,
                ),
            )
            self.settings = settings
            logger.info("Supabase client (service) inicializado.")
        except Exception as e:
            logger.error(f"Fallo al inicializar Supabase: {e}")
            raise

    # ------------ Salud / Conexión ------------

    def test_connection(self) -> bool:
        """Prueba rápida de conectividad y permisos."""
        try:
            self.client.table("sku_atc").select("sku").limit(1).execute()
            logger.info("Conexión a Base de Datos OK.")
            return True
        except Exception as e:
            logger.error(f"Fallo prueba de conexión a DB: {e}")
            return False

    # ------------ SKUs ------------

    def get_active_skus(self) -> pd.DataFrame:
        """Lista de SKUs (catálogo ATC)."""
        try:
            res = self.client.table("sku_atc").select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error obteniendo SKUs: {e}")
            return pd.DataFrame()

    def get_sku_by_atc(self, atc_code: str) -> pd.DataFrame:
        """SKUs por prefijo ATC."""
        try:
            res = (
                self.client.table("sku_atc")
                .select("*")
                .like("atc_code", f"{atc_code}%")
                .execute()
            )
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error obteniendo SKUs por ATC: {e}")
            return pd.DataFrame()

    # ------------ Ventas ------------

    def get_sales_data(
        self,
        sku: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """Ventas diarias (filtradas por sku y ventana)."""
        try:
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=self.settings.TRAINING_WINDOW_DAYS)

            q = self.client.table("ventas_diarias").select("*")
            if sku:
                q = q.eq("sku", sku)

            q = q.gte("fecha", start_date.isoformat()).lte("fecha", end_date.isoformat()).order(
                "fecha", desc=False
            )
            if limit:
                q = q.limit(limit)

            res = q.execute()
            if not res.data:
                return pd.DataFrame()

            df = pd.DataFrame(res.data)
            df["fecha"] = pd.to_datetime(df["fecha"])
            return df
        except Exception as e:
            logger.error(f"Error obteniendo ventas: {e}")
            return pd.DataFrame()

    def get_aggregated_sales(
        self,
        group_by: str = "sku",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """Agregados de ventas por sku o por fecha."""
        df = self.get_sales_data(start_date=start_date, end_date=end_date)
        if df.empty:
            return df

        if group_by == "sku":
            out = (
                df.groupby("sku")
                .agg({"unidades_vendidas": ["sum", "mean", "std"], "promo_flag": "mean"})
                .round(3)
            )
            out.columns = ["_".join(c).strip() for c in out.columns.values]
            return out.reset_index()
        if group_by == "date":
            return df.groupby("fecha").agg({"unidades_vendidas": "sum"}).reset_index()
        return df

    # ------------ Inventario ------------

    def get_current_inventory(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Último inventario por SKU (busca últimos 7 días y deduplica por sku)."""
        try:
            q = (
                self.client.table("inventario_diario")
                .select("*")
                .gte("fecha", (date.today() - timedelta(days=7)).isoformat())
            )
            if sku:
                q = q.eq("sku", sku)

            res = q.order("fecha", desc=True).execute()
            if not res.data:
                return pd.DataFrame()

            df = pd.DataFrame(res.data)
            df["fecha"] = pd.to_datetime(df["fecha"])
            df = df.sort_values("fecha", ascending=False).drop_duplicates(subset=["sku"], keep="first")
            return df.reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error obteniendo inventario: {e}")
            return pd.DataFrame()

    # ------------ Pronósticos (persistencia) ------------

    def save_forecast_run(
        self,
        modelo: str,
        version: str,
        horizonte_dias: int,
        ventana_entrenamiento_dias: int,
        parametros: Dict[str, Any],
        skus_procesados: int = 0,
    ) -> str:
        """Inserta una ejecución del modelo y retorna run_id."""
        try:
            payload = {
                "modelo": modelo,
                "version": version,
                "horizonte_dias": horizonte_dias,
                "ventana_entrenamiento_dias": ventana_entrenamiento_dias,
                "parametros": parametros,
                "notas": f"skus_procesados={skus_procesados}",
            }
            res = self.client.table("ejecuciones_modelo").insert(payload).execute()
            if not res.data:
                raise RuntimeError("No se recibió run_id al insertar ejecución.")
            run_id = res.data[0]["run_id"]
            logger.info(f"Ejecución creada: run_id={run_id}")
            return run_id
        except Exception as e:
            logger.error(f"Error guardando ejecución: {e}")
            raise

    def update_forecast_run(
        self,
        run_id: str,
        exito: bool,
        skus_procesados: int,
        metricas_globales: Optional[Dict[str, Any]] = None,
        mensaje_error: Optional[str] = None,
    ) -> None:
        """Actualiza notas/resumen de una ejecución."""
        try:
            notas_parts: List[str] = [f"exito={exito}", f"skus_procesados={skus_procesados}"]
            if metricas_globales:
                notas_parts.append(f"metricas={metricas_globales}")
            if mensaje_error:
                notas_parts.append(f"error={mensaje_error}")

            self.client.table("ejecuciones_modelo").update(
                {"notas": "; ".join(map(str, notas_parts))}
            ).eq("run_id", run_id).execute()
            logger.info(f"Ejecución actualizada: run_id={run_id}")
        except Exception as e:
            logger.error(f"Error actualizando ejecución: {e}")

    def save_forecasts(self, run_id: str, forecasts: pd.DataFrame) -> None:
        """Upsert de pronósticos (run_id, sku, fecha_objetivo)."""
        try:
            if forecasts.empty:
                return

            required = {"sku", "fecha_objetivo", "unidades_pronosticadas"}
            missing = required - set(map(str, forecasts.columns))
            if missing:
                raise ValueError(f"Faltan columnas en forecasts: {missing}")

            records: List[Dict[str, Any]] = []
            for _, r in forecasts.iterrows():
                fecha_obj = r["fecha_objetivo"]
                if isinstance(fecha_obj, (datetime, date)):
                    fecha_obj = fecha_obj.isoformat()
                records.append(
                    {
                        "run_id": run_id,
                        "sku": r["sku"],
                        "fecha_objetivo": fecha_obj,
                        "unidades_pronosticadas": float(r["unidades_pronosticadas"]),
                    }
                )

            if records:
                self.client.table("forecast_historico").upsert(
                    records, on_conflict="run_id, sku, fecha_objetivo"
                ).execute()
                logger.info(f"Pronósticos guardados: {len(records)} filas (run_id={run_id})")
        except Exception as e:
            logger.error(f"Error guardando pronósticos: {e}")
            raise

    def save_metrics(self, run_id: str, metrics: pd.DataFrame) -> None:
        """Upsert de métricas por SKU."""
        try:
            if metrics.empty:
                return
            if "sku" not in metrics.columns:
                raise ValueError("La tabla de métricas debe incluir columna 'sku'.")

            payload: List[Dict[str, Any]] = []
            for _, r in metrics.iterrows():
                rec = {
                    "run_id": run_id,
                    "sku": r["sku"],
                    "mape": float(r["mape"]) if "mape" in r and not pd.isna(r["mape"]) else None,
                    "mae": float(r["mae"]) if "mae" in r and not pd.isna(r["mae"]) else None,
                    "smape": float(r["smape"]) if "smape" in r and not pd.isna(r["smape"]) else None,
                    "sesgo": float(r["sesgo"]) if "sesgo" in r and not pd.isna(r["sesgo"]) else None,
                }
                payload.append(rec)

            if payload:
                self.client.table("metricas_backtesting").upsert(
                    payload, on_conflict="run_id, sku"
                ).execute()
                logger.info(f"Métricas guardadas para {len(payload)} SKUs.")
        except Exception as e:
            logger.error(f"Error guardando métricas: {e}")
            raise

    # ------------ Consultas de pronóstico / vistas ------------

    def get_latest_forecast(self, sku: Optional[str] = None) -> pd.DataFrame:
        """Pronósticos del último run coherente (vista v_forecast_latest)."""
        try:
            q = self.client.table("v_forecast_latest").select("*")
            if sku:
                q = q.eq("sku", sku)
            res = q.execute()
            if not res.data:
                return pd.DataFrame()
            df = pd.DataFrame(res.data)
            df["fecha_objetivo"] = pd.to_datetime(df["fecha_objetivo"])
            return df
        except Exception as e:
            logger.error(f"Error obteniendo último forecast: {e}")
            return pd.DataFrame()

    def get_future_demand_agg(self) -> pd.DataFrame:
        """Demanda agregada 7/14/28 días (vista v_demanda_futura_7_14_28)."""
        try:
            res = self.client.table("v_demanda_futura_7_14_28").select("*").execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error obteniendo demanda futura agregada: {e}")
            return pd.DataFrame()

    # ------------ Alertas ------------

    def create_alert(
        self,
        sku: str,
        tipo_alerta: str,
        severidad: str,
        descripcion: str,
        fecha_objetivo: Optional[date] = None,
        lote_id: Optional[str] = None,
    ) -> bool:
        """Crea una alerta (QUIEBRE_STOCK / VENCIMIENTO)."""
        try:
            data: Dict[str, Any] = {
                "sku": sku,
                "tipo_alerta": tipo_alerta,
                "severidad": severidad,
                "descripcion": descripcion,
            }
            if fecha_objetivo:
                data["fecha_objetivo"] = fecha_objetivo.isoformat()
            if lote_id:
                data["lote_id"] = lote_id

            res = self.client.table("alertas").insert(data).execute()
            ok = bool(res.data)
            if ok:
                logger.info(f"Alerta creada para SKU={sku} ({tipo_alerta})")
            return ok
        except Exception as e:
            logger.error(f"Error creando alerta: {e}")
            return False

    def get_active_alerts(
        self,
        sku: Optional[str] = None,
        tipo_alerta: Optional[str] = None,
        severidad: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Lista de alertas abiertas con joins embebidos a sku_atc.
        Soporta paginación: range(offset, offset+limit-1).
        """
        try:
            q = (
                self.client.table("alertas")
                .select("*, sku_atc(nombre_producto)")
                .eq("resuelta", False)
                .order("ts_creacion", desc=True)
            )
            if sku:
                q = q.eq("sku", sku)
            if tipo_alerta:
                q = q.eq("tipo_alerta", tipo_alerta)
            if severidad:
                q = q.eq("severidad", severidad)

            if (limit is not None) and (offset is not None):
                # PostgREST: rango 0-based e inclusivo
                q = q.range(offset, offset + limit - 1)

            res = q.execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e:
            logger.error(f"Error obteniendo alertas: {e}")
            return pd.DataFrame()

    def acknowledge_alert(self, alert_id: str, comentario: Optional[str] = None) -> bool:
        """
        Marca alerta como resuelta usando RPC 'ack_alert(p_id uuid)'.
        Si tu función admite comentario (p_comment), lo envía; si no, reintenta sin él.
        """
        try:
            if comentario is not None:
                self.client.rpc("ack_alert", {"p_id": alert_id, "p_comment": comentario}).execute()
            else:
                self.client.rpc("ack_alert", {"p_id": alert_id}).execute()
            return True
        except Exception:
            try:
                self.client.rpc("ack_alert", {"p_id": alert_id}).execute()
                return True
            except Exception as e2:
                logger.error(f"ack_alert falló: {e2}")
                return False

    # ------------ Lotes por caducar ------------

    def get_expiring_batches(self, days_ahead: int = 30) -> pd.DataFrame:
        """Lotes que vencen en <= days_ahead días (unidades > 0)."""
        try:
            target = (date.today() + timedelta(days=days_ahead)).isoformat()
            res = (
                self.client.table("lotes_caducidad")
                .select("*, sku_atc(nombre_producto)")
                .lte("fecha_caducidad", target)
                .gt("unidades", 0)
                .order("fecha_caducidad", desc=False)
                .execute()
            )
            if not res.data:
                return pd.DataFrame()
            df = pd.DataFrame(res.data)
            df["fecha_caducidad"] = pd.to_datetime(df["fecha_caducidad"])
            df["dias_hasta_vencimiento"] = (df["fecha_caducidad"] - pd.Timestamp.today()).dt.days
            return df
        except Exception as e:
            logger.error(f"Error obteniendo lotes por caducar: {e}")
            return pd.DataFrame()

    # ------------ KPIs / Dashboard ------------

    def get_model_kpis(self) -> Dict[str, Any]:
        """KPIs del último run (vista v_kpi_modelo)."""
        try:
            res = self.client.table("v_kpi_modelo").select("*").execute()
            if not res.data:
                return {}
            row = dict(res.data[0])
            for k in ("mape_prom", "mae_prom", "sesgo_prom"):
                if k in row and row[k] is not None:
                    row[k] = float(row[k])
            return row
        except Exception as e:
            logger.error(f"Error obteniendo KPIs del modelo: {e}")
            return {}

    def get_executive_summary(self) -> Dict[str, Any]:
        """Placeholder para resumen ejecutivo."""
        return {}

    def get_inventory_status(self) -> pd.DataFrame:
        """Placeholder para tablero de inventario."""
        return pd.DataFrame()

    def get_abc_analysis(self) -> pd.DataFrame:
        """Placeholder para análisis ABC."""
        return pd.DataFrame()

    # ------------ Utilidades ML / Calidad de datos ------------

    def check_data_quality(self, sku: str) -> Dict[str, Any]:
        """Chequeo de data mínima, completitud e outliers para un SKU."""
        try:
            sales_df = self.get_sales_data(sku=sku)
            if sales_df.empty:
                return {"sku": sku, "has_data": False, "message": "No hay ventas para el SKU"}

            total_days = (sales_df["fecha"].max() - sales_df["fecha"].min()).days + 1
            actual_days = len(sales_df)
            completeness = actual_days / total_days if total_days > 0 else 0.0

            Q1 = sales_df["unidades_vendidas"].quantile(0.25)
            Q3 = sales_df["unidades_vendidas"].quantile(0.75)
            iqr = Q3 - Q1
            outliers = sales_df[
                (sales_df["unidades_vendidas"] < Q1 - 1.5 * iqr)
                | (sales_df["unidades_vendidas"] > Q3 + 1.5 * iqr)
            ]
            outlier_pct = (len(outliers) / len(sales_df)) if len(sales_df) > 0 else 0.0

            sufficient_data = (
                actual_days >= self.settings.MIN_TRAINING_SAMPLES
                and completeness >= self.settings.MIN_DATA_COMPLETENESS
                and outlier_pct <= self.settings.MAX_OUTLIER_PERCENTAGE
            )

            return {
                "sku": sku,
                "has_data": True,
                "total_days": int(total_days),
                "actual_days": int(actual_days),
                "completeness": round(float(completeness), 3),
                "outlier_percentage": round(float(outlier_pct), 3),
                "mean_sales": round(float(sales_df["unidades_vendidas"].mean()), 2),
                "std_sales": round(float(sales_df["unidades_vendidas"].std() or 0), 2),
                "sufficient_for_training": bool(sufficient_data),
            }
        except Exception as e:
            logger.error(f"Error validando calidad de datos (sku={sku}): {e}")
            return {"sku": sku, "has_data": False, "error": str(e)}

    def get_forecast_comparison(
        self,
        sku: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """Comparación forecast vs reales en [start_date, end_date]."""
        try:
            if not end_date:
                end_date = date.today()
            if not start_date:
                start_date = end_date - timedelta(days=30)

            fcast = self.get_latest_forecast(sku=sku)
            if fcast.empty:
                return pd.DataFrame()

            fcast = fcast[
                (fcast["fecha_objetivo"] >= pd.Timestamp(start_date))
                & (fcast["fecha_objetivo"] <= pd.Timestamp(end_date))
            ][["fecha_objetivo", "unidades_pronosticadas"]].copy()

            sales = self.get_sales_data(sku=sku, start_date=start_date, end_date=end_date)
            if sales.empty:
                out = fcast.rename(columns={"fecha_objetivo": "fecha"})
                out["unidades_vendidas"] = np.nan
                out["error"] = np.nan
                out["error_pct"] = np.nan
                return out

            cmp = (
                pd.merge(
                    fcast,
                    sales[["fecha", "unidades_vendidas"]],
                    left_on="fecha_objetivo",
                    right_on="fecha",
                    how="left",
                )
                .drop(columns=["fecha"])
                .rename(columns={"fecha_objetivo": "fecha"})
            )

            cmp["error"] = cmp["unidades_vendidas"] - cmp["unidades_pronosticadas"]
            denom = cmp["unidades_vendidas"].replace({0: np.nan})
            cmp["error_pct"] = (cmp["error"] / denom) * 100.0
            return cmp
        except Exception as e:
            logger.error(f"Error comparando forecast vs reales: {e}")
            return pd.DataFrame()


# ------------ Singleton (inyectable en FastAPI) ------------

_db_instance: Optional[DataRepository] = None


def get_db() -> DataRepository:
    """Obtiene la instancia única del repositorio."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DataRepository()
    return _db_instance
