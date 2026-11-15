"""Objetos de valor: imutáveis e válidos desde a criação (invariantes em ``__post_init__``)."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Final

from odonto.dominio.excecoes import DadoInvalidoError, JanelaAtendimentoExpiradaError
from odonto.dominio.modelo.enums import PeriodoDia, Uf
from odonto.dominio.modelo.tempo import diferenca_real, exigir_fuso, somar_tempo_real

_REGEX_RG: Final = re.compile(r"(?=.{5,14}$)\d+X?")
_REGEX_SEPARADORES_RG: Final = re.compile(r"[\s.\-/]")
_REGEX_WA_ID: Final = re.compile(r"\d{10,15}")
_REGEX_PRONTUARIO: Final = re.compile(r"PR-(\d{6,})")

DURACAO_JANELA_ATENDIMENTO: Final = timedelta(hours=24)
IDADE_MAIORIDADE: Final = 18
IDADE_MAXIMA: Final = 120


@dataclass(frozen=True, slots=True)
class DocumentoRg:
    """RG normalizado (só dígitos e X final, 5 a 14 caracteres) + UF do órgão emissor."""

    numero: str = field(repr=False)
    uf: Uf

    def __post_init__(self) -> None:
        if not _REGEX_RG.fullmatch(self.numero):
            raise DadoInvalidoError(
                "rg", "O RG deve ter de 5 a 14 caracteres: dígitos e, opcionalmente, X no final."
            )

    @classmethod
    def criar(cls, numero: str, uf: str) -> DocumentoRg:
        """Normaliza o número (sem pontos, traços e espaços; X maiúsculo) e valida a UF."""
        numero_normalizado = _REGEX_SEPARADORES_RG.sub("", numero).upper()
        try:
            uf_valida = Uf(uf.strip().upper())
        except ValueError:
            raise DadoInvalidoError("uf", f"UF inválida: {uf!r}.") from None
        return cls(numero_normalizado, uf_valida)

    @property
    def chave_normalizada(self) -> str:
        """Texto canônico usado no hash de busca (HMAC)."""
        return f"{self.numero}:{self.uf.value}"

    @property
    def formatado(self) -> str:
        return f"{self.numero} {self.uf.value}"


@dataclass(frozen=True, slots=True)
class WaId:
    """Identificador do WhatsApp do paciente (número com DDI, só dígitos, 10 a 15)."""

    valor: str = field(repr=False)

    def __post_init__(self) -> None:
        if not _REGEX_WA_ID.fullmatch(self.valor):
            raise DadoInvalidoError("wa_id", "O número do WhatsApp deve ter de 10 a 15 dígitos.")

    @property
    def final(self) -> str:
        """Últimos 4 dígitos: o máximo que pode aparecer em logs."""
        return self.valor[-4:]


@dataclass(frozen=True, slots=True)
class Horario:
    """Intervalo [inicio, fim) com fuso horário."""

    inicio: datetime
    fim: datetime

    def __post_init__(self) -> None:
        exigir_fuso(self.inicio, "inicio")
        exigir_fuso(self.fim, "fim")
        if self.fim <= self.inicio:
            raise DadoInvalidoError("fim", "O fim do horário precisa ser depois do início.")

    @classmethod
    def com_duracao(cls, inicio: datetime, duracao: timedelta) -> Horario:
        return cls(inicio, inicio + duracao)

    @property
    def duracao(self) -> timedelta:
        return diferenca_real(self.fim, self.inicio)

    def sobrepoe(self, outro: Horario) -> bool:
        return self.inicio < outro.fim and outro.inicio < self.fim


@dataclass(frozen=True, slots=True)
class JanelaAtendimento:
    """Regra das 24h da Meta: respostas livres só até 24h após a última mensagem do paciente."""

    ultima_mensagem_paciente: datetime

    def __post_init__(self) -> None:
        exigir_fuso(self.ultima_mensagem_paciente, "ultima_mensagem_paciente")

    @property
    def expira_em(self) -> datetime:
        return somar_tempo_real(self.ultima_mensagem_paciente, DURACAO_JANELA_ATENDIMENTO)

    def aberta_em(self, momento: datetime) -> bool:
        return diferenca_real(self.expira_em, momento) > timedelta(0)

    def garantir_aberta(self, momento: datetime) -> None:
        if not self.aberta_em(momento):
            raise JanelaAtendimentoExpiradaError(
                "A janela de 24h para responder ao paciente já fechou."
            )


@dataclass(frozen=True, slots=True, order=True)
class NumeroProntuario:
    """Número sequencial legível do prontuário (ex.: ``PR-000123``)."""

    sequencial: int

    def __post_init__(self) -> None:
        if self.sequencial < 1:
            raise DadoInvalidoError("prontuario", "O número do prontuário deve ser positivo.")

    def __str__(self) -> str:
        return f"PR-{self.sequencial:06d}"

    @classmethod
    def de_texto(cls, texto: str) -> NumeroProntuario:
        correspondencia = _REGEX_PRONTUARIO.fullmatch(texto.strip().upper())
        if correspondencia is None:
            raise DadoInvalidoError("prontuario", "Número de prontuário inválido.")
        return cls(int(correspondencia.group(1)))


@dataclass(frozen=True, slots=True)
class PreferenciaHorario:
    """Preferência do paciente: data, hora e/ou período. A hora tem precedência sobre o período."""

    data: date | None = None
    hora: time | None = None
    periodo: PeriodoDia | None = None

    def __post_init__(self) -> None:
        if self.data is None and self.hora is None and self.periodo is None:
            raise DadoInvalidoError("preferencia", "Informe ao menos a data, a hora ou o período.")
        if self.hora is not None and self.hora.tzinfo is not None:
            raise DadoInvalidoError("hora", "A hora preferida é local (sem fuso horário).")


def idade_em(nascimento: date, hoje: date) -> int:
    """Idade completa em anos na data ``hoje``."""
    fez_aniversario = (hoje.month, hoje.day) >= (nascimento.month, nascimento.day)
    return hoje.year - nascimento.year - (0 if fez_aniversario else 1)
