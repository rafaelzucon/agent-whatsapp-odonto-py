"""Monta a ``Agenda`` do domínio com as consultas e bloqueios gravados numa janela de tempo."""

from datetime import datetime, timedelta

from odonto.aplicacao.configuracao import ConfiguracaoAgenda
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.servico.agenda import Agenda

_MARGEM = timedelta(days=1)


async def montar_agenda(
    uow: UnidadeDeTrabalho, configuracao: ConfiguracaoAgenda, de: datetime, ate: datetime
) -> Agenda:
    """Carrega as consultas AGENDADAS e os bloqueios entre ``de`` e ``ate`` (com um dia de
    margem) e cria a agenda. Deve ser chamada dentro de um ``async with uow``."""
    inicio, fim = de - _MARGEM, ate + _MARGEM
    consultas = await uow.consultas.listar_entre(inicio, fim, somente_agendadas=True)
    bloqueios = await uow.bloqueios.listar_entre(inicio, fim)
    return configuracao.criar_agenda(
        ocupados=[consulta.horario for consulta in consultas],
        bloqueios=[bloqueio.periodo for bloqueio in bloqueios],
    )


def janela_de_busca(configuracao: ConfiguracaoAgenda, a_partir: datetime) -> datetime:
    """Fim da janela necessária para buscar horários livres a partir de ``a_partir``."""
    return a_partir + timedelta(days=configuracao.dias_busca_maxima + 1)
