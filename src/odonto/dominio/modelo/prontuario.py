"""Prontuário do paciente e as queixas relatadas (com a classificação no catálogo)."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid7

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.agregado import AgregadoRaiz, Entidade
from odonto.dominio.modelo.enums import OrigemClassificacao, Prioridade
from odonto.dominio.modelo.eventos import EmergenciaDetectada, EventoDominio
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.tempo import exigir_fuso
from odonto.dominio.modelo.valores import NumeroProntuario


@dataclass(slots=True, kw_only=True, eq=False)
class QueixaRelatada(Entidade):
    """O que o paciente contou, como foi classificado e a consulta que originou."""

    id: UUID
    texto_original: str = field(repr=False)
    problema: ProblemaOdontologico
    prioridade: Prioridade
    confianca: float
    origem: OrigemClassificacao
    sintomas: tuple[str, ...] = field(default=(), repr=False)
    registrada_em: datetime
    reclassificada_em: datetime | None = None
    consulta_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.texto_original.strip():
            raise DadoInvalidoError("texto", "A queixa não pode ser vazia.")
        if not 0.0 <= self.confianca <= 1.0:
            raise DadoInvalidoError("confianca", "A confiança deve estar entre 0 e 1.")
        exigir_fuso(self.registrada_em, "registrada_em")

    def reclassificar(
        self, *, problema: ProblemaOdontologico, prioridade: Prioridade, momento: datetime
    ) -> None:
        """Correção manual pelo dentista: origem MANUAL e confiança total."""
        self.problema = problema
        self.prioridade = prioridade
        self.confianca = 1.0
        self.origem = OrigemClassificacao.MANUAL
        self.reclassificada_em = exigir_fuso(momento, "momento")

    def vincular_consulta(self, consulta_id: UUID) -> None:
        self.consulta_id = consulta_id


@dataclass(slots=True, kw_only=True, eq=False)
class Prontuario(AgregadoRaiz):
    """Prontuário único por paciente, com número sequencial legível (ex.: PR-000123)."""

    id: UUID
    numero: NumeroProntuario
    paciente_id: UUID
    aberto_em: datetime
    queixas: list[QueixaRelatada] = field(default_factory=list)
    _eventos: list[EventoDominio] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def abrir(
        cls,
        *,
        paciente_id: UUID,
        numero: NumeroProntuario,
        momento: datetime,
        id: UUID | None = None,
    ) -> Prontuario:
        return cls(
            id=id or uuid7(),
            numero=numero,
            paciente_id=paciente_id,
            aberto_em=exigir_fuso(momento, "momento"),
        )

    def registrar_queixa(
        self,
        *,
        texto: str,
        problema: ProblemaOdontologico,
        prioridade: Prioridade,
        confianca: float,
        origem: OrigemClassificacao,
        momento: datetime,
        sintomas: Iterable[str] = (),
        termos_alarme: Iterable[str] = (),
        id: UUID | None = None,
    ) -> QueixaRelatada:
        """Registra a queixa. Prioridade EMERGENCIA gera o evento ``EmergenciaDetectada``."""
        queixa = QueixaRelatada(
            id=id or uuid7(),
            texto_original=texto.strip(),
            problema=problema,
            prioridade=prioridade,
            confianca=confianca,
            origem=origem,
            sintomas=tuple(sintomas),
            registrada_em=momento,
        )
        self.queixas.append(queixa)
        if prioridade is Prioridade.EMERGENCIA:
            self.registrar_evento(
                EmergenciaDetectada(
                    paciente_id=self.paciente_id,
                    queixa_id=queixa.id,
                    problema_codigo=problema.codigo,
                    problema_nome=problema.nome,
                    termos_alarme=tuple(termos_alarme),
                    ocorrido_em=momento,
                )
            )
        return queixa

    def buscar_queixa(self, queixa_id: UUID) -> QueixaRelatada | None:
        return next((queixa for queixa in self.queixas if queixa.id == queixa_id), None)

    def vincular_consulta(self, queixa_id: UUID, consulta_id: UUID) -> QueixaRelatada:
        """Liga a queixa à consulta que ela originou (a mais recente prevalece)."""
        queixa = self.buscar_queixa(queixa_id)
        if queixa is None:
            raise DadoInvalidoError("queixa_id", "A queixa não pertence a este prontuário.")
        queixa.vincular_consulta(consulta_id)
        return queixa

    def reclassificar_queixa(
        self,
        queixa_id: UUID,
        *,
        problema: ProblemaOdontologico,
        momento: datetime,
        prioridade: Prioridade | None = None,
    ) -> QueixaRelatada:
        """Reclassifica manualmente; sem prioridade explícita, vale a do item do catálogo."""
        queixa = self.buscar_queixa(queixa_id)
        if queixa is None:
            raise DadoInvalidoError("queixa_id", "A queixa não pertence a este prontuário.")
        queixa.reclassificar(
            problema=problema, prioridade=prioridade or problema.prioridade, momento=momento
        )
        return queixa
