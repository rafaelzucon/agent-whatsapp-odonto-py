"""Porta do relógio (os testes usam um relógio fixo)."""

from datetime import datetime
from typing import Protocol


class Relogio(Protocol):
    def agora(self) -> datetime:
        """Momento atual com fuso horário (o do consultório)."""
        ...
