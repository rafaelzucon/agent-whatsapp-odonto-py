#!/usr/bin/env bash
# PID 1 do container: inicia o PostgreSQL, aplica as migrações e sobe a aplicação.
# No SIGTERM/SIGINT para a aplicação e depois o banco. Se a aplicação cair sozinha, para o
# banco e sai com o mesmo código (o Docker reinicia o container, se configurado).
set -Eeuo pipefail

readonly BASE_DADOS=/var/lib/postgresql/odonto
readonly DIR_LOGS="${BASE_DADOS}/logs"
readonly LOG_BANCO="${DIR_LOGS}/postgresql.log"
export PGDATA="${PGDATA:-${BASE_DADOS}/pgdata}"
APP_PID=""

log() {
    local nivel=$1 mensagem=$2
    printf '{"momento": "%s", "nivel": "%s", "logger": "entrypoint", "mensagem": "%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)" "$nivel" "$mensagem"
}

falhar() {
    log CRITICAL "$1"
    exit 1
}

banco_rodando() {
    gosu postgres pg_ctl -D "$PGDATA" status >/dev/null 2>&1
}

finalizar() {
    local codigo=$?
    trap - EXIT TERM INT
    if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
        log INFO "parando a aplicação"
        kill -TERM "$APP_PID" 2>/dev/null || true
        wait "$APP_PID" 2>/dev/null || true
    fi
    if banco_rodando; then
        log INFO "parando o PostgreSQL"
        gosu postgres pg_ctl -D "$PGDATA" stop -m fast -w -t 30 >/dev/null || true
    fi
    log INFO "container encerrado (código ${codigo})"
    exit "$codigo"
}
trap finalizar EXIT
trap 'exit 0' TERM INT

# --- 1. Variáveis obrigatórias ----------------------------------------------------------------
[[ -n "${DB_PASSWORD:-}" ]] || falhar "DB_PASSWORD não definida. Rode ./odonto.sh setup e confira o .env."
DB_NAME="${DB_NAME:-odonto}"
DB_USER="${DB_USER:-odonto}"
readonly NOME_VALIDO='^[a-z_][a-z0-9_]{0,62}$'
[[ "$DB_NAME" =~ $NOME_VALIDO ]] || falhar "DB_NAME inválido: use letras minúsculas, números e _."
[[ "$DB_USER" =~ $NOME_VALIDO ]] || falhar "DB_USER inválido: use letras minúsculas, números e _."
[[ "$DB_USER" != "postgres" ]] || falhar "DB_USER não pode ser postgres."

# Dentro do container a aplicação sempre ouve em 0.0.0.0:8080. PORTA no .env escolhe só a porta
# publicada no host (veja odonto.sh e docker-compose.yml).
export HOST=0.0.0.0 PORTA=8080

# --- 2. Primeira execução: initdb -------------------------------------------------------------
mkdir -p "$PGDATA" "$DIR_LOGS"
chown postgres:postgres "$BASE_DADOS" "$PGDATA" "$DIR_LOGS"
chmod 700 "$PGDATA"

if [[ ! -s "$PGDATA/PG_VERSION" ]]; then
    log INFO "primeira execução: criando o cluster do PostgreSQL"
    gosu postgres initdb -D "$PGDATA" --username=postgres --encoding=UTF8 --locale=C.UTF-8 \
        --auth-local=peer --auth-host=scram-sha-256 >/dev/null
fi

# --- 3. PostgreSQL só em 127.0.0.1 ------------------------------------------------------------
log INFO "iniciando o PostgreSQL"
if ! gosu postgres pg_ctl -D "$PGDATA" -l "$LOG_BANCO" -w -t 90 \
    -o "-c listen_addresses=127.0.0.1 -c port=5432" start >/dev/null; then
    tail -n 30 "$LOG_BANCO" >&2 || true
    falhar "o PostgreSQL não iniciou (log acima e em ${LOG_BANCO})"
fi

# --- 4. Usuário e banco (idempotente; a senha é sempre sincronizada com o .env) ---------------
gosu postgres psql -X -q -v ON_ERROR_STOP=1 -d postgres \
    -v usuario="$DB_USER" -v senha="$DB_PASSWORD" -v banco="$DB_NAME" >/dev/null <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'usuario')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'usuario')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'usuario', :'senha')
\gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0',
              :'banco', :'usuario', 'UTF8')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'banco')
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'banco')
\gexec
SQL

# --- 5. Migrações -----------------------------------------------------------------------------
SENHA_URL="$(python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))')"
export DATABASE_URL="postgresql+psycopg://${DB_USER}:${SENHA_URL}@127.0.0.1:5432/${DB_NAME}"
unset SENHA_URL

log INFO "aplicando migrações (alembic upgrade head)"
(cd /app && gosu app alembic upgrade head) || falhar "as migrações falharam"

# --- 6. Aplicação -----------------------------------------------------------------------------
log INFO "iniciando a aplicação"
gosu app python -m odonto &
APP_PID=$!

codigo=0
wait "$APP_PID" || codigo=$?
APP_PID=""
log ERROR "a aplicação terminou sozinha (código ${codigo})"
exit "$codigo"
