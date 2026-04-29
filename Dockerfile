# ── Imagen base ──────────────────────────────────────────────────────────────
# Usamos Python 3.12 en su versión "slim" — más ligera que la completa
# "slim" elimina herramientas que no necesitamos (compiladores, docs, etc.)
# Esto hace la imagen más pequeña y más rápida de descargar
FROM python:3.12-slim

# ── Directorio de trabajo ────────────────────────────────────────────────────
# Todos los comandos siguientes se ejecutan dentro de /app
# Es la carpeta raíz de tu aplicación dentro del contenedor
WORKDIR /app

# ── Dependencias del sistema ─────────────────────────────────────────────────
# Instalamos librerías del sistema que necesita psycopg2 (el cliente PostgreSQL)
# --no-install-recommends: no instala paquetes extra que no necesitamos
# rm -rf /var/lib/apt/lists/*: limpia la caché de apt para reducir tamaño
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencias de Python ───────────────────────────────────────────────────
# Copiamos SOLO requirements.txt primero (antes del resto del código)
# Truco importante: Docker cachea capas. Si el requirements.txt no cambia,
# Docker reutiliza la capa de pip install sin reinstalar todo.
# Así los rebuilds son mucho más rápidos.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código de la aplicación ──────────────────────────────────────────────────
# Copiamos el resto del código DESPUÉS de las dependencias
# (así si cambias código pero no requirements, Docker reutiliza la capa anterior)
COPY . .

# ── Puerto ───────────────────────────────────────────────────────────────────
# Documenta que el contenedor escucha en el puerto 8000
# EXPOSE es solo documentación — el mapeo real se hace en docker-compose.yml
EXPOSE 8000

# ── Comando de arranque ──────────────────────────────────────────────────────
# El comando que se ejecuta cuando arranca el contenedor
# --host 0.0.0.0: escucha en todas las interfaces (necesario dentro de Docker)
# Sin esto, uvicorn solo escucha en localhost del contenedor y no es accesible
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]