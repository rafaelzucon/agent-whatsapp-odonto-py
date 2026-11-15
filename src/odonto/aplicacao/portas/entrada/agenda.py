"""Portas de entrada da agenda: agendamento e gestão pela recepção."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, Self
from uuid import UUID

from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade, StatusConsulta

MAXIMO_DIAS_CONSULTA_AGENDA = 62


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsultaResumo:
    id: UUID
    paciente_id: UUID
    nome_paciente: str | None = field(repr=False)
    queixa_id: UUID | None
    problema: str | None
    inicio: datetime
    fim: datetime
    status: StatusConsulta
    prioridade: Prioridade
    origem: OrigemAgendamento

    @classmethod
    def de(
        cls, consulta: Consulta, *, nome_paciente: str | None = None, problema: str | None = None
    ) -> Self:
        return cls(
            id=consulta.id,
            paciente_id=consulta.paciente_id,
            nome_paciente=nome_paciente,
            queixa_id=consulta.queixa_id,
            problema=problema,
            inicio=consulta.horario.inicio,
            fim=consulta.horario.fim,
            status=consulta.status,
            prioridade=consulta.prioridade,
            origem=consulta.origem,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BloqueioResumo:
    id: UUID
    inicio: datetime
    fim: datetime
    motivo: str

    @classmethod
    def de(cls, bloqueio: BloqueioAgenda) -> Self:
        return cls(
            id=bloqueio.id,
            inicio=bloqueio.periodo.inicio,
            fim=bloqueio.periodo.fim,
            motivo=bloqueio.motivo,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AgendarConsultaCommand:
    paciente_id: UUID
    inicio: datetime
    origem: OrigemAgendamento
    queixa_id: UUID | None = None
    prioridade: Prioridade | None = None


class AgendarConsultaUseCase(Protocol):
    async def executar(self, comando: AgendarConsultaCommand) -> ConsultaResumo:
        """Valida o horário na ``Agenda`` e grava a consulta (evento ``ConsultaAgendada``).

        Pelo WhatsApp vale a antecedência mínima; a recepção pode agendar sem ela.
        Sem prioridade explícita, vale a da queixa (ou ROTINA).
        Levanta ``HorarioIndisponivelError`` (inclusive se outro paciente acabou de ocupar o
        horário), ``RecursoNaoEncontradoError`` (paciente ou queixa do paciente).
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class VisaoAgenda:
    inicio: date
    fim: date
    consultas: tuple[ConsultaResumo, ...]
    bloqueios: tuple[BloqueioResumo, ...]
    horarios_livres: tuple[datetime, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CriarBloqueioCommand:
    inicio: datetime
    fim: datetime
    motivo: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BloqueioCriado:
    bloqueio: BloqueioResumo
    consultas_afetadas: tuple[ConsultaResumo, ...]
    """Consultas agendadas no período bloqueado: não são canceladas automaticamente."""


class GerenciarAgendaUseCase(Protocol):
    async def consultar(self, inicio: date, fim: date) -> VisaoAgenda:
        """Consultas, bloqueios e horários livres entre dois dias (inclusive), até
        ``MAXIMO_DIAS_CONSULTA_AGENDA`` dias. Levanta ``DadoInvalidoError`` se o período for
        inválido."""
        ...

    async def cancelar(self, consulta_id: UUID) -> ConsultaResumo: ...

    async def marcar_realizada(self, consulta_id: UUID) -> ConsultaResumo: ...

    async def marcar_falta(self, consulta_id: UUID) -> ConsultaResumo: ...

    async def criar_bloqueio(self, comando: CriarBloqueioCommand) -> BloqueioCriado: ...

    async def remover_bloqueio(self, bloqueio_id: UUID) -> None:
        """Levanta ``RecursoNaoEncontradoError`` se o bloqueio não existir."""
        ...
