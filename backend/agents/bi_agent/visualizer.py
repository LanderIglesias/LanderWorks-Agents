"""
visualizer.py — Generador de gráficas para el BI Agent.

Recibe el resultado serializado de una pregunta (Series, DataFrame, scalar)
y decide qué tipo de gráfica tiene más sentido. Devuelve PNG en base64.

Tipos de gráfica según el resultado:
- Series con fechas como índice → línea temporal
- Series categórica (plan, country) → barras horizontales
- DataFrame con columna fecha + columnas numéricas → línea temporal
- DataFrame con columna categórica + columna numérica → barras
- Scalar o resultado sin estructura → None (sin gráfica)

El tema es dark para encajar con la UI del dashboard.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Sin ventanas — importante para servidores
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

# ── Paleta dark ───────────────────────────────────────────────────────────
BG = "#0b0d12"
SURFACE = "#131722"
BORDER = "#242938"
TEXT = "#e4e6eb"
TEXT_DIM = "#8b93a7"
ACCENT = "#3b82f6"
ACCENT2 = "#6366f1"
SUCCESS = "#10b981"
WARN = "#f59e0b"
ERROR = "#ef4444"

PALETTE = [ACCENT, SUCCESS, WARN, ERROR, ACCENT2, "#ec4899", "#a78bfa", "#34d399"]


# ── Configuración global de matplotlib ────────────────────────────────────
def _apply_dark_theme():
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": BG,
            "axes.edgecolor": BORDER,
            "axes.labelcolor": TEXT_DIM,
            "axes.titlecolor": TEXT,
            "axes.titlesize": 13,
            "axes.titleweight": "600",
            "axes.labelsize": 11,
            "xtick.color": TEXT_DIM,
            "ytick.color": TEXT_DIM,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "grid.color": BORDER,
            "grid.linewidth": 0.5,
            "legend.facecolor": SURFACE,
            "legend.edgecolor": BORDER,
            "legend.labelcolor": TEXT_DIM,
            "legend.fontsize": 10,
            "figure.dpi": 120,
            "savefig.dpi": 120,
            "savefig.facecolor": SURFACE,
            "text.color": TEXT,
            "font.family": "sans-serif",
            "font.size": 11,
        }
    )


# ── Lógica de decisión ────────────────────────────────────────────────────


def should_visualize(result: Any, question: str) -> bool:
    """
    Decide si tiene sentido generar una gráfica.
    Devuelve False para escalares, resultados vacíos o texto.
    """
    if result is None:
        return False

    if not isinstance(result, dict):
        return False

    result_type = result.get("type")

    if result_type == "series":
        items = result.get("total_items", 0)
        return 2 <= items <= 50

    if result_type == "dataframe":
        rows = result.get("total_rows", 0)
        cols = result.get("columns", [])
        # Necesita al menos 2 filas y al menos una columna numérica
        if rows < 2 or len(cols) < 2:
            return False
        return True

    return False


def generate_chart(result: dict, question: str, title: str = "") -> str | None:
    """
    Genera una gráfica y devuelve un string base64 del PNG.
    Devuelve None si no puede generar nada útil.
    """
    _apply_dark_theme()

    result_type = result.get("type")

    try:
        if result_type == "series":
            return _chart_series(result, question, title)
        elif result_type == "dataframe":
            return _chart_dataframe(result, question, title)
    except Exception:
        # Si la gráfica falla, no queremos romper la respuesta del agente
        # Silencio total — el usuario ve la respuesta sin gráfica
        return None
    finally:
        plt.close("all")

    return None


# ── Gráficas de Series ────────────────────────────────────────────────────


def _chart_series(result: dict, question: str, title: str) -> str | None:
    data = result.get("data", {})
    if not data:
        return None

    # Convertir a Series de pandas
    keys = list(data.keys())
    values = list(data.values())

    # Intentar parsear claves como fechas
    is_temporal = _looks_temporal(keys)

    if is_temporal:
        return _line_chart(keys, values, title or question[:60])
    else:
        return _bar_chart(keys, values, title or question[:60])


def _line_chart(keys: list, values: list, title: str) -> str | None:
    """Gráfica de línea para series temporales."""
    try:
        xs = pd.to_datetime(keys, errors="coerce")
        ys = [float(v) if v is not None else None for v in values]
    except Exception:
        return None

    valid = [(x, y) for x, y in zip(xs, ys, strict=False) if y is not None and not math.isnan(y)]
    if len(valid) < 2:
        return None

    xs_valid, ys_valid = zip(*valid, strict=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(
        xs_valid,
        ys_valid,
        color=ACCENT,
        linewidth=2,
        marker="o",
        markersize=4,
        markerfacecolor=ACCENT2,
    )
    ax.fill_between(xs_valid, ys_valid, alpha=0.12, color=ACCENT)

    ax.set_title(title, pad=12)
    ax.grid(True, axis="y", alpha=0.4)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", rotation=30)

    _format_yaxis(ax, max(ys_valid))

    plt.tight_layout()
    return _to_base64(fig)


def _bar_chart(keys: list, values: list, title: str) -> str | None:
    """Barras horizontales para categorías."""
    try:
        ys = [float(v) if v is not None else 0.0 for v in values]
    except Exception:
        return None

    if not ys:
        return None

    # Ordenar por valor descendente
    pairs = sorted(zip(keys, ys, strict=False), key=lambda x: x[1], reverse=True)
    keys_sorted, ys_sorted = zip(*pairs, strict=False)

    # Limitar a top 15 para no saturar
    keys_sorted = list(keys_sorted)[:15]
    ys_sorted = list(ys_sorted)[:15]

    fig_height = max(3.5, len(keys_sorted) * 0.42)
    fig, ax = plt.subplots(figsize=(8, fig_height))

    colors = [PALETTE[i % len(PALETTE)] for i in range(len(keys_sorted))]
    bars = ax.barh(keys_sorted, ys_sorted, color=colors, height=0.6, alpha=0.9)

    # Labels de valor al final de cada barra
    max_val = max(ys_sorted) if ys_sorted else 1
    for bar, val in zip(bars, ys_sorted, strict=False):
        label = _format_value(val)
        ax.text(
            bar.get_width() + max_val * 0.01,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            ha="left",
            fontsize=9,
            color=TEXT_DIM,
        )

    ax.set_title(title, pad=12)
    ax.set_xlim(0, max_val * 1.15)
    ax.grid(True, axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.invert_yaxis()  # mayor valor arriba

    _format_xaxis(ax, max_val)

    plt.tight_layout()
    return _to_base64(fig)


# ── Gráficas de DataFrames ────────────────────────────────────────────────


def _chart_dataframe(result: dict, question: str, title: str) -> str | None:
    rows = result.get("rows", [])
    cols = result.get("columns", [])

    if not rows or not cols:
        return None

    df = pd.DataFrame(rows)

    # Detectar columna de fecha y columnas numéricas
    date_col = _find_date_col(df)
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [
        c
        for c in df.columns
        if (df[c].dtype == object or pd.api.types.is_string_dtype(df[c]))
        and c != date_col
        and df[c].nunique() <= 30
    ]

    if date_col and num_cols:
        return _df_line_chart(df, date_col, num_cols, title or question[:60])

    if cat_cols and num_cols:
        return _df_bar_chart(df, cat_cols[0], num_cols[0], title or question[:60])

    if len(num_cols) >= 2 and not cat_cols and not date_col:
        # Tabla de números pura — barras con la primera columna numérica
        return _df_bar_chart(df, num_cols[0], num_cols[1], title or question[:60])

    return None


def _df_line_chart(df: pd.DataFrame, date_col: str, num_cols: list, title: str) -> str | None:
    """Líneas temporales desde DataFrame."""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col)

    if len(df) < 2:
        return None

    fig, ax = plt.subplots(figsize=(9, 4.5))

    for i, col in enumerate(num_cols[:4]):
        color = PALETTE[i % len(PALETTE)]
        ys = pd.to_numeric(df[col], errors="coerce")
        ax.plot(df[date_col], ys, color=color, linewidth=2, marker="o", markersize=3, label=col)
        ax.fill_between(df[date_col], ys, alpha=0.07, color=color)

    ax.set_title(title, pad=12)
    ax.grid(True, axis="y", alpha=0.4)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", rotation=30)

    if len(num_cols) > 1:
        ax.legend(loc="upper left")

    all_vals = pd.to_numeric(df[num_cols[0]], errors="coerce").dropna()
    if len(all_vals):
        _format_yaxis(ax, float(all_vals.max()))

    plt.tight_layout()
    return _to_base64(fig)


def _df_bar_chart(df: pd.DataFrame, cat_col: str, num_col: str, title: str) -> str | None:
    """Barras desde DataFrame."""
    df = df.copy()
    df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
    df = df.dropna(subset=[cat_col, num_col])
    df = df.sort_values(num_col, ascending=False).head(15)

    if len(df) == 0:
        return None

    keys = [str(k) for k in df[cat_col].tolist()]
    vals = df[num_col].tolist()

    return _bar_chart(keys, vals, title)


# ── Helpers ───────────────────────────────────────────────────────────────


def _looks_temporal(keys: list) -> bool:
    """Detecta si las claves parecen fechas."""
    sample = keys[:3]
    try:
        parsed = pd.to_datetime(sample, errors="coerce")
        return parsed.notna().all()
    except Exception:
        return False


def _find_date_col(df: pd.DataFrame) -> str | None:
    """Encuentra la primera columna que parece fecha."""
    for col in df.columns:
        if "date" in col.lower() or "time" in col.lower() or "month" in col.lower():
            try:
                sample = pd.to_datetime(df[col].dropna().head(3), errors="coerce")
                if sample.notna().all():
                    return col
            except Exception:
                pass
        # Intentar parsear como fecha directamente
        try:
            sample = pd.to_datetime(df[col].dropna().head(3), errors="coerce", format="mixed")
            if sample.notna().all() and len(df[col].unique()) > 2:
                return col
        except Exception:
            pass
    return None


def _format_value(val: float) -> str:
    """Formatea un número para labels de gráfica."""
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K" if val >= 10_000 else f"${val:,.0f}"
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:.1f}"


def _format_yaxis(ax, max_val: float):
    """Formatea el eje Y según la magnitud de los valores."""
    if max_val >= 1_000_000:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    elif max_val >= 1_000:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e3:.0f}K"))


def _format_xaxis(ax, max_val: float):
    """Formatea el eje X según la magnitud de los valores."""
    if max_val >= 1_000_000:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    elif max_val >= 1_000:
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e3:.0f}K"))


def _to_base64(fig) -> str:
    """Convierte una figura matplotlib a base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=SURFACE, edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
