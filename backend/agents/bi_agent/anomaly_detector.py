"""
anomaly_detector.py — Motor estadístico de detección de anomalías (v4).

Fix crítico v4:
En pandas 2.0+, las columnas de texto pueden tener dtype 'str' (StringDtype)
en vez del clásico 'object'. La condición anterior `df[c].dtype == 'object'`
fallaba para todas ellas, dejando categorical_cols = [] y cero detecciones.

Fix: usar pd.api.types.is_string_dtype() que funciona con ambos tipos.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np  # noqa: F401
import pandas as pd

# ── Configuración ────────────────────────────────────────────────────────

Z_THRESHOLD = 2.0
SEGMENT_Z_THRESHOLD = 1.3
SEGMENT_RATIO_THRESHOLD = 1.5
PCT_CHANGE_THRESHOLD = 80.0
WARMUP_DAYS = 7
MIN_BASE_FOR_PCT_CHANGE = 100.0
CONCENTRATION_THRESHOLD = 0.35
DISPARITY_RATIO_THRESHOLD = 1.8


def make_anomaly(type: str, severity: str, metric: str, details: dict) -> dict:
    return {"type": type, "severity": severity, "metric": metric, "details": details}


def _is_categorical(series: pd.Series, max_unique: int = 30) -> bool:
    """
    Detecta si una columna es categórica. Funciona con pandas 2.0+
    donde las strings pueden ser 'object' o 'StringDtype'.
    """
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        nu = series.nunique()
        return 2 <= nu <= max_unique
    return False


# ── Detección 1: outliers genéricos ─────────────────────────────────────


def detect_outliers(series: pd.Series, metric_name: str = "value") -> list[dict]:
    series = series.dropna()
    if len(series) < 10:
        return []

    mean = float(series.mean())
    std = float(series.std())
    if std == 0 or math.isnan(std):
        return []

    anomalies = []
    for idx, value in series.items():
        if value is None or pd.isna(value):
            continue
        z = (float(value) - mean) / std
        if abs(z) > Z_THRESHOLD:
            severity = "high" if abs(z) > 3 else "medium" if abs(z) > 2.5 else "low"
            anomalies.append(
                make_anomaly(
                    type="outlier",
                    severity=severity,
                    metric=metric_name,
                    details={
                        "index": str(idx),
                        "value": round(float(value), 2),
                        "z_score": round(z, 2),
                        "mean": round(mean, 2),
                        "std": round(std, 2),
                        "direction": "above" if z > 0 else "below",
                    },
                )
            )
    return anomalies


# ── Detección 2: spikes temporales ──────────────────────────────────────


def detect_time_series_spikes(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    group_col: str | None = None,
) -> list[dict]:
    if date_col not in df.columns or value_col not in df.columns:
        return []

    anomalies = []

    def _check_series(series: pd.Series, label: str):
        if len(series) < 3:
            return

        if len(series) > WARMUP_DAYS:
            series = series.iloc[WARMUP_DAYS:]
            if len(series) < 3:
                return

        for i in range(1, len(series)):
            prev = float(series.iloc[i - 1])
            curr = float(series.iloc[i])
            idx = series.index[i]

            if abs(prev) < MIN_BASE_FOR_PCT_CHANGE:
                continue
            if math.isnan(prev) or math.isnan(curr) or prev == 0:
                continue

            pct = ((curr - prev) / abs(prev)) * 100
            if math.isinf(pct):
                continue

            if abs(pct) > PCT_CHANGE_THRESHOLD:
                severity = "high" if abs(pct) > 150 else "medium"
                anomalies.append(
                    make_anomaly(
                        type="spike",
                        severity=severity,
                        metric=f"{value_col}" + (f" ({label})" if label else ""),
                        details={
                            "date": str(idx),
                            "pct_change": round(pct, 1),
                            "previous_value": round(prev, 2),
                            "current_value": round(curr, 2),
                            "direction": "increase" if pct > 0 else "decrease",
                        },
                    )
                )

    df_clean = df.copy()
    df_clean[date_col] = pd.to_datetime(df_clean[date_col], errors="coerce")
    df_clean = df_clean.dropna(subset=[date_col, value_col])

    if group_col and group_col in df.columns:
        for group_name, group_df in df_clean.groupby(group_col):
            daily = group_df.groupby(date_col)[value_col].sum().sort_index()
            _check_series(daily, str(group_name))
    else:
        daily = df_clean.groupby(date_col)[value_col].sum().sort_index()
        _check_series(daily, "")

    return anomalies


# ── Detección 3: segmentos desviados ────────────────────────────────────


def detect_segment_anomalies(
    df: pd.DataFrame,
    segment_col: str,
    metric_col: str,
    metric_type: str = "sum",
) -> list[dict]:
    if segment_col not in df.columns or metric_col not in df.columns:
        return []

    if metric_type == "sum":
        agg = df.groupby(segment_col)[metric_col].sum()
    elif metric_type == "mean":
        agg = df.groupby(segment_col)[metric_col].mean()
    elif metric_type == "count":
        agg = df.groupby(segment_col)[metric_col].count()
    elif metric_type == "nunique":
        agg = df.groupby(segment_col)[metric_col].nunique()
    else:
        return []

    if len(agg) < 3:
        return []

    anomalies = []

    if len(agg) <= 5:
        # Para pocas categorías: ratio vs media del resto
        for segment in agg.index:
            value = float(agg.loc[segment])
            if pd.isna(value):
                continue
            rest_mean = float(agg.drop(segment).mean())
            if rest_mean == 0 or math.isnan(rest_mean):
                continue
            ratio = value / rest_mean
            if ratio >= SEGMENT_RATIO_THRESHOLD or (
                ratio > 0 and ratio <= 1 / SEGMENT_RATIO_THRESHOLD
            ):
                severity = "high" if ratio >= 2.5 or ratio <= 0.4 else "medium"
                anomalies.append(
                    make_anomaly(
                        type="segment",
                        severity=severity,
                        metric=f"{metric_type}({metric_col}) by {segment_col}",
                        details={
                            "segment": str(segment),
                            "value": round(value, 2),
                            "rest_mean": round(rest_mean, 2),
                            "ratio": round(ratio, 2),
                            "direction": "above" if ratio > 1 else "below",
                        },
                    )
                )
    else:
        # Para más categorías: z-score
        mean = float(agg.mean())
        std = float(agg.std())
        if std == 0 or math.isnan(std):
            return []
        for segment in agg.index:
            value = float(agg.loc[segment])
            if pd.isna(value):
                continue
            z = (value - mean) / std
            if abs(z) > SEGMENT_Z_THRESHOLD:
                severity = "high" if abs(z) > 2 else "medium"
                anomalies.append(
                    make_anomaly(
                        type="segment",
                        severity=severity,
                        metric=f"{metric_type}({metric_col}) by {segment_col}",
                        details={
                            "segment": str(segment),
                            "value": round(value, 2),
                            "mean_across_segments": round(mean, 2),
                            "z_score": round(z, 2),
                            "direction": "above" if z > 0 else "below",
                        },
                    )
                )

    return anomalies


# ── Detección 4: concentración ──────────────────────────────────────────


def detect_concentration(
    df: pd.DataFrame,
    segment_col: str,
    metric_col: str | None = None,
    metric_type: str = "count",
) -> list[dict]:
    if segment_col not in df.columns:
        return []

    if metric_col is None:
        agg = df[segment_col].value_counts()
    elif metric_col not in df.columns:
        return []
    else:
        if metric_type == "sum":
            agg = df.groupby(segment_col)[metric_col].sum()
        elif metric_type == "nunique":
            agg = df.groupby(segment_col)[metric_col].nunique()
        else:
            return []

    total = float(agg.sum())
    if total == 0:
        return []

    anomalies = []
    for segment, value in agg.items():
        pct = float(value) / total
        if pct > CONCENTRATION_THRESHOLD:
            severity = "high" if pct > 0.55 else "medium"
            metric_name = "count" if metric_col is None else f"{metric_type}({metric_col})"
            anomalies.append(
                make_anomaly(
                    type="concentration",
                    severity=severity,
                    metric=f"{metric_name} concentration by {segment_col}",
                    details={
                        "segment": str(segment),
                        "value": round(float(value), 2),
                        "total": round(total, 2),
                        "pct_of_total": round(pct * 100, 1),
                    },
                )
            )
    return anomalies


# ── Detección 5: disparidad top/bottom ──────────────────────────────────


def detect_disparity(
    df: pd.DataFrame,
    segment_col: str,
    metric_col: str,
    metric_type: str = "sum",
) -> list[dict]:
    if segment_col not in df.columns or metric_col not in df.columns:
        return []

    if metric_type == "sum":
        agg = df.groupby(segment_col)[metric_col].sum()
    elif metric_type == "mean":
        agg = df.groupby(segment_col)[metric_col].mean()
    elif metric_type == "count":
        agg = df.groupby(segment_col)[metric_col].count()
    elif metric_type == "nunique":
        agg = df.groupby(segment_col)[metric_col].nunique()
    else:
        return []

    if len(agg) < 2:
        return []

    agg_sorted = agg.sort_values(ascending=False)
    top_value = float(agg_sorted.iloc[0])
    bottom_value = float(agg_sorted.iloc[-1])

    if bottom_value <= 0 or math.isnan(top_value) or math.isnan(bottom_value):
        return []

    ratio = top_value / bottom_value
    if ratio >= DISPARITY_RATIO_THRESHOLD:
        severity = "high" if ratio >= 5 else "medium"
        return [
            make_anomaly(
                type="disparity",
                severity=severity,
                metric=f"{metric_type}({metric_col}) by {segment_col}",
                details={
                    "top_segment": str(agg_sorted.index[0]),
                    "top_value": round(top_value, 2),
                    "bottom_segment": str(agg_sorted.index[-1]),
                    "bottom_value": round(bottom_value, 2),
                    "ratio": round(ratio, 1),
                },
            )
        ]
    return []


# ── Detección 6: churn disparity ─────────────────────────────────────────


def detect_churn_disparity(
    df: pd.DataFrame,
    segment_col: str,
    id_col: str,
) -> list[dict]:
    if "status" not in df.columns:
        return []
    if segment_col not in df.columns or id_col not in df.columns:
        return []

    churned = df[df["status"] == "churned"].groupby(segment_col)[id_col].nunique()
    total = df.groupby(segment_col)[id_col].nunique()
    rate = (churned.reindex(total.index, fill_value=0) / total * 100).fillna(0)

    if len(rate) < 2:
        return []

    top_value = float(rate.max())
    bottom_value = float(rate.min())

    if top_value == 0:
        return []

    effective_bottom = max(bottom_value, 1.0)
    ratio = top_value / effective_bottom

    if ratio >= DISPARITY_RATIO_THRESHOLD:
        severity = "high" if ratio >= 3 else "medium"
        return [
            make_anomaly(
                type="churn_disparity",
                severity=severity,
                metric=f"churn rate by {segment_col}",
                details={
                    "top_segment": str(rate.idxmax()),
                    "top_churn_pct": round(top_value, 1),
                    "bottom_segment": str(rate.idxmin()),
                    "bottom_churn_pct": round(bottom_value, 1),
                    "ratio": round(ratio, 1),
                },
            )
        ]
    return []


# ── Análisis in-flight de resultado ─────────────────────────────────────


def analyze_result(result: Any, metric_name: str = "result") -> list[dict]:
    if result is None or not isinstance(result, dict):
        return []

    if result.get("type") == "series":
        data = result.get("data", {})
        numeric_items = {}
        for k, v in data.items():
            if v is None:
                continue
            try:
                numeric_items[k] = float(v)
            except (TypeError, ValueError):
                continue
        if len(numeric_items) < 10:
            return []
        series = pd.Series(numeric_items)
        return detect_outliers(series, metric_name)

    if result.get("type") == "dataframe":
        rows = result.get("rows", [])
        if len(rows) < 10:
            return []
        df = pd.DataFrame(rows)
        anomalies = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                col_anomalies = detect_outliers(df[col], col)
                anomalies.extend(col_anomalies)
        return anomalies[:5]

    return []


# ── Scan proactivo ──────────────────────────────────────────────────────


def scan_dataset(
    df: pd.DataFrame,
    date_col: str | None = None,
    id_col: str | None = None,
) -> list[dict]:
    """
    Escaneo proactivo del dataset completo.

    Fix v4: usa _is_categorical() en vez de df[c].dtype == 'object'
    para compatibilidad con pandas 2.0+ donde strings pueden ser StringDtype.
    """
    anomalies = []

    # Auto-detección de columnas
    if date_col is None:
        for col in df.columns:
            if "date" in col.lower() or "time" in col.lower():
                date_col = col
                break

    # ── Fix clave: usar _is_categorical() en vez de .dtype == 'object' ──
    numeric_cols = [
        c
        for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c]) and not c.lower().endswith("_id")
    ]
    categorical_cols = [
        c
        for c in df.columns
        if _is_categorical(df[c]) and not c.lower().endswith("_id") and "date" not in c.lower()
    ]

    # 1. Spikes temporales
    if date_col:
        for metric in numeric_cols[:3]:
            spikes = detect_time_series_spikes(df, date_col, metric)
            anomalies.extend([s for s in spikes if s["severity"] in ("high", "medium")][:2])

    # 2. Segmentos desviados
    for segment_col in categorical_cols[:4]:
        for metric_col in numeric_cols[:2]:
            seg = detect_segment_anomalies(df, segment_col, metric_col, "sum")
            anomalies.extend(seg[:3])

    # 3. Concentración
    for segment_col in categorical_cols[:4]:
        if id_col and id_col in df.columns:
            conc = detect_concentration(df, segment_col, id_col, "nunique")
        else:
            conc = detect_concentration(df, segment_col)
        anomalies.extend(conc[:2])

    # 4. Disparidad
    for segment_col in categorical_cols[:3]:
        for metric_col in numeric_cols[:2]:
            disp = detect_disparity(df, segment_col, metric_col, "sum")
            anomalies.extend(disp)

    # 5. Churn disparity
    if "status" in df.columns and id_col:
        for segment_col in categorical_cols:
            if segment_col == "status":
                continue
            churn_disp = detect_churn_disparity(df, segment_col, id_col)
            anomalies.extend(churn_disp)

    # Deduplicar
    seen = set()
    unique = []
    for a in anomalies:
        key = (
            a["type"],
            a["metric"],
            str(a["details"].get("segment", a["details"].get("top_segment", ""))),
        )
        if key not in seen:
            seen.add(key)
            unique.append(a)

    return unique
