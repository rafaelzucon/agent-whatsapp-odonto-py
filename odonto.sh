#!/usr/bin/env bash
# Operação do agente no Linux (container único: aplicação + PostgreSQL).
# Uso: ./odonto.sh <comando> [argumentos]   (./odonto.sh ajuda lista os comandos)
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"

readonly NOME="agent-whatsapp-odonto-py"
readonly IMAGEM="${NOME}:latest"
readonly VOLUME="${NOME}-dados"
readonly ARQUIVO_ENV=".env"
readonly DIR_BACKUPS="backups"
readonly ESPERA_SAUDAVEL_SEGUNDOS=180

if [[ -t 1 ]]; then
    VERMELHO=$'\e[31m' VERDE=$'\e[32m' AMARELO=$'\e[33m' NEGRITO=$'\e[1m' NORMAL=$'\e[0m'
else
    VERMELHO="" VERDE="" AMARELO="" NEGRITO="" NORMAL=""
fi

info() { printf '%s\n' "${VERDE}==>${NORMAL} $*"; }
aviso() { printf '%s\n' "${AMARELO}aviso:${NORMAL} $*" >&2; }
erro() {
    printf '%s\n' "${VERMELHO}erro:${NORMAL} $*" >&2
    exit 1
}

exigir_docker() {
    command -v docker >/dev/null 2>&1 || erro "Docker não encontrado. Instale: https://docs.docker.com/engine/install/"
    docker info >/dev/null 2>&1 || erro "Sem acesso ao Docker. O serviço está rodando? Seu usuário está no grupo docker?"
}

valor_env() {
    [[ -f "$ARQUIVO_ENV" ]] || return 0
    grep -E "^$1=" "$ARQUIVO_ENV" | tail -n 1 | cut -d= -f2- || true
}

container_existe() { docker container inspect "$NOME" >/dev/null 2>&1; }
container_rodando() { [[ "$(docker container inspect -f '{{.State.Running}}' "$NOME" 2>/dev/null)" == "true" ]]; }
imagem_existe() { docker image inspect "$IMAGEM" >/dev/null 2>&1; }

exigir_rodando() {
    container_rodando || erro "O container não está rodando. Use: ./odonto.sh start"
}

confirmar() {
    local pergunta=$1 esperado=$2 resposta
    read -r -p "${pergunta} Digite ${NEGRITO}${esperado}${NORMAL} para confirmar: " resposta
    [[ "$resposta" == "$esperado" ]] || erro "Operação cancelada."
}

# --- Geração de segredos (sem depender de Python no host) -----------------------------------
chave_base64() { head -c 32 /dev/urandom | base64 | tr -d '\n'; }
token_hex() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

preencher_se_vazio() {
    local chave=$1 valor=$2 temporario
    if grep -qE "^${chave}=.+" "$ARQUIVO_ENV"; then
        return 0
    fi
    if grep -qE "^${chave}=$" "$ARQUIVO_ENV"; then
        temporario="$(mktemp "${ARQUIVO_ENV}.XXXXXX")"
        awk -v chave="$chave" -v valor="$valor" \
            '$0 == chave "=" { print chave "=" valor; next } { print }' \
            "$ARQUIVO_ENV" >"$temporario"
        mv "$temporario" "$ARQUIVO_ENV"
    else
        printf '%s=%s\n' "$chave" "$valor" >>"$ARQUIVO_ENV"
    fi
    info "${chave} gerado"
}

# --- Comandos ----------------------------------------------------------------------------------
cmd_setup() {
    umask 077
    if [[ ! -f "$ARQUIVO_ENV" ]]; then
        [[ -f .env.example ]] || erro ".env.example não encontrado."
        cp .env.example "$ARQUIVO_ENV"
        info "${ARQUIVO_ENV} criado a partir do .env.example"
    fi
    preencher_se_vazio DB_PASSWORD "$(token_hex)"
    preencher_se_vazio CHAVE_CRIPTOGRAFIA "$(chave_base64)"
    preencher_se_vazio CHAVE_HMAC_DOCUMENTO "$(chave_base64)"
    preencher_se_vazio ADMIN_TOKEN "$(token_hex)"
    preencher_se_vazio WHATSAPP_VERIFY_TOKEN "$(token_hex)"
    chmod 600 "$ARQUIVO_ENV"
    cat <<EOF

${NEGRITO}Próximos passos:${NORMAL}
  1. Edite o ${ARQUIVO_ENV} e preencha WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN,
     WHATSAPP_APP_SECRET, CONSULTORIO_WHATSAPP_NOTIFICACAO, ANTHROPIC_API_KEY e OPENAI_API_KEY.
  2. Guarde uma cópia de CHAVE_CRIPTOGRAFIA e CHAVE_HMAC_DOCUMENTO fora deste servidor.
  3. Ajuste config/odonto.yaml (nome, endereço, horários, feriados).
  4. ./odonto.sh start
EOF
}

validar_env() {
    [[ -f "$ARQUIVO_ENV" ]] || erro "${ARQUIVO_ENV} não encontrado. Rode primeiro: ./odonto.sh setup"
    local faltando=() variavel
    for variavel in DB_PASSWORD CHAVE_CRIPTOGRAFIA CHAVE_HMAC_DOCUMENTO; do
        [[ -n "$(valor_env "$variavel")" ]] || faltando+=("$variavel")
    done
    ((${#faltando[@]} == 0)) || erro "Preencha no ${ARQUIVO_ENV}: ${faltando[*]} (./odonto.sh setup gera)."
    [[ "$(valor_env CHAVE_CRIPTOGRAFIA)" != "$(valor_env CHAVE_HMAC_DOCUMENTO)" ]] ||
        erro "CHAVE_CRIPTOGRAFIA e CHAVE_HMAC_DOCUMENTO devem ser diferentes."
    if grep -qE '^[A-Z_]+=.*[[:space:]]#' "$ARQUIVO_ENV"; then
        aviso "há comentário na mesma linha de um valor no ${ARQUIVO_ENV}; o Docker lê isso como parte do valor."
    fi
    for variavel in WHATSAPP_PHONE_NUMBER_ID WHATSAPP_ACCESS_TOKEN WHATSAPP_APP_SECRET ANTHROPIC_API_KEY; do
        [[ -n "$(valor_env "$variavel")" ]] || aviso "${variavel} vazio no ${ARQUIVO_ENV} (a aplicação sobe com recursos limitados)."
    done
    [[ -f config/odonto.yaml ]] || erro "config/odonto.yaml não encontrado."
}

cmd_build() {
    exigir_docker
    info "construindo a imagem ${IMAGEM} (inclui lint, mypy e testes)"
    DOCKER_BUILDKIT=1 docker build -t "$IMAGEM" .
}

esperar_saudavel() {
    local inicio=$SECONDS estado
    info "aguardando o container ficar saudável (até ${ESPERA_SAUDAVEL_SEGUNDOS}s)"
    while ((SECONDS - inicio < ESPERA_SAUDAVEL_SEGUNDOS)); do
        estado="$(docker container inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$NOME" 2>/dev/null || echo ausente)"
        case "$estado" in
            healthy)
                info "pronto: http://localhost:$(valor_env PORTA | grep . || echo 8080)/health"
                return 0
                ;;
            unhealthy | exited | dead | ausente)
                docker logs --tail 40 "$NOME" >&2 || true
                erro "o container não ficou saudável (estado: ${estado}). Veja: ./odonto.sh logs"
                ;;
        esac
        sleep 3
    done
    docker logs --tail 40 "$NOME" >&2 || true
    erro "tempo esgotado esperando o container. Veja: ./odonto.sh logs"
}

criar_container() {
    local porta
    porta="$(valor_env PORTA)"
    porta="${porta:-8080}"
    [[ "$porta" =~ ^[0-9]+$ ]] || erro "PORTA inválida no ${ARQUIVO_ENV}: ${porta}"
    info "criando o container ${NOME} (porta ${porta})"
    docker run -d \
        --name "$NOME" \
        --env-file "$ARQUIVO_ENV" \
        -p "${porta}:8080" \
        -v "${VOLUME}:/var/lib/postgresql" \
        -v "$PWD/config:/app/config:ro" \
        --restart unless-stopped \
        --stop-timeout 60 \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=5 \
        "$IMAGEM" >/dev/null
}

cmd_start() {
    exigir_docker
    validar_env
    if container_rodando; then
        info "o container já está rodando"
        return 0
    fi
    imagem_existe || cmd_build
    if container_existe; then
        info "iniciando o container existente"
        docker start "$NOME" >/dev/null
    else
        criar_container
    fi
    esperar_saudavel
}

cmd_stop() {
    exigir_docker
    if container_rodando; then
        info "parando o container (até 60s para encerrar com segurança)"
        docker stop -t 60 "$NOME" >/dev/null
    else
        info "o container não está rodando"
    fi
}

cmd_restart() {
    # Recria o container para aplicar mudanças no .env e no config/odonto.yaml (os dados ficam
    # no volume e não são afetados).
    exigir_docker
    validar_env
    imagem_existe || cmd_build
    if container_existe; then
        cmd_stop
        docker rm "$NOME" >/dev/null
    fi
    criar_container
    esperar_saudavel
}

cmd_status() {
    exigir_docker
    if ! container_existe; then
        info "container não criado. Use: ./odonto.sh start"
        return 0
    fi
    docker ps -a --filter "name=^${NOME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    if container_rodando; then
        printf '\n'
        docker exec "$NOME" curl -sS http://127.0.0.1:8080/health || aviso "/health não respondeu"
        printf '\n'
    fi
    docker volume inspect "$VOLUME" >/dev/null 2>&1 && info "volume de dados: ${VOLUME}"
}

cmd_logs() {
    exigir_docker
    container_existe || erro "container não criado."
    case "${1:-app}" in
        app) docker logs -f --tail 200 "$NOME" ;;
        db | banco) docker exec "$NOME" tail -n 200 -f /var/lib/postgresql/odonto/logs/postgresql.log ;;
        *) erro "use: ./odonto.sh logs [app|db]" ;;
    esac
}

cmd_agenda() {
    exigir_docker
    exigir_rodando
    local dia=${1:-$(date +%F)}
    [[ "$dia" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || erro "data inválida: use AAAA-MM-DD."
    # Roda dentro do container: o ADMIN_TOKEN já está no ambiente dele e o Python também.
    docker exec -i "$NOME" python - "$dia" <<'PY'
import json, os, sys, urllib.error, urllib.request
from datetime import datetime

dia = sys.argv[1]
token = os.environ.get("ADMIN_TOKEN", "")
if not token:
    sys.exit("ADMIN_TOKEN vazio no .env: a API da recepção está fechada.")
pedido = urllib.request.Request(
    f"http://127.0.0.1:8080/api/agenda?inicio={dia}&fim={dia}",
    headers={"X-Admin-Token": token},
)
try:
    with urllib.request.urlopen(pedido, timeout=15) as resposta:
        agenda = json.load(resposta)
except urllib.error.HTTPError as erro:
    sys.exit(f"API respondeu {erro.code}: {erro.read().decode()}")

def hora(valor: str) -> str:
    return datetime.fromisoformat(valor).astimezone().strftime("%H:%M")

print(f"Agenda de {datetime.fromisoformat(dia):%d/%m/%Y}\n")
consultas = sorted(agenda["consultas"], key=lambda c: c["inicio"])
if not consultas:
    print("  Nenhuma consulta.")
for c in consultas:
    print(
        f"  {hora(c['inicio'])}-{hora(c['fim'])}  {c['status']:<10} {c['prioridade']:<10} "
        f"{c['nome_paciente'] or '?':<30} {c['problema'] or ''}"
    )
for b in agenda["bloqueios"]:
    print(f"  {hora(b['inicio'])}-{hora(b['fim'])}  BLOQUEIO   {b['motivo']}")
livres = [hora(h) for h in agenda["horarios_livres"]]
print(f"\n  Horários livres ({len(livres)}): {', '.join(livres) or 'nenhum'}")
PY
}

cmd_backup() {
    exigir_docker
    exigir_rodando
    mkdir -p "$DIR_BACKUPS"
    chmod 700 "$DIR_BACKUPS"
    local arquivo
    arquivo="${DIR_BACKUPS}/odonto-$(date +%Y%m%d-%H%M%S).dump"
    info "gerando ${arquivo}"
    if ! docker exec -u postgres "$NOME" sh -c 'pg_dump -Fc -d "$DB_NAME"' >"${arquivo}.parcial"; then
        rm -f "${arquivo}.parcial"
        erro "pg_dump falhou."
    fi
    [[ -s "${arquivo}.parcial" ]] || {
        rm -f "${arquivo}.parcial"
        erro "backup vazio."
    }
    mv "${arquivo}.parcial" "$arquivo"
    chmod 600 "$arquivo"
    info "backup concluído ($(du -h "$arquivo" | cut -f1)). Os dados pessoais estão cifrados: guarde as chaves do .env junto, em local seguro."
}

cmd_restore() {
    exigir_docker
    exigir_rodando
    local arquivo=${1:-}
    [[ -n "$arquivo" ]] || erro "use: ./odonto.sh restore <arquivo.dump>"
    [[ -s "$arquivo" ]] || erro "arquivo não encontrado ou vazio: ${arquivo}"
    aviso "o banco atual será SUBSTITUÍDO pelo conteúdo de ${arquivo}."
    confirmar "Continuar?" "RESTAURAR"
    info "restaurando"
    docker exec -i -u postgres "$NOME" sh -c \
        'pg_restore --clean --if-exists --no-owner --role="$DB_USER" --single-transaction -d "$DB_NAME"' <"$arquivo" ||
        erro "pg_restore falhou (o banco anterior foi mantido)."
    info "reiniciando para aplicar migrações pendentes e limpar o estado em memória"
    cmd_restart
}

cmd_psql() {
    exigir_docker
    exigir_rodando
    docker exec -it -u postgres "$NOME" sh -c 'psql -d "$DB_NAME"'
}

cmd_shell() {
    exigir_docker
    exigir_rodando
    docker exec -it "$NOME" bash
}

cmd_remove() {
    exigir_docker
    if container_existe; then
        cmd_stop
        docker rm "$NOME" >/dev/null
        info "container removido (os dados continuam no volume ${VOLUME})"
    else
        info "container não existe"
    fi
}

cmd_purge() {
    exigir_docker
    aviso "isto APAGA DEFINITIVAMENTE o banco (pacientes, prontuários, agenda) do volume ${VOLUME}."
    aviso "faça antes um backup (./odonto.sh backup) se houver qualquer dúvida."
    confirmar "Apagar tudo?" "APAGAR ${VOLUME}"
    if container_existe; then
        docker rm -f "$NOME" >/dev/null
    fi
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    imagem_existe && docker image rm "$IMAGEM" >/dev/null || true
    info "container, volume e imagem removidos"
}

cmd_ajuda() {
    cat <<EOF
${NEGRITO}Uso:${NORMAL} ./odonto.sh <comando>

  setup               cria o .env e gera senhas, chaves e tokens que estiverem vazios
  build               constrói a imagem (roda lint, mypy e testes)
  start               valida o .env, constrói se preciso e inicia; espera ficar saudável
  stop                para o container
  restart             recria o container (aplica mudanças no .env e no config/odonto.yaml)
  status              estado do container, /health e volume
  logs [app|db]       acompanha os logs da aplicação (padrão) ou do PostgreSQL
  agenda [AAAA-MM-DD] agenda do dia (padrão: hoje)
  backup              pg_dump para ${DIR_BACKUPS}/odonto-AAAAMMDD-HHMMSS.dump
  restore <arquivo>   restaura um backup (pede confirmação)
  psql                console do PostgreSQL
  shell               terminal dentro do container
  remove              remove o container (mantém os dados)
  purge               remove container, imagem e DADOS (pede confirmação)
EOF
}

comando=${1:-ajuda}
shift || true
case "$comando" in
    setup) cmd_setup ;;
    build) cmd_build ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_restart ;;
    status) cmd_status ;;
    logs) cmd_logs "$@" ;;
    agenda) cmd_agenda "$@" ;;
    backup) cmd_backup ;;
    restore) cmd_restore "$@" ;;
    psql) cmd_psql ;;
    shell) cmd_shell ;;
    remove) cmd_remove ;;
    purge) cmd_purge ;;
    ajuda | help | -h | --help) cmd_ajuda ;;
    *)
        cmd_ajuda >&2
        erro "comando desconhecido: ${comando}"
        ;;
esac
