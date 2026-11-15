"""Consumidor da fila em memória: processa as mensagens e entrega os eventos de domínio.

- Mensagens do mesmo número são processadas uma de cada vez e na ordem (``asyncio.Lock`` por
  número, removido quando ninguém mais o usa).
- Números diferentes são processados em paralelo, até ``maximo_paralelo`` ao mesmo tempo.
- Eventos de domínio (consulta agendada, emergência...) viram avisos ao consultório.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from odonto.aplicacao.portas.entrada.conversa import (
    ConduzirConversaUseCase,
    ProcessarMensagemCommand,
)
from odonto.aplicacao.portas.entrada.notificacao import NotificarConsultorioUseCase
from odonto.aplicacao.portas.saida.fila import ItemFila, ItemProcessarMensagem

_log = logging.getLogger(__name__)


class FonteDaFila(Protocol):
    """O que o consumidor precisa da fila (implementado por ``FilaAsyncio``)."""

    async def obter(self) -> ItemFila: ...

    def concluir(self) -> None: ...


class ConsumidorFila:
    def __init__(
        self,
        fonte: FonteDaFila,
        conduzir_conversa: ConduzirConversaUseCase,
        notificar_consultorio: NotificarConsultorioUseCase,
        *,
        maximo_paralelo: int = 8,
    ) -> None:
        self._fonte = fonte
        self._conduzir = conduzir_conversa
        self._notificar = notificar_consultorio
        self._semaforo = asyncio.Semaphore(maximo_paralelo)
        self._travas: dict[str, tuple[asyncio.Lock, int]] = {}
        self._tarefas: set[asyncio.Task[None]] = set()
        self._laco: asyncio.Task[None] | None = None

    @property
    def numeros_em_uso(self) -> int:
        """Quantas travas por número existem agora (para testes e diagnóstico)."""
        return len(self._travas)

    def iniciar(self) -> None:
        if self._laco is None:
            self._laco = asyncio.create_task(self._consumir(), name="consumidor-fila")

    async def parar(self, *, espera_segundos: float = 20.0) -> None:
        """Para de ler a fila e espera o que está em andamento (cancela o que passar do prazo)."""
        if self._laco is not None:
            self._laco.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._laco
            self._laco = None
        if self._tarefas:
            _, pendentes = await asyncio.wait(self._tarefas, timeout=espera_segundos)
            for tarefa in pendentes:
                tarefa.cancel()
            await asyncio.gather(*pendentes, return_exceptions=True)

    async def _consumir(self) -> None:
        while True:
            item = await self._fonte.obter()
            await self._semaforo.acquire()
            tarefa = asyncio.create_task(self._tratar(item))
            self._tarefas.add(tarefa)
            tarefa.add_done_callback(self._tarefas.discard)

    async def _tratar(self, item: ItemFila) -> None:
        try:
            match item:
                case ItemProcessarMensagem(mensagem_id=mensagem_id, wa_id=wa_id):
                    async with self._trava(wa_id.valor):
                        await self._conduzir.executar(ProcessarMensagemCommand(mensagem_id))
                case evento:
                    await self._notificar.notificar(evento)
        except Exception:
            # A mensagem continua pendente no banco e é reprocessada na próxima inicialização.
            _log.exception("falha ao tratar item da fila", extra={"item": type(item).__name__})
        finally:
            self._semaforo.release()
            self._fonte.concluir()

    @contextlib.asynccontextmanager
    async def _trava(self, chave: str) -> AsyncIterator[None]:
        trava, usos = self._travas.get(chave, (asyncio.Lock(), 0))
        self._travas[chave] = (trava, usos + 1)
        try:
            async with trava:
                yield
        finally:
            trava, usos = self._travas[chave]
            if usos <= 1:
                del self._travas[chave]
            else:
                self._travas[chave] = (trava, usos - 1)
