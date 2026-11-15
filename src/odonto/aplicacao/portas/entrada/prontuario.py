"""Portas de entrada do prontuário: registro, reclassificação de queixas e catálogo."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from odonto.dominio.modelo.enums import OrigemClassificacao, Prioridade
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.prontuario import QueixaRelatada


@dataclass(frozen=True, slots=True, kw_only=True)
class QueixaResumo:
    id: UUID
    texto: str = field(repr=False)
    problema_codigo: str
    problema_nome: str
    cid10: str
    prioridade: Prioridade
    confianca: float
    origem: OrigemClassificacao
    sintomas: tuple[str, ...] = field(repr=False)
    registrada_em: datetime
    reclassificada_em: datetime | None
    consulta_id: UUID | None

    @classmethod
    def de(cls, queixa: QueixaRelatada) -> Self:
        return cls(
            id=queixa.id,
            texto=queixa.texto_original,
            problema_codigo=queixa.problema.codigo,
            problema_nome=queixa.problema.nome,
            cid10=queixa.problema.cid10,
            prioridade=queixa.prioridade,
            confianca=queixa.confianca,
            origem=queixa.origem,
            sintomas=queixa.sintomas,
            registrada_em=queixa.registrada_em,
            reclassificada_em=queixa.reclassificada_em,
            consulta_id=queixa.consulta_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RegistrarQueixaCommand:
    paciente_id: UUID
    texto: str = field(repr=False)


class RegistrarQueixaUseCase(Protocol):
    async def executar(self, comando: RegistrarQueixaCommand) -> QueixaResumo:
        """Classifica a queixa (sinais de alarme → IA → palavra-chave → avaliação geral) e a
        registra no prontuário. Prioridade EMERGENCIA gera o aviso imediato ao consultório.

        Levanta ``RecursoNaoEncontradoError`` se o paciente não tiver prontuário.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReclassificarQueixaCommand:
    queixa_id: UUID
    codigo_problema: str
    prioridade: Prioridade | None = None


class ReclassificarQueixaUseCase(Protocol):
    async def executar(self, comando: ReclassificarQueixaCommand) -> QueixaResumo:
        """Correção manual pelo dentista (origem MANUAL). Sem prioridade, vale a do catálogo.

        Levanta ``RecursoNaoEncontradoError`` (queixa) ou ``DadoInvalidoError`` (código).
        """
        ...


class ConsultarCatalogoUseCase(Protocol):
    async def listar(self, *, somente_ativos: bool = True) -> Sequence[ProblemaOdontologico]: ...
