"""API da recepção: agenda, bloqueios e consultas."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from odonto.adaptador.entrada.web.dependencias import Casos, exigir_admin
from odonto.adaptador.entrada.web.schemas_api import (
    AgendarConsultaEntrada,
    AgendaSaida,
    BloqueioCriadoSaida,
    ConsultaSaida,
    CriarBloqueioEntrada,
)
from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaCommand, CriarBloqueioCommand
from odonto.dominio.modelo.enums import OrigemAgendamento

router = APIRouter(prefix="/api", tags=["agenda"], dependencies=[Depends(exigir_admin)])


@router.get("/agenda")
async def consultar_agenda(
    casos: Casos,
    inicio: Annotated[date, Query(description="Primeiro dia (AAAA-MM-DD).")],
    fim: Annotated[date, Query(description="Último dia, inclusive (AAAA-MM-DD).")],
) -> AgendaSaida:
    """Consultas, bloqueios e horários livres do período (até 62 dias)."""
    return AgendaSaida.de(await casos.gerenciar_agenda.consultar(inicio, fim))


@router.post("/agenda/bloqueios", status_code=status.HTTP_201_CREATED)
async def criar_bloqueio(casos: Casos, entrada: CriarBloqueioEntrada) -> BloqueioCriadoSaida:
    """Bloqueia um período (folga, curso, manutenção). Consultas existentes não são canceladas."""
    criado = await casos.gerenciar_agenda.criar_bloqueio(
        CriarBloqueioCommand(inicio=entrada.inicio, fim=entrada.fim, motivo=entrada.motivo)
    )
    return BloqueioCriadoSaida.de(criado)


@router.delete("/agenda/bloqueios/{bloqueio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_bloqueio(casos: Casos, bloqueio_id: UUID) -> Response:
    await casos.gerenciar_agenda.remover_bloqueio(bloqueio_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/consultas", status_code=status.HTTP_201_CREATED)
async def agendar(casos: Casos, entrada: AgendarConsultaEntrada) -> ConsultaSaida:
    """Agendamento manual pela recepção (sem antecedência mínima e sem aviso por WhatsApp)."""
    consulta = await casos.agendar_consulta.executar(
        AgendarConsultaCommand(
            paciente_id=entrada.paciente_id,
            inicio=entrada.inicio,
            origem=OrigemAgendamento.RECEPCAO,
            queixa_id=entrada.queixa_id,
            prioridade=entrada.prioridade,
        )
    )
    return ConsultaSaida.de(consulta)


@router.post("/consultas/{consulta_id}/cancelar")
async def cancelar(casos: Casos, consulta_id: UUID) -> ConsultaSaida:
    return ConsultaSaida.de(await casos.gerenciar_agenda.cancelar(consulta_id))


@router.post("/consultas/{consulta_id}/realizada")
async def marcar_realizada(casos: Casos, consulta_id: UUID) -> ConsultaSaida:
    return ConsultaSaida.de(await casos.gerenciar_agenda.marcar_realizada(consulta_id))


@router.post("/consultas/{consulta_id}/falta")
async def marcar_falta(casos: Casos, consulta_id: UUID) -> ConsultaSaida:
    return ConsultaSaida.de(await casos.gerenciar_agenda.marcar_falta(consulta_id))
