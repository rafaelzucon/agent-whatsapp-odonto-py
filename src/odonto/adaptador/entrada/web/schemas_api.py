"""Modelos Pydantic de entrada e saída da API administrativa (recepção)."""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from odonto.aplicacao.portas.entrada.agenda import (
    BloqueioCriado,
    BloqueioResumo,
    ConsultaResumo,
    VisaoAgenda,
)
from odonto.aplicacao.portas.entrada.pacientes import ProntuarioDetalhado, ResumoPaciente
from odonto.aplicacao.portas.entrada.prontuario import QueixaResumo
from odonto.dominio.modelo.enums import (
    OrigemAgendamento,
    OrigemClassificacao,
    Prioridade,
    StatusConsulta,
)
from odonto.dominio.modelo.problema import ProblemaOdontologico


class _Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Agenda -----------------------------------------------------------------------------------


class ConsultaSaida(_Saida):
    id: UUID
    paciente_id: UUID
    nome_paciente: str | None
    queixa_id: UUID | None
    problema: str | None
    inicio: datetime
    fim: datetime
    status: StatusConsulta
    prioridade: Prioridade
    origem: OrigemAgendamento

    @classmethod
    def de(cls, consulta: ConsultaResumo) -> Self:
        return cls.model_validate(consulta)


class BloqueioSaida(_Saida):
    id: UUID
    inicio: datetime
    fim: datetime
    motivo: str

    @classmethod
    def de(cls, bloqueio: BloqueioResumo) -> Self:
        return cls.model_validate(bloqueio)


class AgendaSaida(_Saida):
    inicio: date
    fim: date
    consultas: list[ConsultaSaida]
    bloqueios: list[BloqueioSaida]
    horarios_livres: list[datetime]

    @classmethod
    def de(cls, visao: VisaoAgenda) -> Self:
        return cls(
            inicio=visao.inicio,
            fim=visao.fim,
            consultas=[ConsultaSaida.de(c) for c in visao.consultas],
            bloqueios=[BloqueioSaida.de(b) for b in visao.bloqueios],
            horarios_livres=list(visao.horarios_livres),
        )


class CriarBloqueioEntrada(_Entrada):
    inicio: AwareDatetime = Field(description="Início com fuso (ex.: 2026-12-24T08:00:00-03:00).")
    fim: AwareDatetime
    motivo: str = Field(min_length=1, max_length=200)


class BloqueioCriadoSaida(_Saida):
    bloqueio: BloqueioSaida
    consultas_afetadas: list[ConsultaSaida] = Field(
        description="Consultas já agendadas no período (não são canceladas automaticamente)."
    )

    @classmethod
    def de(cls, criado: BloqueioCriado) -> Self:
        return cls(
            bloqueio=BloqueioSaida.de(criado.bloqueio),
            consultas_afetadas=[ConsultaSaida.de(c) for c in criado.consultas_afetadas],
        )


class AgendarConsultaEntrada(_Entrada):
    paciente_id: UUID
    inicio: AwareDatetime
    queixa_id: UUID | None = None
    prioridade: Prioridade | None = None


# --- Pacientes e prontuário --------------------------------------------------------------------


class PacienteSaida(_Saida):
    id: UUID
    nome: str
    documento: str
    data_nascimento: date
    responsavel: str | None
    telefones: list[str]
    numero_prontuario: str | None
    cadastrado_em: datetime
    consentimento_em: datetime

    @classmethod
    def de(cls, paciente: ResumoPaciente) -> Self:
        return cls.model_validate(paciente)


class QueixaSaida(_Saida):
    id: UUID
    texto: str
    problema_codigo: str
    problema_nome: str
    cid10: str
    prioridade: Prioridade
    confianca: float
    origem: OrigemClassificacao
    sintomas: list[str]
    registrada_em: datetime
    reclassificada_em: datetime | None
    consulta_id: UUID | None

    @classmethod
    def de(cls, queixa: QueixaResumo) -> Self:
        return cls.model_validate(queixa)


class ProntuarioSaida(_Saida):
    paciente: PacienteSaida
    numero: str
    aberto_em: datetime
    queixas: list[QueixaSaida]
    consultas: list[ConsultaSaida]

    @classmethod
    def de(cls, prontuario: ProntuarioDetalhado) -> Self:
        return cls(
            paciente=PacienteSaida.de(prontuario.paciente),
            numero=prontuario.numero,
            aberto_em=prontuario.aberto_em,
            queixas=[QueixaSaida.de(q) for q in prontuario.queixas],
            consultas=[ConsultaSaida.de(c) for c in prontuario.consultas],
        )


class ReclassificarEntrada(_Entrada):
    codigo_problema: str = Field(min_length=2, max_length=60, examples=["PULPITE"])
    prioridade: Prioridade | None = None


class ProblemaSaida(_Saida):
    codigo: str
    nome: str
    descricao: str
    especialidade: str
    prioridade: Prioridade
    cid10: str
    palavras_chave: list[str]
    ativo: bool

    @classmethod
    def de(cls, problema: ProblemaOdontologico) -> Self:
        return cls.model_validate(problema)
