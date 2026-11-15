# syntax=docker/dockerfile:1.7
# Container único: PostgreSQL 18 + aplicação (Uvicorn, 1 worker). As duas etapas usam a mesma
# base (postgres:18, Debian) para o Python e as bibliotecas do sistema serem as mesmas.

ARG POSTGRES_IMAGE=postgres:18
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.8

FROM ${UV_IMAGE} AS uv

# --- Etapa 1: dependências, verificações de qualidade e ambiente de produção -------------------
FROM ${POSTGRES_IMAGE} AS build

COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

WORKDIR /app

COPY .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv python install

# Dependências primeiro (camada reaproveitada enquanto o uv.lock não mudar).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

# Se qualquer verificação falhar, a imagem não é gerada.
RUN uv run --no-sync ruff check src tests \
    && uv run --no-sync ruff format --check src tests \
    && uv run --no-sync mypy \
    && uv run --no-sync lint-imports \
    && uv run --no-sync pytest -q -p no:cacheprovider

# Recria o ambiente só com o necessário em produção (projeto instalado como pacote, não editável).
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_COMPILE_BYTECODE=1 uv sync --frozen --no-dev --no-editable

# --- Etapa 2: imagem final --------------------------------------------------------------------
FROM ${POSTGRES_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /opt/python /opt/python
COPY --from=build /app/.venv /app/.venv

WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/odonto-entrypoint

# PGDATA fica num subdiretório do volume da imagem base (/var/lib/postgresql).
ENV PATH=/app/.venv/bin:$PATH \
    PGDATA=/var/lib/postgresql/odonto/pgdata \
    TZ=America/Sao_Paulo \
    DB_NAME=odonto \
    DB_USER=odonto \
    ODONTO_CONFIG=/app/config/odonto.yaml \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS -o /dev/null http://127.0.0.1:8080/health || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["odonto-entrypoint"]
