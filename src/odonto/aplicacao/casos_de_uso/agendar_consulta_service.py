"""Agendamento de consulta (pelo WhatsApp ou pela recepção)."""

import logging
from datetime import timedelta

from odonto.aplicacao.casos_de_uso.montador_agenda import montar_agenda
from odonto.aplicacao.configuracao import ConfiguracaoAgenda
from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaCommand, ConsultaResumo
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade

logger = logging.getLogger(__name__)


class AgendarConsultaService:
    def __init__(
        self, *, uow: UnidadeDeTrabalho, relogio: Relogio, configuracao: ConfiguracaoAgenda
    ) -> None:
        self._uow = uow
        self._relogio = relogio
        self._configuracao = configuracao

    async def executar(self, comando: AgendarConsultaCommand) -> ConsultaResumo:
        agora = self._relogio.agora()
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_id(comando.paciente_id)
            if paciente is None:
                raise RecursoNaoEncontradoError("Paciente", comando.paciente_id)
            prontuario = queixa = None
            if comando.queixa_id is not None:
                prontuario = await uow.prontuarios.buscar_por_queixa(comando.queixa_id)
                if prontuario is None or prontuario.paciente_id != paciente.id:
                    raise RecursoNaoEncontradoError("Queixa do paciente", comando.queixa_id)
                queixa = prontuario.buscar_queixa(comando.queixa_id)
            prioridade = comando.prioridade or (queixa.prioridade if queixa else Prioridade.ROTINA)

            agenda = await montar_agenda(
                uow, self._configuracao, comando.inicio, comando.inicio + timedelta(hours=1)
            )
            horario = agenda.validar(
                comando.inicio,
                agora,
                respeitar_antecedencia=comando.origem is OrigemAgendamento.WHATSAPP,
            )
            consulta = Consulta.agendar(
                paciente_id=paciente.id,
                queixa_id=comando.queixa_id,
                horario=horario,
                prioridade=prioridade,
                origem=comando.origem,
                momento=agora,
            )
            await uow.consultas.adicionar(consulta)
            if prontuario is not None and comando.queixa_id is not None:
                prontuario.vincular_consulta(comando.queixa_id, consulta.id)
                await uow.prontuarios.salvar(prontuario)
            await uow.commit()
        logger.info(
            "consulta agendada",
            extra={
                "consulta_id": str(consulta.id),
                "origem": comando.origem.value,
                "prioridade": prioridade.value,
            },
        )
        return ConsultaResumo.de(
            consulta,
            nome_paciente=paciente.nome,
            problema=queixa.problema.nome if queixa else None,
        )
