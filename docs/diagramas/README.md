# Diagramas

Fontes em Mermaid na pasta [`fonte/`](fonte/). O GitHub renderiza os blocos abaixo diretamente.
Não há SVG/PNG versionados: o mermaid-cli (`mmdc`) não estava disponível no ambiente de geração. Para gerar localmente:

```bash
npx -p @mermaid-js/mermaid-cli mmdc -i docs/diagramas/fonte/01-arquitetura.mmd -o docs/diagramas/01-arquitetura.svg
```

## Índice

- [1. Arquitetura](fonte/01-arquitetura.mmd)
- [2. Modelo de dados](fonte/02-modelo-dados.mmd)
- [3. Estados da conversa (`EtapaConversa`)](fonte/03-estados-conversa.mmd)
- [4. Sequência: paciente novo](fonte/04-sequencia-paciente-novo.mmd)
- [5. Sequência: paciente existente](fonte/05-sequencia-paciente-existente.mmd)
- [6. Sequência: horário ocupado e conflito de concorrência](fonte/06-sequencia-horario-ocupado.mmd)
- [7. Sequência: queixa com sinais de alarme](fonte/07-sequencia-emergencia.mmd)
- [8. Fluxo de dados nível 0 (contexto)](fonte/08-fluxo-dados-n0.mmd)
- [9. Fluxo de dados nível 1](fonte/09-fluxo-dados-n1.mmd)
- [10. Implantação](fonte/10-implantacao.mmd)

## 1. Arquitetura

Camadas da Clean Architecture. As setas significam "importa" e sempre apontam para dentro; a regra é verificada pelo import-linter (`uv run lint-imports`).

```mermaid
%% Camadas da Clean Architecture: as setas indicam "importa" (sempre para dentro).
flowchart TB
    subgraph INFRA["infraestrutura (frameworks, configuração e composição)"]
        direction LR
        servidor["servidor.py<br/>Uvicorn, 1 worker"]
        app["app.py<br/>FastAPI + ciclo de vida"]
        container["container.py<br/>raiz de composição"]
        config["config.py<br/>pydantic-settings + YAML"]
        logs["logs.py<br/>JSON em uma linha"]
    end

    subgraph ADAPT["adaptador"]
        direction LR
        subgraph ENTRADA["entrada"]
            web["web: webhook, agenda,<br/>pacientes, erros"]
            fila_in["fila: ConsumidorFila"]
            agendador["agendador: APScheduler"]
        end
        subgraph SAIDA["saída"]
            persist["persistencia: SQLAlchemy,<br/>UoW, AES-GCM, HMAC"]
            whats["whatsapp: Cloud API (httpx)"]
            ia["ia: Anthropic"]
            transc["transcricao: OpenAI"]
            notif["notificacao: WhatsApp,<br/>e-mail, log"]
            fila_out["fila: FilaAsyncio"]
            relogio["relogio: RelogioSistema"]
        end
    end

    subgraph APP["aplicacao (casos de uso e portas)"]
        direction LR
        portas_in["portas.entrada<br/>*UseCase, comandos, DTOs"]
        casos["casos_de_uso<br/>*Service"]
        portas_out["portas.saida<br/>Repositorio, UnidadeDeTrabalho,<br/>EnviadorWhatsApp, ClassificadorProblemaIA..."]
    end

    subgraph DOM["dominio (só biblioteca padrão)"]
        direction LR
        modelo["modelo: Paciente, Prontuario,<br/>QueixaRelatada, Consulta, Conversa"]
        servico["servico: Agenda, ValidadorDados,<br/>ClassificadorPalavraChave,<br/>DetectorSinaisAlarme"]
    end

    INFRA --> ADAPT
    INFRA --> APP
    web --> portas_in
    fila_in --> portas_in
    agendador --> portas_in
    casos -. implementa .-> portas_in
    casos --> portas_out
    SAIDA -. implementa .-> portas_out
    APP --> DOM
    ADAPT --> DOM
```

## 2. Modelo de dados

Tabelas do PostgreSQL criadas pelas migrações do Alembic (`migracoes/versions`). Campos marcados como cifrados usam AES-GCM; o RG é localizado pelo `rg_hash` (HMAC-SHA256 de RG + UF).

```mermaid
erDiagram
    PACIENTE ||--o{ PACIENTE_TELEFONE : "tem"
    PACIENTE ||--|| PRONTUARIO : "tem"
    PRONTUARIO ||--o{ QUEIXA_RELATADA : "registra"
    PROBLEMA_ODONTOLOGICO ||--o{ QUEIXA_RELATADA : "classifica"
    PACIENTE ||--o{ CONSULTA : "agenda"
    QUEIXA_RELATADA |o--o| CONSULTA : "motiva"

    PACIENTE {
        uuid id PK
        varchar rg_hash UK "HMAC-SHA256(RG+UF)"
        text rg_cifrado "AES-256-GCM"
        text nome_cifrado "AES-256-GCM"
        text data_nascimento_cifrada "AES-256-GCM"
        text responsavel_cifrado "AES-256-GCM, menor de 18"
        boolean consentimento_lgpd
        timestamptz consentimento_em
        timestamptz cadastrado_em
    }
    PACIENTE_TELEFONE {
        int id PK
        uuid paciente_id FK
        varchar wa_id
        timestamptz vinculado_em
    }
    PRONTUARIO {
        uuid id PK
        uuid paciente_id FK,UK
        int numero UK "sequência: PR-000001"
        timestamptz aberto_em
    }
    QUEIXA_RELATADA {
        uuid id PK
        uuid prontuario_id FK
        text texto_cifrado "AES-256-GCM"
        varchar problema_codigo FK
        varchar prioridade
        float confianca
        varchar origem "IA, PALAVRA_CHAVE, MANUAL"
        text sintomas_cifrados
        timestamptz registrada_em
        timestamptz reclassificada_em
        uuid consulta_id FK
    }
    PROBLEMA_ODONTOLOGICO {
        varchar codigo PK
        varchar nome
        text descricao
        varchar especialidade
        varchar prioridade
        varchar cid10
        json palavras_chave
        boolean ativo
        int ordem
    }
    CONSULTA {
        uuid id PK
        uuid paciente_id FK
        uuid queixa_id FK
        timestamptz inicio "único entre AGENDADA"
        timestamptz fim
        varchar status
        varchar prioridade
        varchar origem
        timestamptz agendada_em
        timestamptz atualizada_em
    }
    BLOQUEIO_AGENDA {
        uuid id PK
        timestamptz inicio
        timestamptz fim
        varchar motivo
        timestamptz criado_em
    }
    CONVERSA {
        uuid id PK
        varchar wa_id UK
        varchar etapa
        text dados_cifrados "AES-256-GCM"
        int tentativas_invalidas
        timestamptz ultima_interacao
        timestamptz iniciada_em
        timestamptz encerrada_em
    }
    MENSAGEM {
        uuid id PK
        varchar wa_id
        varchar direcao "RECEBIDA, ENVIADA"
        varchar tipo
        text texto_cifrado "AES-256-GCM"
        varchar wa_message_id UK "idempotência"
        varchar midia_id
        boolean automatica
        timestamptz momento
        timestamptz criada_em
        timestamptz processada_em "NULL = pendente"
    }
```

## 3. Estados da conversa (`EtapaConversa`)

Máquina de estados fixa implementada em `dominio/modelo/conversa.py`. Três respostas inválidas seguidas encaminham para atendimento humano; a inatividade expira a conversa e a próxima mensagem recomeça do RG.

```mermaid
stateDiagram-v2
    [*] --> AGUARDANDO_RG: primeira mensagem / boas-vindas

    AGUARDANDO_RG --> AGUARDANDO_PROBLEMA: RG encontrado
    AGUARDANDO_RG --> AGUARDANDO_DECISAO_NOVA_CONSULTA: RG encontrado e já tem consulta futura
    AGUARDANDO_RG --> AGUARDANDO_NOME: RG não cadastrado

    AGUARDANDO_NOME --> AGUARDANDO_DATA_NASCIMENTO: nome válido
    AGUARDANDO_DATA_NASCIMENTO --> AGUARDANDO_RESPONSAVEL: menor de 18 anos
    AGUARDANDO_DATA_NASCIMENTO --> AGUARDANDO_CONSENTIMENTO: maior de idade
    AGUARDANDO_RESPONSAVEL --> AGUARDANDO_CONSENTIMENTO: nome do responsável
    AGUARDANDO_CONSENTIMENTO --> AGUARDANDO_PROBLEMA: SIM / cadastro e prontuário criados
    AGUARDANDO_CONSENTIMENTO --> ENCERRADA_SEM_CONSENTIMENTO: NÃO

    AGUARDANDO_DECISAO_NOVA_CONSULTA --> AGUARDANDO_PROBLEMA: SIM
    AGUARDANDO_DECISAO_NOVA_CONSULTA --> CONCLUIDA: NÃO

    AGUARDANDO_PROBLEMA --> AGUARDANDO_DATA_HORA: queixa classificada e registrada
    AGUARDANDO_PROBLEMA --> AGUARDANDO_CONFIRMACAO_SUGESTAO: EMERGENCIA / oferece o 1º horário livre
    note right of AGUARDANDO_PROBLEMA
        Sinais de alarme: texto fixo de emergência
        e aviso imediato ao consultório
    end note

    AGUARDANDO_DATA_HORA --> CONCLUIDA: horário livre / consulta agendada
    AGUARDANDO_DATA_HORA --> AGUARDANDO_CONFIRMACAO_SUGESTAO: ocupado / sugere o mais próximo
    AGUARDANDO_CONFIRMACAO_SUGESTAO --> CONCLUIDA: SIM / consulta agendada
    AGUARDANDO_CONFIRMACAO_SUGESTAO --> AGUARDANDO_CONFIRMACAO_SUGESTAO: outra data ocupada
    AGUARDANDO_CONFIRMACAO_SUGESTAO --> AGUARDANDO_DATA_HORA: NÃO

    AGUARDANDO_NOME --> ENCAMINHADA_ATENDIMENTO_HUMANO: N respostas inválidas
    AGUARDANDO_PROBLEMA --> ENCAMINHADA_ATENDIMENTO_HUMANO: N respostas inválidas
    AGUARDANDO_DATA_HORA --> ENCAMINHADA_ATENDIMENTO_HUMANO: inválidas ou sem horário livre

    CONCLUIDA --> AGUARDANDO_RG: nova mensagem (cortesias são ignoradas)
    ENCERRADA_SEM_CONSENTIMENTO --> AGUARDANDO_RG: nova mensagem
    ENCAMINHADA_ATENDIMENTO_HUMANO --> AGUARDANDO_RG: após a expiração (silêncio até lá)

    note left of AGUARDANDO_RG
        Qualquer etapa sem interação por
        conversa.expiracao_minutos expira
        e recomeça do início
    end note
```

## 4. Sequência: paciente novo

```mermaid
sequenceDiagram
    autonumber
    actor P as Paciente
    participant M as Meta (WhatsApp Cloud API)
    participant W as Webhook (FastAPI)
    participant F as Fila + ConsumidorFila
    participant C as ConduzirConversaService
    participant D as Conversa (domínio)
    participant BD as PostgreSQL
    participant IA as Claude (Anthropic)
    participant N as NotificarConsultorioService
    actor R as Recepção

    P->>M: "Oi, quero marcar uma consulta"
    M->>W: POST /webhook/whatsapp (X-Hub-Signature-256)
    W->>W: valida HMAC do corpo bruto
    W->>BD: grava mensagem (texto cifrado, wa_message_id único)
    W->>F: enfileira mensagem_id
    W-->>M: 200 OK (rápido)
    F->>C: processa (trava por número)
    C->>D: Conversa.iniciar
    C-->>M: boas-vindas: pede RG e UF
    M-->>P: mensagem

    P->>M: "12.345.678-9 SP"
    M->>W: webhook
    W->>F: enfileira
    F->>C: processa
    C->>D: registrar_resposta → BuscarPaciente
    C->>BD: busca por rg_hash = HMAC(RG + UF)
    BD-->>C: não encontrado
    C->>D: paciente_nao_encontrado → AGUARDANDO_NOME
    C-->>P: "Qual é o seu nome completo?"

    P->>C: "Maria da Silva" (via Meta, webhook e fila)
    C-->>P: "Qual é a sua data de nascimento?"
    P->>C: "15/03/1990"
    C-->>P: pedido de consentimento LGPD
    P->>C: "Sim"
    C->>D: CadastrarPaciente
    C->>BD: paciente (dados cifrados) + telefone + prontuário PR-000001
    C-->>P: "Cadastro concluído! Qual é o problema?"

    P->>C: "Estou com dor de dente ao mastigar"
    C->>D: ClassificarQueixa
    C->>C: DetectorSinaisAlarme (sem alarme)
    C->>IA: só o texto da queixa + catálogo (saída estruturada)
    IA-->>C: DOR_DE_DENTE, confiança 0,9
    C->>BD: queixa_relatada (texto cifrado, URGENCIA)
    C-->>P: "Para quando você gostaria de agendar?"

    P->>C: "Amanhã às 10h"
    C->>C: interpretador local (regex) e, se preciso, Claude
    C->>BD: monta a Agenda (consultas e bloqueios)
    C->>C: Agenda.resolver → horário livre
    C->>BD: consulta AGENDADA (índice único parcial em inicio)
    C->>BD: commit + evento ConsultaAgendada
    C-->>P: "Consulta agendada para terça, 17/11 às 10:00"
    BD-->>F: evento publicado após o commit
    F->>N: ConsultaAgendada
    N->>R: template novo_agendamento (WhatsApp)
    N->>R: e-mail (se SMTP configurado) e log
```

## 5. Sequência: paciente existente

```mermaid
sequenceDiagram
    autonumber
    actor P as Paciente
    participant C as ConduzirConversaService
    participant I as IdentificarPacienteService
    participant BD as PostgreSQL
    participant Q as RegistrarQueixaService
    participant A as AgendarConsultaService
    participant N as NotificarConsultorioService
    actor R as Recepção

    P->>C: "Oi" (via Meta, webhook e fila)
    C-->>P: boas-vindas: pede RG e UF
    P->>C: "MG 12.345.678"
    C->>I: IdentificarPacienteCommand(documento, wa_id)
    I->>BD: busca por rg_hash
    BD-->>I: paciente + prontuário
    I->>BD: vincula o número do WhatsApp, se novo
    I-->>C: primeiro nome, consulta futura

    alt já tem consulta futura
        C-->>P: "Você já tem consulta em 25/11 às 10:00. Deseja agendar outra?"
        P->>C: "Sim"
    end

    C-->>P: "Olá, Maria! Qual é o problema?"
    P->>C: "Quero fazer uma limpeza"
    C->>Q: RegistrarQueixaCommand
    Q-->>C: LIMPEZA_PROFILAXIA, ROTINA
    C-->>P: "Para quando você gostaria de agendar?"
    P->>C: "Sexta de manhã"
    C->>C: Agenda.resolver(data = sexta, período = manhã)
    C->>A: AgendarConsultaCommand(primeiro horário livre da manhã)
    A->>BD: consulta AGENDADA
    C-->>P: "Consulta agendada para sexta, 20/11 às 08:00"
    BD-->>N: ConsultaAgendada (após o commit)
    N->>R: aviso pelo WhatsApp, e-mail e log
```

## 6. Sequência: horário ocupado e conflito de concorrência

O índice único parcial `ux_consulta_inicio_agendada` impede duas consultas AGENDADAS no mesmo início; se outra conversa ganhar a corrida, o agente oferece o próximo horário livre.

```mermaid
sequenceDiagram
    autonumber
    actor P as Paciente
    participant C as ConduzirConversaService
    participant AG as Agenda (domínio)
    participant A as AgendarConsultaService
    participant BD as PostgreSQL

    P->>C: "Quinta às 15h"
    C->>AG: resolver(quinta 15:00)
    AG-->>C: HorarioSugerido(quinta 15:30, HORARIO_INDISPONIVEL)

    alt confirmar_sugestao = true (padrão)
        C-->>P: "Esse horário não está disponível. O mais próximo é quinta às 15:30. Posso confirmar?"
        alt paciente responde SIM
            P->>C: "Sim"
            C->>A: AgendarConsultaCommand(quinta 15:30)
        else paciente sugere outra data
            P->>C: "Sexta às 9h"
            C->>AG: resolver(sexta 09:00)
        else paciente responde NÃO
            P->>C: "Não"
            C-->>P: "Para quando você gostaria de agendar?"
        end
    else confirmar_sugestao = false
        C->>A: AgendarConsultaCommand(quinta 15:30) direto
    end

    A->>BD: INSERT consulta (status AGENDADA)
    alt outro paciente ocupou o horário no meio-tempo
        BD-->>A: violação de ux_consulta_inicio_agendada
        A-->>C: HorarioIndisponivelError
        C->>BD: recarrega a agenda
        C->>AG: alternativa_para(quinta 15:30)
        AG-->>C: HorarioSugerido(quinta 16:00)
        C-->>P: "Esse horário não está disponível. O mais próximo é quinta às 16:00. Posso confirmar?"
    else horário continua livre
        BD-->>A: ok
        C-->>P: "Consulta agendada para quinta às 15:30"
    end
```

## 7. Sequência: queixa com sinais de alarme

```mermaid
sequenceDiagram
    autonumber
    actor P as Paciente
    participant C as ConduzirConversaService
    participant Q as RegistrarQueixaService
    participant S as DetectorSinaisAlarme
    participant IA as Claude (Anthropic)
    participant BD as PostgreSQL
    participant F as Fila de eventos
    participant N as NotificarConsultorioService
    actor R as Recepção

    P->>C: "Meu rosto está inchado e estou com febre alta"
    C->>Q: RegistrarQueixaCommand
    Q->>S: palavras_alarme do config/odonto.yaml
    S-->>Q: sinais: rosto inchado, febre alta
    Q->>IA: classificar (texto da queixa e catálogo)
    IA-->>Q: CELULITE_ABSCESSO_FACE, sinais_alarme = true
    Note over Q: Prioridade final = a mais alta entre<br/>catálogo, IA e detector → EMERGENCIA
    Q->>BD: queixa_relatada (EMERGENCIA) + evento EmergenciaDetectada
    Q-->>C: queixa registrada
    C->>C: OferecerPrimeiroHorario: Agenda.primeiro_livre
    C-->>P: texto fixo de emergência: pronto-socorro ou SAMU (192)
    C-->>P: "O primeiro horário livre é hoje às 14:00. Posso confirmar?"
    BD-->>F: EmergenciaDetectada (após o commit)
    F->>N: notificar
    par canais independentes
        N->>R: template alerta_consultorio (WhatsApp)
    and
        N->>R: e-mail
    and
        N->>N: log
    end
    Note over N: Falha em um canal não impede os outros
    P->>C: "Sim"
    C->>BD: consulta AGENDADA (prioridade EMERGENCIA) + ConsultaAgendada
    C-->>P: "Consulta agendada para hoje às 14:00"
```

## 8. Fluxo de dados nível 0 (contexto)

Para a IA vão apenas o texto da queixa ou da data; nome, RG e telefone nunca são enviados.

```mermaid
%% Diagrama de contexto (DFD nível 0): o sistema como um único processo.
flowchart LR
    paciente(["Paciente"])
    meta(["Meta<br/>WhatsApp Cloud API"])
    claude(["Anthropic<br/>Claude"])
    transcricao(["OpenAI<br/>transcrição de áudio"])
    smtp(["Servidor SMTP"])
    recepcao(["Consultório<br/>recepção e dentista"])

    sistema(("0<br/>Agente WhatsApp<br/>do consultório"))

    paciente -- "texto e áudio" --> meta
    meta -- "respostas automáticas" --> paciente
    meta -- "webhook: mensagens assinadas (HMAC)" --> sistema
    sistema -- "mensagens de texto e templates" --> meta
    sistema -- "download de mídia" --> meta
    sistema -- "só o texto da queixa ou da data" --> claude
    claude -- "código do catálogo, prioridade, data e hora" --> sistema
    sistema -- "áudio do paciente" --> transcricao
    transcricao -- "transcrição em pt" --> sistema
    sistema -- "aviso de agendamento e alertas" --> smtp
    smtp -- "e-mail" --> recepcao
    meta -- "template novo_agendamento e alerta" --> recepcao
    recepcao -- "API: agenda, bloqueios, prontuário, reclassificação" --> sistema
    sistema -- "agenda, pacientes, catálogo" --> recepcao
```

## 9. Fluxo de dados nível 1

Processos numerados e depósitos de dados (tabelas).

```mermaid
%% DFD nível 1: processos (círculos) e depósitos de dados (tabelas do PostgreSQL).
flowchart LR
    meta(["Meta"])
    claude(["Claude"])
    openai(["OpenAI"])
    recepcao(["Recepção"])
    smtp(["SMTP"])

    p1(("1<br/>Receber mensagens"))
    p2(("2<br/>Conduzir conversa"))
    p3(("3<br/>Identificar e<br/>cadastrar paciente"))
    p4(("4<br/>Registrar queixa"))
    p5(("5<br/>Agendar consulta"))
    p6(("6<br/>Notificar consultório"))
    p7(("7<br/>Gerenciar agenda<br/>e prontuário"))
    p8(("8<br/>Manutenção:<br/>expirar e expurgar"))

    d1[("D1 mensagem")]
    d2[("D2 conversa")]
    d3[("D3 paciente e<br/>paciente_telefone")]
    d4[("D4 prontuario e<br/>queixa_relatada")]
    d5[("D5 problema_odontologico")]
    d6[("D6 consulta e<br/>bloqueio_agenda")]

    meta -- "webhook" --> p1
    p1 -- "texto cifrado, pendente" --> d1
    p1 -- "id da mensagem (fila em memória)" --> p2
    d1 -- "mensagem pendente" --> p2
    p2 -- "midia_id" --> meta
    p2 -- "áudio" --> openai
    openai -- "transcrição" --> p2
    p2 <-- "etapa e dados cifrados" --> d2
    p2 -- "RG + UF, nome, nascimento" --> p3
    p3 <-- "rg_hash, dados cifrados" --> d3
    p3 -- "abre prontuário" --> d4
    p2 -- "texto da queixa" --> p4
    d5 -- "catálogo ativo" --> p4
    p4 -- "texto da queixa" --> claude
    claude -- "código e confiança" --> p4
    p4 -- "queixa classificada" --> d4
    p2 -- "data e hora" --> claude
    p2 -- "preferência de horário" --> p5
    d6 -- "ocupação" --> p5
    p5 -- "consulta AGENDADA" --> d6
    p2 -- "respostas" --> meta
    p4 -- "EmergenciaDetectada" --> p6
    p5 -- "ConsultaAgendada" --> p6
    p6 -- "template" --> meta
    p6 -- "e-mail" --> smtp
    recepcao -- "X-Admin-Token" --> p7
    p7 <--> d6
    p7 <--> d4
    p7 -- "consulta (busca por RG)" --> d3
    p8 -- "encerra conversas inativas" --> d2
    p8 -- "apaga texto das mensagens > 90 dias (configurável)" --> d1
```

## 10. Implantação

Container único com aplicação e banco no host Linux; o PostgreSQL escuta só em 127.0.0.1 dentro do container.

```mermaid
flowchart TB
    internet(["Internet"])
    meta(["Meta<br/>graph.facebook.com"])
    apis(["api.anthropic.com<br/>api.openai.com<br/>SMTP"])

    subgraph HOST["Host Linux (servidor do consultório ou VPS)"]
        tunel["Túnel HTTPS<br/>Cloudflare Tunnel, ngrok<br/>ou Nginx/Caddy + Let's Encrypt"]
        odonto_sh["odonto.sh<br/>setup, start, backup..."]
        envfile[".env (chmod 600)<br/>segredos e chaves"]
        configdir["config/odonto.yaml<br/>montado somente leitura"]
        backups["backups/*.dump<br/>pg_dump -Fc (cron diário)"]

        subgraph CT["Container agent-whatsapp-odonto-py (imagem sobre postgres:18)"]
            entry["docker/entrypoint.sh (PID 1)<br/>1. initdb na 1ª execução<br/>2. pg_ctl start<br/>3. usuário e banco<br/>4. alembic upgrade head<br/>5. python -m odonto"]
            pg[("PostgreSQL 18<br/>127.0.0.1:5432")]
            app["Uvicorn + FastAPI<br/>1 worker, 0.0.0.0:8080<br/>fila, consumidor, APScheduler"]
            entry --> pg
            entry --> app
            app -- "psycopg 3" --> pg
        end

        volume[("Volume agent-whatsapp-odonto-py-dados<br/>/var/lib/postgresql/odonto<br/>pgdata e logs")]
    end

    internet -- "HTTPS 443" --> tunel
    meta -- "webhook HTTPS" --> tunel
    tunel -- "http://127.0.0.1:PORTA → 8080" --> app
    app -- "HTTPS de saída" --> meta
    app -- "HTTPS / SMTP de saída" --> apis
    pg --- volume
    configdir -. "bind mount :ro" .-> app
    envfile -. "--env-file" .-> CT
    odonto_sh -- "docker run, exec, pg_dump" --> CT
    odonto_sh --> backups
```
