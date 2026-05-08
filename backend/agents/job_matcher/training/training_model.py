"""
Fase 2: Entrenamiento del modelo sklearn.

Que hace este archivo:
- Carga el CSV generado por Claude en la Fase 1
- Entrena un GradientBoostingRegressor para predecir el score
- Evalua con cross-validation
- Guarda el modelo entrenado en un archivo .pkl

Por que GradientBoosting y no RandomForest?
GradientBoosting es mejor para regresion con features mixtas
y datasets pequeños. Aprende de sus errores iterativamente.
RandomForest seria igualmente valido pero GradientBoosting
suele ganar en benchmarks con menos de 10.000 filas.

Por que regresion y no clasificacion?
Porque el output es un score continuo 0-100, no una categoria.
Queremos predecir "78" no "bueno/malo".
"""

from __future__ import annotations

import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split

# ── 1. Carga de datos ─────────────────────────────────────────────────────────
DATA_PATH = Path("backend/agents/job_matcher/training/training_data.csv")
MODEL_PATH = Path("backend/agents/job_matcher/training/model.pkl")

df = pd.read_csv(DATA_PATH)

FEATURES = [
    "cobertura_tech",
    "n_techs_match",
    "diff_nivel",
    "diff_anos",
    "tiene_cloud_si_pide",
    "falta_cloud",
    "tiene_docker_si_pide",
    "falta_docker",
    "tiene_sql_si_pide",
    "falta_sql",
    "ingles_ok",
    "llm_match",
    "n_proyectos",
    "anos_experiencia",
]

X = df[FEATURES]
y = df["score_claude"]

print("=" * 50)
print("DATASET")
print("=" * 50)
print(f"Total muestras: {len(df)}")
print(f"Features: {len(FEATURES)}")
print(f"Score medio: {y.mean():.1f}")
print(f"Score std: {y.std():.1f}")
print(f"Rango: {y.min():.0f} - {y.max():.0f}")

# ── 2. Train/test split ───────────────────────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# ── 3. Entrenamiento ──────────────────────────────────────────────────────────
modelo = GradientBoostingRegressor(
    n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, random_state=42
)
modelo.fit(X_train, y_train)

# ── 4. Evaluacion ─────────────────────────────────────────────────────────────
y_pred = modelo.predict(X_test)

mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print("\n" + "=" * 50)
print("EVALUACION EN TEST")
print("=" * 50)
print(f"MAE: {mae:.2f} puntos")
print(f"R²: {r2:.3f}")
print(f"(El modelo se equivoca de media {mae:.1f} puntos sobre 100)")

# ── 5. Cross-validation ───────────────────────────────────────────────────────
cv_scores = cross_val_score(modelo, X, y, cv=5, scoring="neg_mean_absolute_error")
cv_mae = -cv_scores.mean()

print("\n" + "=" * 50)
print("CROSS-VALIDATION (5 folds)")
print("=" * 50)
print(f"MAE medio: {cv_mae:.2f} puntos")
print(f"Std: {-cv_scores.std():.2f}")
print(f"Por fold: {[-round(s, 2) for s in cv_scores]}")

# ── 6. Feature importance ─────────────────────────────────────────────────────
importancias = pd.Series(modelo.feature_importances_, index=FEATURES).sort_values(ascending=False)

print("\n" + "=" * 50)
print("FEATURE IMPORTANCE")
print("=" * 50)
for feature, imp in importancias.items():
    barra = "█" * int(imp * 50)
    print(f"{feature:<25} {barra} {imp:.3f}")

# ── 7. Ejemplos de prediccion ─────────────────────────────────────────────────
print("\n" + "=" * 50)
print("EJEMPLOS DE PREDICCION")
print("=" * 50)

ejemplos = pd.DataFrame(
    [
        {  # Candidato fuerte para oferta junior
            "cobertura_tech": 0.8,
            "n_techs_match": 6,
            "diff_nivel": 1,
            "diff_anos": 3.0,
            "tiene_cloud_si_pide": 1,
            "falta_cloud": 0,
            "tiene_docker_si_pide": 1,
            "falta_docker": 0,
            "tiene_sql_si_pide": 1,
            "falta_sql": 0,
            "ingles_ok": 1,
            "llm_match": 1,
            "n_proyectos": 6,
            "anos_experiencia": 3.5,
        },
        {  # Candidato junior para oferta senior
            "cobertura_tech": 0.2,
            "n_techs_match": 2,
            "diff_nivel": -2,
            "diff_anos": -4.0,
            "tiene_cloud_si_pide": 0,
            "falta_cloud": 1,
            "tiene_docker_si_pide": 0,
            "falta_docker": 1,
            "tiene_sql_si_pide": 0,
            "falta_sql": 1,
            "ingles_ok": 0,
            "llm_match": 0,
            "n_proyectos": 1,
            "anos_experiencia": 0.5,
        },
        {  # Encaje medio
            "cobertura_tech": 0.5,
            "n_techs_match": 4,
            "diff_nivel": 0,
            "diff_anos": 0.5,
            "tiene_cloud_si_pide": 1,
            "falta_cloud": 0,
            "tiene_docker_si_pide": 0,
            "falta_docker": 1,
            "tiene_sql_si_pide": 1,
            "falta_sql": 0,
            "ingles_ok": 1,
            "llm_match": 1,
            "n_proyectos": 3,
            "anos_experiencia": 2.0,
        },
    ]
)

descripciones = [
    "Candidato fuerte para oferta junior",
    "Junior aplicando a senior",
    "Encaje medio con gaps de Docker",
]

predicciones = modelo.predict(ejemplos)
for desc, pred in zip(descripciones, predicciones, strict=False):
    print(f"{desc}: {pred:.0f}/100")

# ── 8. Visualizacion ──────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Real vs predicho
axes[0].scatter(y_test, y_pred, alpha=0.5, color="steelblue")
axes[0].plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], "r--", linewidth=2)
axes[0].set_xlabel("Score real (Claude)")
axes[0].set_ylabel("Score predicho (modelo)")
axes[0].set_title(f"Real vs Predicho — R²={r2:.3f}")

# Feature importance
importancias.head(8).plot(kind="barh", ax=axes[1], color="steelblue")
axes[1].set_title("Variables mas importantes")
axes[1].set_xlabel("Importancia")

plt.tight_layout()
plt.savefig("backend/agents/job_matcher/training/evaluacion_modelo.png")
print("\nGrafica guardada")

# ── 9. Guardamos el modelo ────────────────────────────────────────────────────
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(MODEL_PATH, "wb") as f:
    pickle.dump({"modelo": modelo, "features": FEATURES, "mae_cv": cv_mae, "r2_test": r2}, f)

print(f"\nModelo guardado en {MODEL_PATH}")
print("\nListo para la Fase 3 — construccion del agente completo")
