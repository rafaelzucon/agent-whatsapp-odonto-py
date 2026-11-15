"""Bases das entidades: identidade por ``id`` e coleta de eventos de domínio."""

from uuid import UUID

from odonto.dominio.modelo.eventos import EventoDominio


class Entidade:
    """Entidades são iguais quando têm o mesmo tipo e o mesmo ``id``."""

    __slots__ = ()
    id: UUID

    def __eq__(self, outro: object) -> bool:
        if not isinstance(outro, Entidade) or type(outro) is not type(self):
            return NotImplemented
        return self.id == outro.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))


class AgregadoRaiz(Entidade):
    """Raiz de agregado: registra eventos que a Unidade de Trabalho publica após o commit.

    As subclasses (dataclasses com ``slots``) declaram o campo
    ``_eventos: list[EventoDominio] = field(default_factory=list, init=False, repr=False)``.
    """

    __slots__ = ()
    _eventos: list[EventoDominio]

    def registrar_evento(self, evento: EventoDominio) -> None:
        self._eventos.append(evento)

    def coletar_eventos(self) -> tuple[EventoDominio, ...]:
        """Devolve e esvazia os eventos pendentes."""
        eventos = tuple(self._eventos)
        self._eventos.clear()
        return eventos
