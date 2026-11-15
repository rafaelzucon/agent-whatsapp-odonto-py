"""Fila em memória (``asyncio.Queue``) para mensagens a processar e eventos de domínio.

Funciona com 1 processo (1 worker do Uvicorn). Itens na fila se perdem se o processo cair,
mas nada se perde de fato: as mensagens já estão gravadas e são reenfileiradas na
inicialização (``processada_em`` nulo). Para vários processos, troque por Redis ou SQS
implementando as mesmas portas.
"""

import asyncio
import logging
from collections.abc import Sequence

from odonto.aplicacao.portas.saida.fila import ItemFila, ItemProcessarMensagem
from odonto.dominio.modelo.eventos import EventoDominio

_log = logging.getLogger(__name__)


class FilaAsyncio:
    """Implementa ``FilaProcessamento`` e ``PublicadorEventos``; o consumidor usa ``obter``."""

    def __init__(self, tamanho_maximo: int = 10_000) -> None:
        self._fila: asyncio.Queue[ItemFila] = asyncio.Queue(maxsize=tamanho_maximo)

    async def enfileirar(self, item: ItemProcessarMensagem) -> None:
        await self._fila.put(item)

    async def publicar(self, eventos: Sequence[EventoDominio]) -> None:
        for evento in eventos:
            try:
                self._fila.put_nowait(evento)
            except asyncio.QueueFull:
                _log.error("fila cheia: evento descartado", extra={"evento": type(evento).__name__})

    async def obter(self) -> ItemFila:
        return await self._fila.get()

    def concluir(self) -> None:
        self._fila.task_done()

    async def aguardar_vazia(self) -> None:
        await self._fila.join()

    @property
    def tamanho(self) -> int:
        return self._fila.qsize()
