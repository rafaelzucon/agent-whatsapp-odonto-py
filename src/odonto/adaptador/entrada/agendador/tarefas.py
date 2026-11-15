"""Rotinas periódicas com o APScheduler (scheduler assíncrono no mesmo loop do FastAPI)."""

import logging
from collections.abc import Awaitable, Callable
from datetime import time, tzinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from odonto.aplicacao.portas.entrada.conversa import (
    ExpirarConversasUseCase,
    ExpurgarMensagensUseCase,
)

_log = logging.getLogger(__name__)


def _protegida(nome: str, rotina: Callable[[], Awaitable[object]]) -> Callable[[], Awaitable[None]]:
    async def executar() -> None:
        try:
            resultado = await rotina()
            _log.info("rotina concluída", extra={"rotina": nome, "resultado": str(resultado)})
        except Exception:
            _log.exception("rotina falhou", extra={"rotina": nome})

    return executar


def criar_agendador(
    *,
    expirar_conversas: ExpirarConversasUseCase,
    expurgar_mensagens: ExpurgarMensagensUseCase,
    fuso: tzinfo,
    horario_expurgo: time,
    intervalo_expiracao_minutos: int = 5,
) -> AsyncIOScheduler:
    """Cria o agendador (iniciar com ``start()`` dentro do loop, parar com ``shutdown()``)."""
    agendador = AsyncIOScheduler(
        timezone=fuso,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    agendador.add_job(
        _protegida("expirar_conversas", expirar_conversas.executar),
        IntervalTrigger(minutes=intervalo_expiracao_minutos, timezone=fuso),
        id="expirar_conversas",
        replace_existing=True,
    )
    agendador.add_job(
        _protegida("expurgar_mensagens", expurgar_mensagens.executar),
        CronTrigger(hour=horario_expurgo.hour, minute=horario_expurgo.minute, timezone=fuso),
        id="expurgar_mensagens",
        replace_existing=True,
    )
    return agendador
