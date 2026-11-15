"""Casos de uso da recepção (agenda, pacientes) e rotinas de manutenção."""

from datetime import date, timedelta
from uuid import uuid7

import pytest

from odonto.aplicacao.casos_de_uso.consultar_pacientes_service import ConsultarPacientesService
from odonto.aplicacao.casos_de_uso.gerenciar_agenda_service import GerenciarAgendaService
from odonto.aplicacao.casos_de_uso.manutencao_service import (
    ExpirarConversasService,
    ExpurgarMensagensService,
)
from odonto.aplicacao.casos_de_uso.receber_mensagens_service import ReenfileirarPendentesService
from odonto.aplicacao.configuracao import ConfiguracaoRetencao
from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaCommand, CriarBloqueioCommand
from odonto.dominio.excecoes import DadoInvalidoError, HorarioIndisponivelError
from odonto.dominio.modelo.conversa import RegrasConversa
from odonto.dominio.modelo.enums import (
    DirecaoMensagem,
    EtapaConversa,
    OrigemAgendamento,
    StatusConsulta,
)
from tests.aplicacao.fakes import CONFIG_AGENDA, Ambiente
from tests.apoio import em

SEXTA = date(2026, 11, 20)


def agenda_de(ambiente: Ambiente) -> GerenciarAgendaService:
    return GerenciarAgendaService(
        uow=ambiente.uow, relogio=ambiente.relogio, configuracao=CONFIG_AGENDA
    )


class TestAgenda:
    async def test_recepcao_agenda_sem_antecedencia_minima(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        resumo = await ambiente.agendar.executar(
            AgendarConsultaCommand(
                paciente_id=paciente.id,
                inicio=em(2026, 11, 18, 9, 30),
                origem=OrigemAgendamento.RECEPCAO,
            )
        )
        assert resumo.nome_paciente == "Maria da Silva"
        assert ambiente.publicador.eventos  # ConsultaAgendada publicada após o commit

    async def test_horario_ocupado_e_recusado(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        ambiente.ocupar(em(2026, 11, 20, 10, 0))
        with pytest.raises(HorarioIndisponivelError):
            await ambiente.agendar.executar(
                AgendarConsultaCommand(
                    paciente_id=paciente.id,
                    inicio=em(2026, 11, 20, 10, 0),
                    origem=OrigemAgendamento.RECEPCAO,
                )
            )

    async def test_visao_do_dia_com_consultas_bloqueios_e_livres(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        await ambiente.agendar.executar(
            AgendarConsultaCommand(
                paciente_id=paciente.id,
                inicio=em(2026, 11, 20, 8, 0),
                origem=OrigemAgendamento.RECEPCAO,
            )
        )
        ambiente.bloquear(em(2026, 11, 20, 13, 0), em(2026, 11, 20, 18, 0))

        visao = await agenda_de(ambiente).consultar(SEXTA, SEXTA)

        (consulta,) = visao.consultas
        assert consulta.nome_paciente == "Maria da Silva"
        assert len(visao.bloqueios) == 1
        # 8h às 12h em grade de 30 min = 8 horários, menos o ocupado.
        assert len(visao.horarios_livres) == 7
        assert em(2026, 11, 20, 8, 0) not in visao.horarios_livres

    async def test_periodo_invalido(self) -> None:
        agenda = agenda_de(Ambiente())
        with pytest.raises(DadoInvalidoError):
            await agenda.consultar(SEXTA, SEXTA - timedelta(days=1))
        with pytest.raises(DadoInvalidoError):
            await agenda.consultar(SEXTA, SEXTA + timedelta(days=62))

    async def test_cancelar_libera_o_horario(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        inicio = em(2026, 11, 20, 8, 0)
        consulta = await ambiente.agendar.executar(
            AgendarConsultaCommand(
                paciente_id=paciente.id, inicio=inicio, origem=OrigemAgendamento.RECEPCAO
            )
        )
        agenda = agenda_de(ambiente)
        cancelada = await agenda.cancelar(consulta.id)
        assert cancelada.status is StatusConsulta.CANCELADA
        visao = await agenda.consultar(SEXTA, SEXTA)
        assert inicio in visao.horarios_livres

    async def test_consulta_inexistente(self) -> None:
        with pytest.raises(RecursoNaoEncontradoError):
            await agenda_de(Ambiente()).marcar_falta(uuid7())

    async def test_bloqueio_informa_consultas_afetadas_sem_cancelar(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        await ambiente.agendar.executar(
            AgendarConsultaCommand(
                paciente_id=paciente.id,
                inicio=em(2026, 11, 20, 9, 0),
                origem=OrigemAgendamento.RECEPCAO,
            )
        )
        agenda = agenda_de(ambiente)
        criado = await agenda.criar_bloqueio(
            CriarBloqueioCommand(
                inicio=em(2026, 11, 20, 8, 0), fim=em(2026, 11, 20, 12, 0), motivo="Curso"
            )
        )
        (afetada,) = criado.consultas_afetadas
        assert afetada.status is StatusConsulta.AGENDADA
        await agenda.remover_bloqueio(criado.bloqueio.id)
        with pytest.raises(RecursoNaoEncontradoError):
            await agenda.remover_bloqueio(criado.bloqueio.id)


class TestPacientes:
    async def test_busca_por_nome_sem_acento_e_por_partes(self) -> None:
        ambiente = Ambiente()
        await ambiente.cadastrar_paciente_existente(nome="Márcia Conceição")
        servico = ConsultarPacientesService(uow=ambiente.uow, cifrador=ambiente.cifrador)
        (encontrado,) = await servico.buscar_por_nome("marcia conc")
        assert encontrado.numero_prontuario == "PR-000001"
        assert await servico.buscar_por_nome("joana") == []
        with pytest.raises(DadoInvalidoError):
            await servico.buscar_por_nome(" a ")

    async def test_busca_por_documento_e_prontuario(self) -> None:
        ambiente = Ambiente()
        paciente = await ambiente.cadastrar_paciente_existente()
        servico = ConsultarPacientesService(uow=ambiente.uow, cifrador=ambiente.cifrador)
        resumo = await servico.buscar_por_documento("12345678-9", "SP")
        assert resumo is not None
        assert resumo.id == paciente.id
        detalhe = await servico.prontuario(paciente.id)
        assert detalhe.numero == "PR-000001"
        assert detalhe.queixas == detalhe.consultas == ()


class TestManutencao:
    async def test_expira_conversas_paradas(self) -> None:
        ambiente = Ambiente()
        await ambiente.paciente_diz("oi")
        await ambiente.paciente_diz("12345678 SP")
        ambiente.relogio.avancar(timedelta(hours=3))
        servico = ExpirarConversasService(
            uow=ambiente.uow, relogio=ambiente.relogio, regras=RegrasConversa()
        )
        assert await servico.executar() == 1
        assert ambiente.conversa.encerrada
        assert ambiente.conversa.dados.documento is None
        assert await servico.executar() == 0

    async def test_expurgo_apaga_mensagens_e_conversas_antigas(self) -> None:
        ambiente = Ambiente()
        for texto in ("oi", "12345678 SP", "Maria da Silva", "15/03/1990", "não"):
            await ambiente.paciente_diz(texto)
        assert ambiente.conversa.etapa is EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO
        servico = ExpurgarMensagensService(
            uow=ambiente.uow, relogio=ambiente.relogio, configuracao=ConfiguracaoRetencao()
        )
        resultado = await servico.executar()
        assert (resultado.mensagens, resultado.conversas) == (0, 0)

        ambiente.relogio.avancar(timedelta(days=91))
        resultado = await servico.executar()
        assert resultado.mensagens == 10
        assert resultado.conversas == 1
        assert ambiente.banco.estado.mensagens == {}

    async def test_reenfileira_mensagens_pendentes(self) -> None:
        ambiente = Ambiente()
        await ambiente.paciente_diz("oi")
        (recebida,) = ambiente.mensagens(DirecaoMensagem.RECEBIDA)
        ambiente.banco.estado.mensagens[recebida.id].processada_em = None
        servico = ReenfileirarPendentesService(uow=ambiente.uow, fila=ambiente.fila)
        assert await servico.executar() == 1
        assert ambiente.fila.itens[0].mensagem_id == recebida.id
