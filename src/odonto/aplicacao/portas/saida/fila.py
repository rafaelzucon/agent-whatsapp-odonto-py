"""Portas da fila de processamento assíncrono e da publicação de eventos de domínio."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from odonto.dominio.modelo.eventos import EventoDominio
from odonto.dominio.modelo.valores import WaId


@dataclass(frozen=True, slots=True)
class ItemProcessarMensagem:
    """Pedido de processamento de uma mensagem já gravada."""

    mensagem_id: UUID
    wa_id: WaId


type ItemFila = ItemProcessarMensagem | EventoDominio


class FilaProcessamento(Protocol):
    async def enfileirar(self, item: ItemProcessarMensagem) -> None:
        """Agenda o processamento da mensagem. Chamado só depois do commit que a gravou."""
        ...


class PublicadorEventos(Protocol):
    async def publicar(self, eventos: Sequence[EventoDominio]) -> None:
        """Entrega os eventos aos interessados (ex.: aviso ao consultório).

        Chamado pela unidade de trabalho só depois do commit. Não levanta exceção por falha
        de um interessado.
        """
        ...
