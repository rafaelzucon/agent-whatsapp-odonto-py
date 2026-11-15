"""Consulta agendada na agenda do consultório."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid7

from odonto.dominio.excecoes import TransicaoInvalidaError
from odonto.dominio.modelo.agregado import AgregadoRaiz
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade, StatusConsulta
from odonto.dominio.modelo.eventos import ConsultaAgendada, EventoDominio
from odonto.dominio.modelo.tempo import diferenca_real, exigir_fuso
from odonto.dominio.modelo.valores import Horario


@dataclass(slots=True, kw_only=True, eq=False)
class Consulta(AgregadoRaiz):
    """Consulta com transições AGENDADA → CANCELADA | REALIZADA | FALTOU."""

    id: UUID
    paciente_id: UUID
    queixa_id: UUID | None
    horario: Horario
    status: StatusConsulta
    prioridade: Prioridade
    origem: OrigemAgendamento
    agendada_em: datetime
    atualizada_em: datetime
    _eventos: list[EventoDominio] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def agendar(
        cls,
        *,
        paciente_id: UUID,
        queixa_id: UUID | None,
        horario: Horario,
        prioridade: Prioridade,
        origem: OrigemAgendamento,
        momento: datetime,
        id: UUID | None = None,
    ) -> Consulta:
        """Cria a consulta AGENDADA e registra o evento ``ConsultaAgendada``.

        A disponibilidade do horário é verificada antes, pela ``Agenda``.
        """
        exigir_fuso(momento, "momento")
        consulta = cls(
            id=id or uuid7(),
            paciente_id=paciente_id,
            queixa_id=queixa_id,
            horario=horario,
            status=StatusConsulta.AGENDADA,
            prioridade=prioridade,
            origem=origem,
            agendada_em=momento,
            atualizada_em=momento,
        )
        consulta.registrar_evento(
            ConsultaAgendada(
                consulta_id=consulta.id,
                paciente_id=paciente_id,
                queixa_id=queixa_id,
                inicio=horario.inicio,
                prioridade=prioridade,
                origem=origem,
                ocorrido_em=momento,
            )
        )
        return consulta

    @property
    def inicio(self) -> datetime:
        return self.horario.inicio

    @property
    def ativa(self) -> bool:
        return self.status is StatusConsulta.AGENDADA

    def cancelar(self, momento: datetime) -> None:
        self._transicionar(StatusConsulta.CANCELADA, momento)

    def marcar_realizada(self, momento: datetime) -> None:
        self._exigir_iniciada(momento, "realizada")
        self._transicionar(StatusConsulta.REALIZADA, momento)

    def marcar_falta(self, momento: datetime) -> None:
        self._exigir_iniciada(momento, "falta")
        self._transicionar(StatusConsulta.FALTOU, momento)

    def _exigir_iniciada(self, momento: datetime, acao: str) -> None:
        if diferenca_real(exigir_fuso(momento, "momento"), self.horario.inicio).total_seconds() < 0:
            raise TransicaoInvalidaError(
                f"Não é possível marcar {acao} numa consulta que ainda não começou."
            )

    def _transicionar(self, novo_status: StatusConsulta, momento: datetime) -> None:
        if self.status is not StatusConsulta.AGENDADA:
            raise TransicaoInvalidaError(
                f"Consulta {self.status.value}: só consultas AGENDADAS mudam de status."
            )
        self.status = novo_status
        self.atualizada_em = exigir_fuso(momento, "momento")
