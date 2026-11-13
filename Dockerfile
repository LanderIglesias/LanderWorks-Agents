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
    git \
    curl \
    ca-certificates \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ── Escáneres del tech debt agent ────────────────────────────────────────────
# Versiones fijas y checksum SHA-256 verificado: son binarios que corren sobre
# código ajeno, así que no se aceptan descargas sin comprobar.
# Deben coincidir con GITLEAKS_VERSION, OSV_SCANNER_VERSION y SEMGREP_VERSION
# del código del agente.
RUN curl -fsSL -o /tmp/gitleaks.tgz https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_x64.tar.gz \
    && echo "ba6dbb656933921c775ee5a2d1c13a91046e7952e9d919f9bac4cec61d628e7d  /tmp/gitleaks.tgz" | sha256sum -c - \
    && tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks \
    && curl -fsSL -o /usr/local/bin/osv-scanner https://github.com/google/osv-scanner/releases/download/v2.7.1/osv-scanner_linux_amd64 \
    && echo "fb7dab19a8bd9bbe5c3189f09d4b7ee1820c9553a23bac202648a56efd2f6ee8  /usr/local/bin/osv-scanner" | sha256sum -c - \
    && chmod +x /usr/local/bin/osv-scanner \
    && rm /tmp/gitleaks.tgz

# semgrep en un venv aislado: sus pins (jsonschema, rich, etc.) chocan con los
# del monolito.
RUN python -m venv /opt/semgrep \
    && /opt/semgrep/bin/pip install --no-cache-dir semgrep==1.163.0 \
    && ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep

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
# Usuario sin privilegios: el agente clona y analiza código ajeno.
# backend/data guarda la SQLite del agente (TECH_DEBT_DB_PATH la puede mover).
RUN useradd -m app
COPY --chown=app:app . .
RUN mkdir -p backend/data && chown app:app backend/data
USER app

# ── Puerto ───────────────────────────────────────────────────────────────────
# Documenta que el contenedor escucha en el puerto 8000
# EXPOSE es solo documentación — el mapeo real se hace en docker-compose.yml
EXPOSE 8000

# ── Comando de arranque ──────────────────────────────────────────────────────
# El comando que se ejecuta cuando arranca el contenedor
# --host 0.0.0.0: escucha en todas las interfaces (necesario dentro de Docker)
# Sin esto, uvicorn solo escucha en localhost del contenedor y no es accesible
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]