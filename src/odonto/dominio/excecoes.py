"""Exceções de domínio: violações de regras de negócio, sem detalhes de infraestrutura."""

from datetime import datetime
from enum import StrEnum


class ErroDominio(Exception):
    """Base de todas as exceções de regra de negócio."""


class DadoInvalidoError(ErroDominio):
    """Um dado informado não respeita uma invariante do domínio."""

    def __init__(self, campo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.campo = campo
        self.mensagem = mensagem


class TransicaoInvalidaError(ErroDominio):
    """Transição de estado não permitida (ex.: cancelar uma consulta já realizada)."""


class MotivoIndisponibilidade(StrEnum):
    """Por que um horário não pode ser agendado."""

    NO_PASSADO = "NO_PASSADO"
    ANTECEDENCIA_MINIMA = "ANTECEDENCIA_MINIMA"
    DIA_SEM_ATENDIMENTO = "DIA_SEM_ATENDIMENTO"
    FERIADO = "FERIADO"
    FORA_DO_EXPEDIENTE = "FORA_DO_EXPEDIENTE"
    INTERVALO_ALMOCO = "INTERVALO_ALMOCO"
    FORA_DA_GRADE = "FORA_DA_GRADE"
    OCUPADO = "OCUPADO"
    BLOQUEADO = "BLOQUEADO"


class HorarioIndisponivelError(ErroDominio):
    """O horário pedido não pode ser agendado (ocupado, bloqueado, fora do expediente...)."""

    def __init__(self, motivo: MotivoIndisponibilidade, inicio: datetime) -> None:
        super().__init__(f"Horário {inicio.isoformat()} indisponível: {motivo.value}.")
        self.motivo = motivo
        self.inicio = inicio


class JanelaAtendimentoExpiradaError(ErroDominio):
    """A janela de 24h da Meta para respostas livres ao paciente já fechou."""
