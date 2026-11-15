# agent-whatsapp-odonto-py

[![CI](https://github.com/rafaelzucon/agent-whatsapp-odonto-py/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelzucon/agent-whatsapp-odonto-py/actions/workflows/ci.yml)

Agente de WhatsApp para consultório odontológico. Ele conversa com o paciente pelo número do
consultório (WhatsApp Cloud API da Meta) e:

1. identifica o paciente pelo **RG + UF** do órgão emissor;
2. faz o **cadastro** de quem é novo (com consentimento LGPD) e abre o **prontuário**;
3. pergunta a **queixa**, classifica-a num **catálogo de problemas odontológicos** e registra no
   prontuário;
4. pergunta **data e horário**, agenda a consulta e, se o horário estiver ocupado ou fora do
   expediente, **sugere o horário livre mais próximo**;
5. confirma ao paciente e **avisa o consultório** (WhatsApp da recepção, e-mail e log).

A conversa é um **workflow agêntico com etapas fixas** (uma máquina de estados), não um agente
autônomo: as respostas ao paciente são textos fixos e configuráveis. A IA (Claude, da Anthropic)
é usada só para **classificar a queixa no catálogo** e **interpretar datas em linguagem natural**
("amanhã à tarde", "sexta às 10h") quando o interpretador local não entende. **Nenhuma
orientação clínica é gerada por IA.** Áudios são transcritos (OpenAI) e tratados como texto.

Diagramas: [docs/diagramas](docs/diagramas/README.md).

## Sumário

- [Stack](#stack)
- [Exemplo de conversa](#exemplo-de-conversa-paciente-novo)
- [Arquitetura](#arquitetura)
- [Catálogo de problemas](#catálogo-de-problemas)
- [Configuração na Meta (WhatsApp Cloud API)](#configuração-na-meta-whatsapp-cloud-api)
- [Rodando com Docker no Linux](#rodando-com-docker-no-linux)
- [Expondo o webhook com HTTPS](#expondo-o-webhook-com-https)
- [Personalização: config/odonto.yaml](#personalização-configodontoyaml)
- [API da recepção](#api-da-recepção)
- [Comandos do odonto.sh](#comandos-do-odontosh)
- [Atualização e backup](#atualização-e-backup)
- [Tabela de configurações (.env)](#tabela-de-configurações-env)
- [Desenvolvimento local (sem Docker)](#desenvolvimento-local-sem-docker)
- [Segurança e LGPD](#segurança-e-lgpd)
- [Limitações e próximos passos](#limitações-e-próximos-passos)

## Stack

| Componente | Versão fixada | Uso |
|---|---|---|
| Python (CPython) | **3.14** (`>=3.14,<3.15`; 3.14.10 no lock) | linguagem |
| uv (Astral) | 0.13.8 (na imagem) | projeto, dependências, Python gerenciado |
| FastAPI / Uvicorn | 0.163 / 0.54 | webhook e API (1 worker) |
| Pydantic / pydantic-settings | 2.14 / 2.16 | validação e configuração (só adaptadores e infraestrutura) |
| PostgreSQL | 18 | banco (dentro do mesmo container) |
| SQLAlchemy (async) / psycopg 3 / Alembic | 2.1 / 3.3 / 1.20 | persistência e migrações |
| anthropic | 2.8 | classificação da queixa e datas (saída estruturada) |
| openai | 3.51 | transcrição de áudio (`gpt-transcribe`) |
| httpx | 0.28 | WhatsApp Cloud API (Graph API v24.0) |
| APScheduler | 3.11 | tarefas periódicas (expiração, expurgo, reprocessamento) |
| aiosmtplib | 5.1 | e-mail para o consultório |
| cryptography | 50.0 | AES-GCM dos dados pessoais |
| ruff / mypy / pytest / pytest-asyncio / respx / import-linter | 0.17 / 2.4 / 9.2 / 1.5 / 0.23 / 2.16 | qualidade |

As faixas exatas (`>=X.Y,<X+1`) estão no [`pyproject.toml`](pyproject.toml) e o
[`uv.lock`](uv.lock) é versionado.

**Por que Python 3.14 e não 3.15?** O 3.15.0 saiu em outubro de 2026, mas, na data da
construção, o **PyYAML** (dependência do pydantic-settings para o YAML e do carregador do
catálogo) **não publicava wheels `cp315`**. Sem wheel, a instalação compila a extensão C e exige
compilador e cabeçalhos na imagem. pydantic-core, psycopg, cryptography e uvloop já tinham
wheels. Quando o PyYAML publicar, basta trocar `requires-python`, `.python-version` e rodar
`uv lock --upgrade`.

## Exemplo de conversa (paciente novo)

```text
Paciente: Oi, boa tarde
Agente:   Olá! Aqui é o assistente automático do Consultório Odontológico. Para começar, informe
          o número do seu RG e a UF do órgão emissor (exemplo: 12.345.678-9 SP).
Paciente: 12.345.678-9 sp
Agente:   Não encontrei cadastro com esse RG. Vamos fazer agora, é rápido. Qual é o seu nome
          completo?
Paciente: Maria da Silva
Agente:   Qual é a sua data de nascimento? (dd/mm/aaaa)
Paciente: 15/03/1990
Agente:   Para fazer seu cadastro e seu prontuário, o Consultório Odontológico vai armazenar seus
          dados pessoais e de saúde com segurança, conforme a LGPD, e usar um sistema
          automatizado com inteligência artificial para organizar o atendimento. Você concorda?
          Responda SIM ou NÃO.
Paciente: sim
Agente:   Cadastro concluído! Seu prontuário é o PR-000001. Agora conte, em poucas palavras,
          qual é o problema ou o motivo da consulta.
Paciente: [áudio] "tô com uma dor de dente forte quando mastigo, do lado direito"
Agente:   Entendi. Para quando você gostaria de agendar? Pode escrever do seu jeito, por exemplo:
          amanhã às 14h, sexta de manhã, 25/11 às 10h.
Paciente: terça às 10h
Agente:   Esse horário não está disponível. O horário livre mais próximo é terça-feira,
          17/11/2026 às 10:30. Posso confirmar? Responda SIM, ou sugira outra data e horário.
Paciente: sim
Agente:   Consulta agendada para terça-feira, 17/11/2026 às 10:30, no endereço Rua Exemplo, 123 -
          Centro. Chegue com 10 minutos de antecedência e traga um documento com foto. Até lá!
```

Ao mesmo tempo, a recepção recebe no WhatsApp (template `novo_agendamento`):
"Nova consulta agendada pelo WhatsApp: paciente Maria da Silva, em terça-feira, 17/11/2026 às
10:30. Motivo informado: Dor de dente. Prioridade: Urgência. ...", e o mesmo aviso por e-mail.

Outros caminhos: paciente já cadastrado (vai direto à queixa ou avisa da consulta futura), menor
de 18 anos (pede o responsável legal), consentimento recusado, emergência (texto fixo de
pronto-socorro/SAMU, aviso imediato ao consultório e oferta do primeiro horário livre), três
respostas inválidas seguidas ou agenda cheia (encaminha para a equipe). Veja os
[diagramas de sequência](docs/diagramas/README.md).

## Arquitetura

### Clean Architecture e regra de dependência

```text
infraestrutura  (FastAPI, Uvicorn, configuração, logs, composição)
   → adaptador  (entrada: webhook, API, fila, agendador | saída: banco, WhatsApp, IA, e-mail...)
      → aplicacao  (casos de uso e portas)
         → dominio  (regras de negócio puras, só biblioteca padrão)
```

O código só importa camadas mais internas. `dominio` e `aplicacao` usam **só a biblioteca
padrão** (nem Pydantic): entidades com `slots=True`, objetos de valor
`dataclass(frozen=True, slots=True)` que validam invariantes no `__post_init__`, portas como
`typing.Protocol`, `StrEnum`, `match` e aliases `type`. O mypy roda em modo `strict`.

```text
src/odonto/
├── dominio/
│   ├── modelo/        Paciente, Prontuario, QueixaRelatada, Consulta, BloqueioAgenda, Conversa
│   │                  (máquina de estados), Mensagem, eventos, objetos de valor (DocumentoRg...)
│   └── servico/       Agenda (disponibilidade), ValidadorDados, InterpretadorDataHora,
│                      DetectorSinaisAlarme, ClassificadorPalavraChave
├── aplicacao/
│   ├── portas/entrada/   casos de uso (Protocols + commands e resumos imutáveis)
│   ├── portas/saida/     repositórios, UnidadeDeTrabalho, EnviadorWhatsApp, IA, transcrição,
│   │                     CanalNotificacaoConsultorio, fila, relógio, cifrador
│   └── casos_de_uso/     ConduzirConversaService, RegistrarQueixaService,
│                         AgendarConsultaService, NotificarConsultorioService...
├── adaptador/
│   ├── entrada/web/      routers do webhook e da API (só conhecem portas de entrada)
│   ├── entrada/fila/     consumidor da fila de processamento
│   ├── entrada/agendador/ tarefas periódicas (APScheduler)
│   └── saida/            persistencia (SQLAlchemy, mappers, UoW, AES-GCM), whatsapp (httpx),
│                         ia (anthropic), transcricao (openai), notificacao (whatsapp, e-mail,
│                         log), fila (asyncio), relogio
└── infraestrutura/       config.py, container.py (composição), app.py, servidor.py, logs.py
```

### SOLID no código

- **S – responsabilidade única:** `Agenda` (domínio) só decide disponibilidade e o horário mais
  próximo; `ValidadorDados` só valida respostas; `RegistrarQueixaService` só classifica e
  registra a queixa; o envio de avisos fica em `NotificarConsultorioService`.
- **O – aberto/fechado:** um novo canal de aviso é só uma nova classe que implementa
  `CanalNotificacaoConsultorio`; `NotificarConsultorioService` percorre a lista de canais sem
  mudar (e a falha de um canal não impede os outros).
- **L – substituição de Liskov:** os testes de aplicação usam fakes em memória das mesmas portas
  (`UnidadeDeTrabalho`, repositórios, `Relogio`) e os casos de uso não percebem a diferença.
- **I – segregação de interfaces:** portas pequenas e específicas (`ClassificadorProblemaIA` e
  `InterpretadorDataHoraIA` separadas; `EnviadorWhatsApp` separado de `ProvedorMidia`), e os
  routers dependem só da porta de entrada que usam.
- **D – inversão de dependência:** os casos de uso recebem `Protocol`s no construtor; quem decide
  as implementações concretas é o `container.py`.

A conversa segue o "diga, não pergunte": o caso de uso informa fatos à `Conversa`
(`paciente_encontrado`, `queixa_registrada`, `horario_sugerido`...) e ela devolve uma
`AcaoConversa` com a resposta e o próximo comando; as transições inválidas levantam erro.

### Raiz de composição (`infraestrutura/container.py`)

É o único lugar que conhece todas as implementações: lê `Configuracoes` (pydantic-settings),
converte as seções do YAML em objetos de configuração da aplicação, cria engine, UoW, clientes
httpx/Anthropic/OpenAI, canais de notificação habilitados, fila e casos de uso, e os entrega ao
`app.py` (FastAPI com `lifespan`). A configuração é validada antes de subir o servidor; erro no
YAML ou no `.env` encerra com código 2 e mensagem clara.

### Unit of Work

`UnidadeDeTrabalho` é uma transação com acesso aos repositórios: `async with uow: ...;
await uow.commit()`. Ela é reentrante (um caso de uso pode chamar outro na mesma transação) e
coleta os **eventos de domínio** dos agregados (`ConsultaAgendada`, `EmergenciaDetectada`,
`AtendimentoHumanoNecessario`, `ConsentimentoRecusado`), publicando-os na fila **só depois do
commit**. Assim o consultório nunca é avisado de algo que não foi gravado.

Concorrência: as mensagens de um mesmo número são processadas em ordem pela fila; dois pacientes
que pedem o mesmo horário são resolvidos pelo índice único parcial
`ux_consulta_inicio_agendada`. Quem perde a corrida recebe a oferta do próximo horário livre.

### Como estender

**Novo canal de notificação (ex.: Telegram, SMS):**

1. crie `adaptador/saida/notificacao/telegram_canal.py` com uma classe que implemente
   `CanalNotificacaoConsultorio` (`nome`, `novo_agendamento`, `alerta`);
2. adicione as variáveis em `Configuracoes` e no `.env.example`;
3. inclua a classe em `_canais()` no `container.py`. Nenhum caso de uso muda.

**Agenda externa (Google Agenda, sistema de gestão odontológica):**

- implemente `ConsultaRepositorio` e `BloqueioAgendaRepositorio` sobre a API externa (ou um
  repositório composto que grava no banco e sincroniza com o serviço externo) e troque a
  implementação no `container.py`/na UoW;
- as regras de disponibilidade continuam no domínio (`Agenda`), que recebe as consultas e os
  bloqueios já carregados.

### Contratos do import-linter

`uv run lint-imports` (e `tests/test_arquitetura.py`) verifica 7 contratos definidos no
`pyproject.toml`:

1. camadas: `infraestrutura → adaptador → aplicacao → dominio`;
2. `dominio` e `aplicacao` não importam bibliotecas de terceiros;
3. adaptadores de entrada e de saída não se importam;
4. só a persistência (e a infraestrutura) importa `sqlalchemy`;
5. só o adaptador de IA importa `anthropic`;
6. só o adaptador de transcrição importa `openai`;
7. routers web conhecem só as portas de entrada (não os casos de uso concretos).

Um import proibido quebra o CI.

## Catálogo de problemas

O catálogo tem **63 itens** em
[`catalogo_problemas.yaml`](src/odonto/adaptador/saida/persistencia/dados/catalogo_problemas.yaml),
cada um com código, nome, descrição para leigos, especialidade, prioridade padrão
(`EMERGENCIA`, `URGENCIA`, `ROTINA`), código CID-10 de referência e palavras-chave do jeito que
o paciente escreve.

**Fontes:** CID-10 (OMS/DATASUS), capítulo XI, **K00–K14** (doenças da cavidade oral, glândulas
salivares e maxilares), mais **S02.5** (fratura de dente), **S03.2** (luxação de dente) e alguns
códigos de apoio (B00.1, B37.0, R19.6, T81, T85, Z); e as **especialidades odontológicas
reconhecidas pelo CFO** para agrupar os itens. O CID-10 é só referência: quem diagnostica é o
dentista, que pode reclassificar qualquer queixa pela API (origem `MANUAL`).

Classificação: a IA recebe o catálogo e o texto da queixa e devolve código, confiança e
prioridade (validados com Pydantic, código restrito ao catálogo). Se a IA falhar, devolver um
código desconhecido ou ficar abaixo de `classificacao.confianca_minima`, o
`ClassificadorPalavraChave` do domínio assume; sem correspondência, a queixa fica como
`AVALIACAO_GERAL_OUTRO` (o dentista avalia e reclassifica). Palavras de alarme
(`classificacao.palavras_alarme`) ou sinais de alarme apontados pela IA elevam a prioridade para
`EMERGENCIA`; a prioridade final é a mais alta entre o item do catálogo, a IA e o alarme.

**Incluir ou alterar itens:** o YAML é a fonte única e é carregado pela migração
`0002_catalogo_problemas` (idempotente). Depois de implantado:

1. edite o YAML (novos itens no fim; não reutilize códigos);
2. crie uma migração: `uv run alembic revision -m "catalogo: inclui X"`;
3. no `upgrade()`, para itens novos, repita a carga da 0002 (`ler_catalogo()` +
   `insert(...).on_conflict_do_nothing()`); para alterações, faça `UPDATE` pelo `codigo`;
   para retirar um item, use `ativo = false` (nunca apague: há queixas que o referenciam);
4. `./odonto.sh build && ./odonto.sh restart`; a migração roda sozinha.

## Configuração na Meta (WhatsApp Cloud API)

> Os menus da Meta mudam com frequência; os nomes abaixo eram os vigentes na construção.

1. **Conta e app:** em [business.facebook.com](https://business.facebook.com) tenha um
   Portfólio Empresarial verificado. Em [developers.facebook.com](https://developers.facebook.com)
   → *Meus apps* → *Criar app* → caso de uso *Conectar com clientes pelo WhatsApp* (tipo
   Empresa) e vincule ao portfólio.
2. **Número do consultório e coexistência:** em *WhatsApp → Configuração da API*, adicione o
   número. Se o consultório já usa o **app WhatsApp Business** nesse número, escolha o
   **modo de coexistência** (cadastro incorporado com "usar número existente do WhatsApp
   Business"): o número passa a funcionar na Cloud API **e continua** no app do celular, com o
   histórico sincronizado. A equipe continua vendo as conversas no celular e pode assumir quando
   o agente encaminhar para atendimento humano. Sem coexistência, o número sai do app e só
   funciona pela API. O celular precisa abrir o app Business periodicamente para manter a
   coexistência ativa (veja as regras atuais da Meta).
3. **Token permanente:** em *Configurações do negócio → Usuários → Usuários do sistema*, crie um
   usuário do sistema (Admin), atribua o app e a conta do WhatsApp e gere um token **sem
   expiração** com as permissões `whatsapp_business_messaging` e
   `whatsapp_business_management`. Esse é o `WHATSAPP_ACCESS_TOKEN` (o token temporário do painel
   expira em 24 h).
4. **IDs e segredo:** o **Phone Number ID** (não é o número de telefone) está em *WhatsApp →
   Configuração da API* → `WHATSAPP_PHONE_NUMBER_ID`. O **App Secret** está em *Configurações
   do app → Básico* → `WHATSAPP_APP_SECRET` (valida a assinatura `X-Hub-Signature-256` de cada
   webhook).
5. **Webhook:** em *WhatsApp → Configuração*, URL de callback
   `https://SEU-DOMINIO/webhook/whatsapp`, token de verificação = `WHATSAPP_VERIFY_TOKEN` do
   `.env`. Depois, assine o campo **`messages`**. O sistema precisa estar no ar (com HTTPS) para
   a verificação.
6. **Número de notificação:** `CONSULTORIO_WHATSAPP_NOTIFICACAO` é o **celular da recepção**
   (ou do dentista), diferente do número do consultório: o número do consultório é o remetente
   do agente e não consegue mandar mensagem para si mesmo. Como a recepção normalmente não
   conversou com o número do consultório nas últimas 24 h, os avisos usam **templates aprovados**.
7. **Templates:** no [WhatsApp Manager](https://business.facebook.com/wa/manage/) → *Modelos de
   mensagem* → *Criar modelo* → categoria **Utilidade** → nome e idioma **Português (BR)** →
   corpo → *exemplos das variáveis* → *Enviar para análise*.

   **`novo_agendamento`**

   ```text
   Nova consulta agendada pelo WhatsApp: paciente {{1}}, em {{2}}. Motivo informado: {{3}}. Prioridade: {{4}}. Confira os detalhes na agenda do consultório.
   ```

   Exemplos: {{1}} = `Maria Silva`, {{2}} = `25/11 às 10:00`, {{3}} = `Dor de dente`,
   {{4}} = `Urgência`.

   **`alerta_consultorio`**

   ```text
   Aviso do assistente do consultório: {{1}} referente ao paciente {{2}}. Detalhe: {{3}}. Por favor, entre em contato com o paciente assim que possível.
   ```

   Exemplos: {{1}} = `Emergência odontológica`, {{2}} = `João Souza`,
   {{3}} = `Inchaço no rosto com febre`.

   O código envia exatamente 4 e 3 parâmetros, nessa ordem. Os nomes e o idioma podem ser
   alterados em `WHATSAPP_TEMPLATE_*`.

**A conversa com os pacientes não precisa de templates:** o agente só responde a quem escreveu,
dentro da janela de atendimento de 24 h. Enquanto os templates não forem aprovados (ou se
`CONSULTORIO_WHATSAPP_NOTIFICACAO` estiver vazio), os avisos chegam **só por e-mail e log**; a
falha do canal WhatsApp é registrada e não afeta os demais canais.

## Rodando com Docker no Linux

Pré-requisitos: Docker Engine 24+ e Git. Tudo (aplicação + PostgreSQL 18) roda num **único
container**; os dados ficam no volume `agent-whatsapp-odonto-py-dados`.

```bash
git clone https://github.com/rafaelzucon/agent-whatsapp-odonto-py.git && cd agent-whatsapp-odonto-py
./odonto.sh setup     # cria o .env e gera senha do banco, chaves e tokens
nano .env             # preencha WhatsApp, Anthropic, OpenAI e SMTP
./odonto.sh start     # constrói a imagem (com lint e testes), sobe e espera ficar saudável
```

Na inicialização, o `docker/entrypoint.sh` cria o cluster (na primeira vez), sobe o PostgreSQL
em `127.0.0.1` dentro do container, garante usuário e banco, roda `alembic upgrade head` e inicia
a aplicação. `docker stop` encerra a aplicação e o banco de forma limpa. O
[`docker-compose.yml`](docker-compose.yml) é uma alternativa equivalente (`docker compose up -d`).

A porta publicada (`PORTA` no `.env`, padrão 8080) fica aberta em todas as interfaces do host,
e o Docker ignora as regras do `ufw`. Em servidor com IP público, bloqueie essa porta no
firewall do provedor e deixe acessível só o proxy HTTPS (ou use o Cloudflare Tunnel, que não
precisa de porta aberta).

## Expondo o webhook com HTTPS

A Meta exige HTTPS com certificado válido. Opções:

- **Cloudflare Tunnel** (sem abrir portas, recomendado para servidor no consultório):

  ```bash
  cloudflared tunnel login
  cloudflared tunnel create odonto
  cloudflared tunnel route dns odonto odonto.seudominio.com.br
  cloudflared tunnel run --url http://127.0.0.1:8080 odonto
  ```

- **ngrok** (testes): `ngrok http 8080` e use a URL `https://...ngrok-free.app/webhook/whatsapp`.
- **Caddy** (VPS com IP público e domínio; certificado Let's Encrypt automático), `Caddyfile`:

  ```text
  odonto.seudominio.com.br {
      reverse_proxy 127.0.0.1:8080
  }
  ```

  Com **Nginx**, use `certbot --nginx` e `proxy_pass http://127.0.0.1:8080;`.

Se o proxy rodar em outro container ou host, ajuste `FORWARDED_ALLOW_IPS` para que os IPs reais
apareçam nos logs. Exponha só `/webhook/whatsapp` publicamente se possível; a API exige
`X-Admin-Token` de qualquer forma.

## Personalização: `config/odonto.yaml`

O arquivo [`config/odonto.yaml`](config/odonto.yaml) (montado somente leitura no container)
contém tudo o que não é segredo:

- `consultorio`: nome e endereço (usados nas mensagens);
- `conversa.mensagens` e `conversa.dicas`: todos os textos enviados ao paciente, com os
  marcadores `NOME_CONSULTORIO`, `NOME_PACIENTE`, `DATA_HORA`, `ENDERECO` e `PRONTUARIO`;
  `expiracao_minutos` e `max_tentativas_por_etapa`;
- `classificacao`: confiança mínima da IA e palavras de alarme;
- `agendamento`: duração da consulta, dias e horário de funcionamento, almoço, antecedência
  mínima, alcance da busca, `confirmar_sugestao` e **feriados** (inclua os municipais e
  estaduais; os nacionais de 2026–2027 já estão lá);
- `retencao`: dias de guarda do texto das mensagens e horário do expurgo;
- `api.docs_habilitada`: Swagger em `/docs?token=ADMIN_TOKEN` (deixe `false` em produção).

Horários sempre entre aspas (`"08:00"`). Para aplicar: **`./odonto.sh restart`** (não precisa
reconstruir a imagem). Um YAML inválido impede a subida com uma mensagem indicando o campo.

**Bloqueios de agenda** (folga, curso, manutenção) são criados pela API; consultas já marcadas no
período não são canceladas, mas são listadas na resposta para a recepção remarcar:

```bash
curl -X POST http://127.0.0.1:8080/api/agenda/bloqueios \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"inicio": "2026-12-24T08:00:00-03:00", "fim": "2026-12-24T18:00:00-03:00", "motivo": "Véspera de Natal"}'
```

## API da recepção

Todas as rotas `/api` exigem o cabeçalho `X-Admin-Token` (comparado com
`hmac.compare_digest`). Datas com fuso (ISO 8601).

```bash
export ADMIN_TOKEN=$(grep ^ADMIN_TOKEN= .env | cut -d= -f2-)
API=http://127.0.0.1:8080/api
H="X-Admin-Token: $ADMIN_TOKEN"

# Agenda do período (consultas, bloqueios e horários livres; até 62 dias)
curl -s -H "$H" "$API/agenda?inicio=2026-11-16&fim=2026-11-20"

# Remover um bloqueio
curl -s -X DELETE -H "$H" "$API/agenda/bloqueios/<bloqueio_id>"

# Agendar pela recepção (origem RECEPCAO)
curl -s -X POST -H "$H" -H "Content-Type: application/json" "$API/consultas" \
  -d '{"paciente_id": "<uuid>", "inicio": "2026-11-18T14:00:00-03:00"}'

# Cancelar, marcar como realizada ou registrar falta
curl -s -X POST -H "$H" "$API/consultas/<consulta_id>/cancelar"
curl -s -X POST -H "$H" "$API/consultas/<consulta_id>/realizada"
curl -s -X POST -H "$H" "$API/consultas/<consulta_id>/falta"

# Buscar paciente por nome ou por RG + UF
curl -s -H "$H" "$API/pacientes?nome=maria"
curl -s -H "$H" "$API/pacientes?rg=12.345.678-9&uf=SP"

# Prontuário completo (queixas e consultas)
curl -s -H "$H" "$API/pacientes/<paciente_id>/prontuario"

# Reclassificar uma queixa (dentista)
curl -s -X PUT -H "$H" -H "Content-Type: application/json" "$API/queixas/<queixa_id>/classificacao" \
  -d '{"codigo_problema": "PULPITE", "prioridade": "URGENCIA"}'

# Catálogo de problemas
curl -s -H "$H" "$API/catalogo-problemas"

# Saúde (sem token; 503 se o banco estiver fora)
curl -s http://127.0.0.1:8080/health
```

## Comandos do `odonto.sh`

| Comando | O que faz |
|---|---|
| `./odonto.sh setup` | cria o `.env` (chmod 600) e gera senhas, chaves e tokens vazios |
| `./odonto.sh build` | constrói a imagem (roda ruff, mypy, contratos e testes no build) |
| `./odonto.sh start` | valida o `.env`, constrói se preciso, inicia e espera ficar saudável |
| `./odonto.sh stop` | para o container (encerramento limpo do banco) |
| `./odonto.sh restart` | recria o container, aplicando `.env` e `config/odonto.yaml` |
| `./odonto.sh status` | estado do container, `/health` e volume |
| `./odonto.sh logs [app\|db]` | acompanha os logs da aplicação (JSON) ou do PostgreSQL |
| `./odonto.sh agenda [AAAA-MM-DD]` | agenda do dia no terminal |
| `./odonto.sh backup` | `pg_dump -Fc` para `backups/odonto-AAAAMMDD-HHMMSS.dump` |
| `./odonto.sh restore <arquivo>` | restaura um backup (pede para digitar `RESTAURAR`) |
| `./odonto.sh psql` | console do PostgreSQL |
| `./odonto.sh shell` | terminal dentro do container |
| `./odonto.sh remove` | remove o container (mantém os dados) |
| `./odonto.sh purge` | remove container, imagem **e dados** (pede confirmação) |

## Atualização e backup

**Atualizar:**

```bash
./odonto.sh backup
git pull
./odonto.sh build
./odonto.sh restart     # as migrações do Alembic rodam sozinhas na subida
```

**Backup diário** (crontab do usuário que roda o Docker, `crontab -e`), mantendo 30 dias:

```cron
30 2 * * * cd /opt/agent-whatsapp-odonto-py && ./odonto.sh backup >> backups/backup.log 2>&1 && find backups -name 'odonto-*.dump' -mtime +30 -delete
```

Copie os backups **e o `.env`** para fora do servidor (outro disco, nuvem com criptografia):
os dados pessoais são cifrados com `CHAVE_CRIPTOGRAFIA` e o RG é localizado com
`CHAVE_HMAC_DOCUMENTO`; **sem essas chaves, o backup é inútil.**

## Tabela de configurações (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `DB_PASSWORD`, `DB_NAME`, `DB_USER` | gerada, `odonto`, `odonto` | banco interno (o container monta a `DATABASE_URL`) |
| `CHAVE_CRIPTOGRAFIA` | gerada | 32 bytes Base64; AES-GCM de nomes, RG, mensagens e queixas |
| `CHAVE_HMAC_DOCUMENTO` | gerada | 32 bytes Base64; HMAC-SHA256 de RG + UF (busca sem decifrar) |
| `ADMIN_TOKEN` | gerado | token da API (`X-Admin-Token`), 16+ caracteres |
| `WHATSAPP_PHONE_NUMBER_ID` | — | ID do número na Cloud API |
| `WHATSAPP_ACCESS_TOKEN` | — | token permanente do usuário do sistema |
| `WHATSAPP_APP_SECRET` | — | segredo do app (assinatura do webhook) |
| `WHATSAPP_VERIFY_TOKEN` | gerado | token de verificação do webhook |
| `WHATSAPP_API_VERSION` | `v24.0` | versão da Graph API |
| `WHATSAPP_TEMPLATE_NOVO_AGENDAMENTO` | `novo_agendamento` | template do aviso de agendamento |
| `WHATSAPP_TEMPLATE_ALERTA` | `alerta_consultorio` | template de alerta (emergência, atendimento humano) |
| `WHATSAPP_TEMPLATE_IDIOMA` | `pt_BR` | idioma dos templates |
| `CONSULTORIO_WHATSAPP_NOTIFICACAO` | — | celular da recepção (só dígitos, com DDI); vazio desliga o aviso por WhatsApp |
| `ANTHROPIC_API_KEY` | — | chave da Anthropic; vazia usa só palavras-chave e o parser local |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | modelo para classificação e datas |
| `ANTHROPIC_TIMEOUT_SEGUNDOS` | `30` | timeout (com `max_retries=3`) |
| `TRANSCRICAO_PROVEDOR` | `openai` | `openai` ou `none` (pede para o paciente escrever) |
| `TRANSCRICAO_MODELO` | `gpt-transcribe` | modelo de transcrição |
| `OPENAI_API_KEY` | — | chave da OpenAI |
| `OPENAI_TIMEOUT_SEGUNDOS` | `60` | timeout da transcrição |
| `SMTP_HOST`, `SMTP_PORT` | —, `587` | servidor de e-mail (STARTTLS; TLS direto na 465); e-mail ligado se `SMTP_HOST` e `CONSULTORIO_EMAIL` existirem |
| `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_REMETENTE` | — | credenciais e remetente |
| `CONSULTORIO_EMAIL` | — | destinatário dos avisos |
| `TZ` | `America/Sao_Paulo` | fuso (o YAML `fuso` tem precedência) |
| `LOG_NIVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PORTA` | `8080` | porta publicada no host (todas as interfaces) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies confiáveis para `X-Forwarded-For` |
| `ODONTO_CONFIG` | `config/odonto.yaml` | caminho do YAML (no container, `/app/config/odonto.yaml`) |

**Modelos de transcrição:** o padrão é `gpt-transcribe`. O `whisper-1` ainda funciona como
alternativa, mas a OpenAI anunciou o desligamento dele em **26/02/2027**. Confira a página de
deprecações da OpenAI antes de trocar de modelo.

## Desenvolvimento local (sem Docker)

```bash
uv sync                                   # instala o Python 3.14 gerenciado e as dependências
docker run -d --name odonto-pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:18   # ou um PG local
./odonto.sh setup                         # gera o .env com as chaves
echo 'DATABASE_URL=postgresql+psycopg://postgres:dev@127.0.0.1:5432/postgres' >> .env
set -a; source .env; set +a               # o Alembic lê DATABASE_URL do ambiente
uv run alembic upgrade head
uv run python -m odonto                   # ou: uv run odonto
```

Qualidade e testes (os mesmos do CI):

```bash
uv run ruff check && uv run ruff format --check
uv run mypy
uv run lint-imports
uv run pytest
# testes de integração das migrações contra um PostgreSQL real:
ODONTO_TESTE_DATABASE_URL=postgresql+psycopg://postgres:dev@127.0.0.1:5432/postgres uv run pytest tests/integracao
```

Os testes de domínio e aplicação não usam banco nem chaves (fakes em memória e `Relogio` fixo);
os de adaptadores usam `respx` e o `TestClient` do FastAPI. Para simular o WhatsApp localmente,
envie ao `/webhook/whatsapp` um payload da Cloud API assinado com
`X-Hub-Signature-256: sha256=HMAC(WHATSAPP_APP_SECRET, corpo)`.

## Segurança e LGPD

- **Dados sensíveis:** queixas e prontuário são dados de saúde, **dados pessoais sensíveis**
  (LGPD, art. 5º, II, e art. 11). O cadastro só é feito com **consentimento** explícito pelo
  WhatsApp (data registrada no paciente); a recusa encerra a conversa sem cadastro e avisa a
  equipe. Atendimento à saúde (art. 11, II, "f") também pode amparar o tratamento: defina a base
  legal com seu encarregado/advogado.
- **RG protegido:** guardado cifrado (AES-GCM) e localizado por `rg_hash` = HMAC-SHA256 de
  RG + UF normalizados, com chave separada. Nomes, responsável, texto das mensagens e queixas
  também são cifrados. Os logs registram só metadados (final do número, códigos, ids) e
  mascaram tokens.
- **Minimização com a IA:** para a Anthropic vão só o texto da queixa (com o catálogo) ou o
  texto da data; nunca nome, RG ou telefone. Para a OpenAI vai só o áudio.
- **Retenção:** o texto das mensagens é apagado após `retencao.mensagens_dias` (padrão 90). O
  **prontuário não é apagado**: a Lei 13.787/2018 (art. 6º) prevê guarda mínima de **20 anos**
  a partir do último registro para prontuários em meio eletrônico. Verifique também as
  resoluções do CFO vigentes (não verificadas nesta construção).
- **Operadores (DPA):** formalize os termos de tratamento de dados com **Anthropic**, **OpenAI**
  e **Meta** (WhatsApp Business), avalie a transferência internacional (LGPD, arts. 33 a 36) e
  prefira as opções sem retenção/treinamento disponíveis nas contas empresariais.
- **Chaves e acesso:** `.env` com `chmod 600`, nunca versionado; guarde uma cópia das chaves
  **fora do servidor** (cofre de senhas). Webhook só aceita requisições com assinatura válida;
  API só com `X-Admin-Token`; o banco não é exposto fora do container. Mantenha este
  **repositório privado** e o servidor atualizado.

## Limitações e próximos passos

- **1 worker:** a fila de processamento fica em memória; as mensagens recebidas são gravadas
  antes de enfileirar e as pendentes são reenfileiradas na subida. Escalar horizontalmente exige uma
  fila externa (ex.: PostgreSQL `LISTEN/NOTIFY`, Redis) e o agendador num único processo.
- Cancelamento e remarcação pelo próprio paciente no WhatsApp.
- Lembretes automáticos antes da consulta (template de utilidade).
- Vários dentistas e cadeiras (agenda por profissional/recurso).
- Integração com Google Agenda ou sistema de gestão odontológica.
- Interface web para a recepção (hoje: API + `./odonto.sh agenda`).
- Testes de integração com Testcontainers (hoje: banco via `ODONTO_TESTE_DATABASE_URL`).
- Não verificado nesta construção: chamadas reais à Meta, Anthropic, OpenAI e SMTP (cobertas
  por mocks e testes de contrato).
