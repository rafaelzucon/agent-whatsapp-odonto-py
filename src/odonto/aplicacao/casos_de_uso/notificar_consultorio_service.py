"""Aviso ao consultório: novo agendamento e alertas, por todos os canais habilitados."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from odonto.aplicacao.configuracao import ConfiguracaoNotificacao
from odonto.aplicacao.mensagens import formatar_data_hora
from odonto.aplicacao.portas.saida.notificacao import (
    AlertaConsultorio,
    AvisoNovoAgendamento,
    CanalNotificacaoConsultorio,
    TipoAlerta,
)
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade
from odonto.dominio.modelo.eventos import (
    AtendimentoHumanoNecessario,
    ConsentimentoRecusado,
    ConsultaAgendada,
    EmergenciaDetectada,
    EventoDominio,
)
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.valores import WaId

logger = logging.getLogger(__name__)

type Envio = Callable[[CanalNotificacaoConsultorio], Awaitable[None]]


def _final(wa_id: WaId) -> str:
    return f"WhatsApp com final {wa_id.final}"


class NotificarConsultorioService:
    def __init__(
        self,
        *,
        uow: UnidadeDeTrabalho,
        canais: Sequence[CanalNotificacaoConsultorio],
        configuracao: ConfiguracaoNotificacao,
    ) -> None:
        self._uow = uow
        self._canais = tuple(canais)
        self._configuracao = configuracao

    async def notificar(self, evento: EventoDominio) -> None:
        match evento:
            case ConsultaAgendada(origem=OrigemAgendamento.RECEPCAO):
                return  # a própria recepção agendou
            case ConsultaAgendada():
                aviso = await self._aviso_agendamento(evento)
                if aviso is not None:
                    await self._enviar("novo_agendamento", lambda c: c.novo_agendamento(aviso))
                return
            case EmergenciaDetectada():
                alerta = await self._alerta_emergencia(evento)
            case ConsentimentoRecusado(wa_id=wa_id):
                alerta = AlertaConsultorio(
                    tipo=TipoAlerta.CONSENTIMENTO_RECUSADO,
                    paciente=_final(wa_id),
                    resumo="O paciente não aceitou o cadastro pelo WhatsApp e aguarda contato.",
                    contato=wa_id.valor,
                )
            case AtendimentoHumanoNecessario():
                alerta = await self._alerta_atendimento(evento)
        await self._enviar(alerta.tipo.name.lower(), lambda c: c.alerta(alerta))

    async def _aviso_agendamento(self, evento: ConsultaAgendada) -> AvisoNovoAgendamento | None:
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_id(evento.paciente_id)
            prontuario = await uow.prontuarios.buscar_por_paciente(evento.paciente_id)
        if paciente is None or prontuario is None:
            logger.error(
                "paciente da consulta não encontrado para o aviso",
                extra={"consulta_id": str(evento.consulta_id)},
            )
            return None
        queixa = prontuario.buscar_queixa(evento.queixa_id) if evento.queixa_id else None
        return AvisoNovoAgendamento(
            nome_paciente=paciente.nome,
            data_hora=formatar_data_hora(evento.inicio, self._configuracao.fuso),
            problema=queixa.problema.nome if queixa else "Não informado",
            prioridade=evento.prioridade,
            prontuario=str(prontuario.numero),
        )

    async def _alerta_emergencia(self, evento: EmergenciaDetectada) -> AlertaConsultorio:
        paciente = await self._paciente(evento.paciente_id)
        sinais = ", ".join(evento.termos_alarme) or "classificação de emergência"
        return AlertaConsultorio(
            tipo=TipoAlerta.EMERGENCIA,
            paciente=paciente.nome if paciente else "paciente cadastrado",
            resumo=f"{evento.problema_nome}; sinais: {sinais}",
            prioridade=Prioridade.EMERGENCIA,
            contato=paciente.telefones[-1].valor if paciente and paciente.telefones else None,
        )

    async def _alerta_atendimento(self, evento: AtendimentoHumanoNecessario) -> AlertaConsultorio:
        paciente = await self._paciente(evento.paciente_id) if evento.paciente_id else None
        return AlertaConsultorio(
            tipo=TipoAlerta.ATENDIMENTO_HUMANO,
            paciente=paciente.nome if paciente else _final(evento.wa_id),
            resumo=evento.motivo,
            prioridade=evento.prioridade,
            contato=evento.wa_id.valor,
        )

    async def _paciente(self, paciente_id: UUID) -> Paciente | None:
        async with self._uow as uow:
            return await uow.pacientes.buscar_por_id(paciente_id)

    async def _enviar(self, tipo: str, envio: Envio) -> None:
        resultados = await asyncio.gather(
            *(envio(canal) for canal in self._canais), return_exceptions=True
        )
        for canal, resultado in zip(self._canais, resultados, strict=True):
            if isinstance(resultado, BaseException):
                logger.error(
                    "falha ao avisar o consultório",
                    extra={"canal": canal.nome, "tipo": tipo, "erro": type(resultado).__name__},
                )
            else:
                logger.info("consultório avisado", extra={"canal": canal.nome, "tipo": tipo})
