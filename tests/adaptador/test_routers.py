"""Routers com casos de uso falsos: o router só traduz HTTP ↔ portas de entrada."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from odonto.adaptador.entrada.web import agenda, pacientes, webhook
from odonto.adaptador.entrada.web.assinatura_webhook import calcular_assinatura
from odonto.adaptador.entrada.web.dependencias import CasosDeUsoWeb, ConfiguracaoWeb
from odonto.adaptador.entrada.web.documentacao import criar_router_documentacao
from odonto.adaptador.entrada.web.erros import registrar_tratadores_de_erro
from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.agenda import (
    AgendarConsultaCommand,
    ConsultaResumo,
    VisaoAgenda,
)
from odonto.aplicacao.portas.entrada.conversa import (
    MensagemRecebidaCommand,
    ResultadoRecebimento,
)
from odonto.aplicacao.portas.entrada.prontuario import ReclassificarQueixaCommand
from odonto.dominio.excecoes import HorarioIndisponivelError, MotivoIndisponibilidade
from odonto.dominio.modelo.enums import (
    OrigemAgendamento,
    Prioridade,
    StatusConsulta,
)
from tests.apoio import em, problema

TOKEN = "token-admin-de-teste-123"
ADMIN = {"X-Admin-Token": TOKEN}
CONFIG = ConfiguracaoWeb(
    verify_token="verificacao", app_secret="segredo", admin_token=TOKEN, phone_number_id="PNID"
)


def resumo_consulta(**alteracoes: Any) -> ConsultaResumo:
    valores: dict[str, Any] = {
        "id": uuid4(),
        "paciente_id": uuid4(),
        "nome_paciente": "Maria Souza",
        "queixa_id": None,
        "problema": None,
        "inicio": em(2026, 11, 20, 10),
        "fim": em(2026, 11, 20, 10, 30),
        "status": StatusConsulta.AGENDADA,
        "prioridade": Prioridade.ROTINA,
        "origem": OrigemAgendamento.RECEPCAO,
    }
    return ConsultaResumo(**(valores | alteracoes))


@dataclass
class Falso:
    """Um objeto que registra as chamadas e devolve respostas programadas."""

    respostas: dict[str, Any] = field(default_factory=dict)
    chamadas: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def __getattr__(self, nome: str) -> Any:
        if nome.startswith("_") or nome in {"respostas", "chamadas"}:
            raise AttributeError(nome)

        async def metodo(*args: Any, **kwargs: Any) -> Any:
            self.chamadas.append((nome, args + tuple(kwargs.values())))
            resposta = self.respostas.get(nome)
            if isinstance(resposta, Exception):
                raise resposta
            return resposta

        return metodo


@dataclass
class Cenario:
    cliente: TestClient
    receber: Falso
    agendar: Falso
    agenda: Falso
    pacientes: Falso
    reclassificar: Falso
    catalogo: Falso


@pytest.fixture
def cenario() -> Iterator[Cenario]:
    falsos = [Falso() for _ in range(6)]
    falsos[0].respostas["executar"] = ResultadoRecebimento(novas=1, duplicadas=0, ignoradas=0)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    registrar_tratadores_de_erro(app)
    for router in (webhook.router, agenda.router, pacientes.router):
        app.include_router(router)
    app.include_router(criar_router_documentacao(app))
    app.state.configuracao_web = CONFIG
    app.state.casos_de_uso = CasosDeUsoWeb(
        receber_mensagens=falsos[0],  # type: ignore[arg-type]
        agendar_consulta=falsos[1],  # type: ignore[arg-type]
        gerenciar_agenda=falsos[2],  # type: ignore[arg-type]
        consultar_pacientes=falsos[3],  # type: ignore[arg-type]
        reclassificar_queixa=falsos[4],  # type: ignore[arg-type]
        consultar_catalogo=falsos[5],  # type: ignore[arg-type]
    )
    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield Cenario(cliente, *falsos)


# --- Webhook -----------------------------------------------------------------------------------

CORPO = (
    b'{"object":"whatsapp_business_account","entry":[{"changes":[{"field":"messages","value":'
    b'{"metadata":{"phone_number_id":"PNID"},"messages":[{"from":"5511987654321","id":"wamid.1",'
    b'"timestamp":"1795000000","type":"text","text":{"body":"oi"}}]}}]}]}'
)


def test_handshake_devolve_o_desafio(cenario: Cenario) -> None:
    resposta = cenario.cliente.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verificacao", "hub.challenge": "42"},
    )

    assert resposta.status_code == 200
    assert resposta.text == "42"
    assert resposta.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "verificacao", "hub.challenge": "42"},
        {},
    ],
)
def test_handshake_invalido_e_proibido(cenario: Cenario, params: dict[str, str]) -> None:
    assert cenario.cliente.get("/webhook/whatsapp", params=params).status_code == 403


def test_webhook_com_assinatura_valida_chama_o_caso_de_uso(cenario: Cenario) -> None:
    resposta = cenario.cliente.post(
        "/webhook/whatsapp",
        content=CORPO,
        headers={"X-Hub-Signature-256": calcular_assinatura(CORPO, "segredo")},
    )

    assert resposta.status_code == 200
    [(_, (comandos,))] = cenario.receber.chamadas
    [comando] = comandos
    assert isinstance(comando, MensagemRecebidaCommand)
    assert (comando.wa_message_id, comando.texto) == ("wamid.1", "oi")


def test_webhook_com_assinatura_invalida_e_recusado(cenario: Cenario) -> None:
    resposta = cenario.cliente.post(
        "/webhook/whatsapp",
        content=CORPO,
        headers={"X-Hub-Signature-256": calcular_assinatura(CORPO, "outro")},
    )

    assert resposta.status_code == 401
    assert cenario.receber.chamadas == []


def test_payload_inesperado_responde_200_sem_processar(cenario: Cenario) -> None:
    corpo = b'{"isso": "nao e da meta"}'

    resposta = cenario.cliente.post(
        "/webhook/whatsapp",
        content=corpo,
        headers={"X-Hub-Signature-256": calcular_assinatura(corpo, "segredo")},
    )

    assert resposta.status_code == 200
    assert cenario.receber.chamadas == []


# --- API administrativa ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metodo", "url"),
    [
        ("GET", "/api/agenda?inicio=2026-11-20&fim=2026-11-21"),
        ("GET", "/api/catalogo-problemas"),
        ("GET", "/api/pacientes?nome=Maria"),
        ("POST", f"/api/consultas/{uuid4()}/cancelar"),
    ],
)
def test_api_exige_token(cenario: Cenario, metodo: str, url: str) -> None:
    assert cenario.cliente.request(metodo, url).status_code == 401
    assert cenario.cliente.request(metodo, url, headers={"X-Admin-Token": "x"}).status_code == 401


def test_consulta_a_agenda(cenario: Cenario) -> None:
    consulta = resumo_consulta()
    cenario.agenda.respostas["consultar"] = VisaoAgenda(
        inicio=date(2026, 11, 20),
        fim=date(2026, 11, 20),
        consultas=(consulta,),
        bloqueios=(),
        horarios_livres=(em(2026, 11, 20, 8),),
    )

    resposta = cenario.cliente.get(
        "/api/agenda", params={"inicio": "2026-11-20", "fim": "2026-11-20"}, headers=ADMIN
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["consultas"][0]["id"] == str(consulta.id)
    assert corpo["consultas"][0]["status"] == "AGENDADA"
    assert corpo["horarios_livres"] == ["2026-11-20T08:00:00-03:00"]
    assert cenario.agenda.chamadas == [("consultar", (date(2026, 11, 20), date(2026, 11, 20)))]


def test_agendamento_manual_tem_origem_recepcao(cenario: Cenario) -> None:
    paciente_id = uuid4()
    cenario.agendar.respostas["executar"] = resumo_consulta(paciente_id=paciente_id)

    resposta = cenario.cliente.post(
        "/api/consultas",
        json={"paciente_id": str(paciente_id), "inicio": "2026-11-20T10:00:00-03:00"},
        headers=ADMIN,
    )

    assert resposta.status_code == 201
    [(_, (comando,))] = cenario.agendar.chamadas
    assert isinstance(comando, AgendarConsultaCommand)
    assert comando.origem is OrigemAgendamento.RECEPCAO
    assert comando.inicio == datetime(2026, 11, 20, 13, tzinfo=UTC)


def test_agendamento_sem_fuso_e_rejeitado_com_problem_json(cenario: Cenario) -> None:
    resposta = cenario.cliente.post(
        "/api/consultas",
        json={"paciente_id": str(uuid4()), "inicio": "2026-11-20T10:00:00"},
        headers=ADMIN,
    )

    assert resposta.status_code == 400
    assert resposta.headers["content-type"] == "application/problem+json"
    assert cenario.agendar.chamadas == []


def test_horario_indisponivel_vira_409(cenario: Cenario) -> None:
    cenario.agendar.respostas["executar"] = HorarioIndisponivelError(
        MotivoIndisponibilidade.OCUPADO, em(2026, 11, 20, 10)
    )

    resposta = cenario.cliente.post(
        "/api/consultas",
        json={"paciente_id": str(uuid4()), "inicio": "2026-11-20T10:00:00-03:00"},
        headers=ADMIN,
    )

    assert resposta.status_code == 409
    assert resposta.headers["content-type"] == "application/problem+json"
    assert resposta.json()["motivo"] == "OCUPADO"


def test_recurso_inexistente_vira_404(cenario: Cenario) -> None:
    cenario.agenda.respostas["cancelar"] = RecursoNaoEncontradoError("Consulta", uuid4())

    resposta = cenario.cliente.post(f"/api/consultas/{uuid4()}/cancelar", headers=ADMIN)

    assert resposta.status_code == 404
    assert resposta.json()["status"] == 404


def test_busca_paciente_exige_rg_e_uf_juntos(cenario: Cenario) -> None:
    resposta = cenario.cliente.get("/api/pacientes", params={"rg": "123"}, headers=ADMIN)

    assert resposta.status_code == 400
    assert resposta.json()["campo"] == "rg"


def test_busca_paciente_por_rg_sem_resultado(cenario: Cenario) -> None:
    resposta = cenario.cliente.get(
        "/api/pacientes", params={"rg": "12.345.678-9", "uf": "SP"}, headers=ADMIN
    )

    assert resposta.status_code == 200
    assert resposta.json() == []
    assert cenario.pacientes.chamadas == [("buscar_por_documento", ("12.345.678-9", "SP"))]


def test_reclassificacao_normaliza_o_codigo(cenario: Cenario) -> None:
    cenario.reclassificar.respostas["executar"] = RecursoNaoEncontradoError("Queixa", uuid4())
    queixa_id = uuid4()

    cenario.cliente.put(
        f"/api/queixas/{queixa_id}/classificacao",
        json={"codigo_problema": " pulpite ", "prioridade": "URGENCIA"},
        headers=ADMIN,
    )

    [(_, (comando,))] = cenario.reclassificar.chamadas
    assert comando == ReclassificarQueixaCommand(
        queixa_id=queixa_id, codigo_problema="PULPITE", prioridade=Prioridade.URGENCIA
    )


def test_catalogo(cenario: Cenario) -> None:
    itens: Sequence[Any] = [problema("CARIE", palavras_chave=("cárie",))]
    cenario.catalogo.respostas["listar"] = itens

    resposta = cenario.cliente.get("/api/catalogo-problemas", headers=ADMIN)

    assert resposta.json()[0]["codigo"] == "CARIE"
    assert resposta.json()[0]["palavras_chave"] == ["cárie"]


def test_documentacao_exige_token(cenario: Cenario) -> None:
    assert cenario.cliente.get("/docs").status_code == 401
    assert cenario.cliente.get("/openapi.json").status_code == 401
    assert cenario.cliente.get("/docs", params={"token": TOKEN}).status_code == 200
    esquema = cenario.cliente.get("/openapi.json", headers=ADMIN).json()
    assert "/api/agenda" in esquema["paths"]
    assert "/webhook/whatsapp" not in esquema["paths"]
