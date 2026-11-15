"""Relógio do sistema no fuso do consultório."""

from datetime import datetime, tzinfo


class RelogioSistema:
    """Implementa ``Relogio``."""

    __slots__ = ("_fuso",)

    def __init__(self, fuso: tzinfo) -> None:
        self._fuso = fuso

    def agora(self) -> datetime:
        return datetime.now(self._fuso)
