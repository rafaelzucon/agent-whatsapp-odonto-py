"""Aritmética de datas com fuso horário.

Datetimes "conscientes" com o mesmo ``tzinfo`` são somados e comparados pelo horário de parede,
o que erra em transições de horário de verão. Estas funções fazem as contas em UTC (tempo real).
"""

from datetime import UTC, datetime, timedelta

from odonto.dominio.excecoes import DadoInvalidoError


def exigir_fuso(momento: datetime, campo: str) -> datetime:
    """Garante que o datetime tem fuso horário (nunca trabalhamos com datas "ingênuas")."""
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise DadoInvalidoError(campo, f"O campo {campo} precisa de fuso horário.")
    return momento


def somar_tempo_real(momento: datetime, duracao: timedelta) -> datetime:
    """Soma uma duração em tempo real, devolvendo no mesmo fuso do momento original."""
    return (momento.astimezone(UTC) + duracao).astimezone(momento.tzinfo)


def diferenca_real(fim: datetime, inicio: datetime) -> timedelta:
    """Intervalo de tempo real entre dois instantes (``fim - inicio``)."""
    return fim.astimezone(UTC) - inicio.astimezone(UTC)
