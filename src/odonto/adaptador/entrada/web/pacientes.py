"""API da recepção: pacientes, prontuário, reclassificação de queixas e catálogo."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from odonto.adaptador.entrada.web.dependencias import Casos, exigir_admin
from odonto.adaptador.entrada.web.schemas_api import (
    PacienteSaida,
    ProblemaSaida,
    ProntuarioSaida,
    QueixaSaida,
    ReclassificarEntrada,
)
from odonto.aplicacao.portas.entrada.prontuario import ReclassificarQueixaCommand
from odonto.dominio.excecoes import DadoInvalidoError

router = APIRouter(prefix="/api", tags=["pacientes"], dependencies=[Depends(exigir_admin)])


@router.get("/pacientes")
async def buscar_pacientes(
    casos: Casos,
    nome: Annotated[str | None, Query(description="Parte do nome (mínimo 2 letras).")] = None,
    rg: Annotated[str | None, Query(description="Número do RG (com ou sem pontuação).")] = None,
    uf: Annotated[str | None, Query(description="UF do órgão emissor do RG.")] = None,
) -> list[PacienteSaida]:
    """Busca por ``nome`` ou por ``rg`` + ``uf``."""
    if rg is not None or uf is not None:
        if not rg or not uf:
            raise DadoInvalidoError("rg", "Informe o RG e a UF juntos.")
        paciente = await casos.consultar_pacientes.buscar_por_documento(rg, uf)
        return [] if paciente is None else [PacienteSaida.de(paciente)]
    if nome is None:
        raise DadoInvalidoError("nome", "Informe o nome ou o RG e a UF.")
    return [PacienteSaida.de(p) for p in await casos.consultar_pacientes.buscar_por_nome(nome)]


@router.get("/pacientes/{paciente_id}/prontuario")
async def prontuario(casos: Casos, paciente_id: UUID) -> ProntuarioSaida:
    return ProntuarioSaida.de(await casos.consultar_pacientes.prontuario(paciente_id))


@router.put("/queixas/{queixa_id}/classificacao")
async def reclassificar(
    casos: Casos, queixa_id: UUID, entrada: ReclassificarEntrada
) -> QueixaSaida:
    """Reclassificação manual pelo dentista ou pela recepção (origem MANUAL)."""
    queixa = await casos.reclassificar_queixa.executar(
        ReclassificarQueixaCommand(
            queixa_id=queixa_id,
            codigo_problema=entrada.codigo_problema.strip().upper(),
            prioridade=entrada.prioridade,
        )
    )
    return QueixaSaida.de(queixa)


@router.get("/catalogo-problemas")
async def catalogo(
    casos: Casos,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[ProblemaSaida]:
    problemas = await casos.consultar_catalogo.listar(somente_ativos=not incluir_inativos)
    return [ProblemaSaida.de(p) for p in problemas]
