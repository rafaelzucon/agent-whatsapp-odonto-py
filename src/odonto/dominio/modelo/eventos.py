"""Eventos de domínio: fatos já ocorridos, publicados depois do commit da transação.

Carregam só identificadores e metadados, nunca textos do paciente.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from odonto.dominio.modelo.enums import EtapaConversa, OrigemAgendamento, Prioridade
from odonto.dominio.modelo.valores import WaId


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsultaAgendada:
    consulta_id: UUID
    paciente_id: UUID
    queixa_id: UUID | None
    inicio: datetime
    prioridade: Prioridade
    origem: OrigemAgendamento
    ocorrido_em: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class EmergenciaDetectada:
    paciente_id: UUID
    queixa_id: UUID
    problema_codigo: str
    problema_nome: str
    termos_alarme: tuple[str, ...]
    ocorrido_em: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AtendimentoHumanoNecessario:
    wa_id: WaId
    paciente_id: UUID | None
    motivo: str
    etapa: EtapaConversa
    prioridade: Prioridade | None
    ocorrido_em: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentimentoRecusado:
    wa_id: WaId
    ocorrido_em: datetime


type EventoDominio = (
    ConsultaAgendada | EmergenciaDetectada | AtendimentoHumanoNecessario | ConsentimentoRecusado
)
