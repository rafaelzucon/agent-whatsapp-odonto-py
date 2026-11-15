"""Consulta: agendamento e transições de status."""

from datetime import timedelta
from uuid import uuid7

import pytest

from odonto.dominio.excecoes import TransicaoInvalidaError
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade, StatusConsulta
from odonto.dominio.modelo.eventos import ConsultaAgendada
from odonto.dominio.modelo.valores import Horario
from tests.apoio import AGORA, em

INICIO = em(2026, 11, 20, 10, 0)
DEPOIS_DO_INICIO = INICIO + timedelta(minutes=5)


def agendar() -> Consulta:
    return Consulta.agendar(
        paciente_id=uuid7(),
        queixa_id=uuid7(),
        horario=Horario.com_duracao(INICIO, timedelta(minutes=30)),
        prioridade=Prioridade.URGENCIA,
        origem=OrigemAgendamento.WHATSAPP,
        momento=AGORA,
    )


def test_agendar_registra_evento() -> None:
    consulta = agendar()
    assert consulta.status is StatusConsulta.AGENDADA
    assert consulta.ativa
    assert consulta.inicio == INICIO
    (evento,) = consulta.coletar_eventos()
    assert isinstance(evento, ConsultaAgendada)
    assert evento.consulta_id == consulta.id
    assert evento.inicio == INICIO
    assert evento.prioridade is Prioridade.URGENCIA
    assert evento.origem is OrigemAgendamento.WHATSAPP


def test_cancelar() -> None:
    consulta = agendar()
    consulta.cancelar(AGORA)
    assert consulta.status is StatusConsulta.CANCELADA
    assert not consulta.ativa


@pytest.mark.parametrize(
    ("marcar", "status"),
    [
        (Consulta.marcar_realizada, StatusConsulta.REALIZADA),
        (Consulta.marcar_falta, StatusConsulta.FALTOU),
    ],
)
def test_realizada_ou_falta_depois_do_inicio(marcar: object, status: StatusConsulta) -> None:
    consulta = agendar()
    marcar(consulta, DEPOIS_DO_INICIO)  # type: ignore[operator]
    assert consulta.status is status
    assert consulta.atualizada_em == DEPOIS_DO_INICIO


@pytest.mark.parametrize("marcar", [Consulta.marcar_realizada, Consulta.marcar_falta])
def test_nao_marca_consulta_que_nao_comecou(marcar: object) -> None:
    with pytest.raises(TransicaoInvalidaError):
        marcar(agendar(), AGORA)  # type: ignore[operator]


@pytest.mark.parametrize(
    "transicao",
    [
        lambda c: c.cancelar(DEPOIS_DO_INICIO),
        lambda c: c.marcar_realizada(DEPOIS_DO_INICIO),
        lambda c: c.marcar_falta(DEPOIS_DO_INICIO),
    ],
)
def test_so_consultas_agendadas_mudam_de_status(transicao: object) -> None:
    consulta = agendar()
    consulta.cancelar(AGORA)
    with pytest.raises(TransicaoInvalidaError):
        transicao(consulta)  # type: ignore[operator]
    assert consulta.status is StatusConsulta.CANCELADA
