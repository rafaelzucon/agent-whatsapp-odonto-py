"""Gestão da agenda pela recepção: visão do período, status das consultas e bloqueios."""

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time, timedelta
from uuid import UUID

from odonto.aplicacao.configuracao import ConfiguracaoAgenda
from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.agenda import (
    MAXIMO_DIAS_CONSULTA_AGENDA,
    BloqueioCriado,
    BloqueioResumo,
    ConsultaResumo,
    CriarBloqueioCommand,
    VisaoAgenda,
)
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta

logger = logging.getLogger(__name__)


async def resumir_consultas(
    uow: UnidadeDeTrabalho, consultas: Sequence[Consulta]
) -> tuple[ConsultaResumo, ...]:
    """Resume as consultas com o nome do paciente e o problema da queixa de origem."""
    ids = {consulta.paciente_id for consulta in consultas}
    nomes = {paciente.id: paciente.nome for paciente in await uow.pacientes.buscar_por_ids(ids)}
    problemas: dict[UUID, str] = {}
    for paciente_id in ids:
        prontuario = await uow.prontuarios.buscar_por_paciente(paciente_id)
        if prontuario is not None:
            problemas |= {queixa.id: queixa.problema.nome for queixa in prontuario.queixas}
    return tuple(
        ConsultaResumo.de(
            consulta,
            nome_paciente=nomes.get(consulta.paciente_id),
            problema=problemas.get(consulta.queixa_id) if consulta.queixa_id else None,
        )
        for consulta in consultas
    )


class GerenciarAgendaService:
    def __init__(
        self, *, uow: UnidadeDeTrabalho, relogio: Relogio, configuracao: ConfiguracaoAgenda
    ) -> None:
        self._uow = uow
        self._relogio = relogio
        self._configuracao = configuracao

    async def consultar(self, inicio: date, fim: date) -> VisaoAgenda:
        if fim < inicio:
            raise DadoInvalidoError("fim", "O fim do período deve ser igual ou depois do início.")
        if (fim - inicio).days + 1 > MAXIMO_DIAS_CONSULTA_AGENDA:
            raise DadoInvalidoError(
                "fim", f"Consulte no máximo {MAXIMO_DIAS_CONSULTA_AGENDA} dias por vez."
            )
        de = self._meia_noite(inicio)
        ate = self._meia_noite(fim + timedelta(days=1))
        async with self._uow as uow:
            consultas = await uow.consultas.listar_entre(de, ate)
            bloqueios = await uow.bloqueios.listar_entre(de, ate)
            resumos = await resumir_consultas(uow, consultas)
        agenda = self._configuracao.criar_agenda(
            ocupados=[consulta.horario for consulta in consultas if consulta.ativa],
            bloqueios=[bloqueio.periodo for bloqueio in bloqueios],
        )
        return VisaoAgenda(
            inicio=inicio,
            fim=fim,
            consultas=resumos,
            bloqueios=tuple(BloqueioResumo.de(bloqueio) for bloqueio in bloqueios),
            horarios_livres=agenda.horarios_livres(inicio, fim, self._relogio.agora()),
        )

    async def cancelar(self, consulta_id: UUID) -> ConsultaResumo:
        return await self._alterar(consulta_id, Consulta.cancelar)

    async def marcar_realizada(self, consulta_id: UUID) -> ConsultaResumo:
        return await self._alterar(consulta_id, Consulta.marcar_realizada)

    async def marcar_falta(self, consulta_id: UUID) -> ConsultaResumo:
        return await self._alterar(consulta_id, Consulta.marcar_falta)

    async def criar_bloqueio(self, comando: CriarBloqueioCommand) -> BloqueioCriado:
        bloqueio = BloqueioAgenda.criar(
            inicio=comando.inicio,
            fim=comando.fim,
            motivo=comando.motivo,
            momento=self._relogio.agora(),
        )
        async with self._uow as uow:
            await uow.bloqueios.adicionar(bloqueio)
            candidatas = await uow.consultas.listar_entre(
                bloqueio.periodo.inicio - self._configuracao.funcionamento.duracao_consulta,
                bloqueio.periodo.fim,
                somente_agendadas=True,
            )
            afetadas = await resumir_consultas(uow, _bloqueadas(bloqueio, candidatas))
            await uow.commit()
        logger.info(
            "bloqueio criado",
            extra={"bloqueio_id": str(bloqueio.id), "consultas_afetadas": len(afetadas)},
        )
        return BloqueioCriado(bloqueio=BloqueioResumo.de(bloqueio), consultas_afetadas=afetadas)

    async def remover_bloqueio(self, bloqueio_id: UUID) -> None:
        async with self._uow as uow:
            if not await uow.bloqueios.remover(bloqueio_id):
                raise RecursoNaoEncontradoError("Bloqueio", bloqueio_id)
            await uow.commit()

    async def _alterar(
        self, consulta_id: UUID, acao: Callable[[Consulta, datetime], None]
    ) -> ConsultaResumo:
        async with self._uow as uow:
            consulta = await uow.consultas.buscar_por_id(consulta_id)
            if consulta is None:
                raise RecursoNaoEncontradoError("Consulta", consulta_id)
            acao(consulta, self._relogio.agora())
            await uow.consultas.salvar(consulta)
            (resumo,) = await resumir_consultas(uow, [consulta])
            await uow.commit()
        logger.info(
            "status da consulta alterado",
            extra={"consulta_id": str(consulta.id), "status": consulta.status.value},
        )
        return resumo

    def _meia_noite(self, dia: date) -> datetime:
        return datetime.combine(dia, time(0), tzinfo=self._configuracao.fuso)


def _bloqueadas(bloqueio: BloqueioAgenda, consultas: Iterable[Consulta]) -> list[Consulta]:
    return [consulta for consulta in consultas if bloqueio.bloqueia(consulta.horario)]
