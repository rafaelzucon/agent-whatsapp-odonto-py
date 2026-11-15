"""Aplicação FastAPI: ciclo de vida (banco, fila, agendador), routers e ``/health``."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from odonto import __version__
from odonto.adaptador.entrada.web import agenda, pacientes, webhook
from odonto.adaptador.entrada.web.documentacao import criar_router_documentacao
from odonto.adaptador.entrada.web.erros import registrar_tratadores_de_erro
from odonto.infraestrutura.config import Configuracoes
from odonto.infraestrutura.container import Container, montar_container

_log = logging.getLogger(__name__)

type FabricaContainer = Callable[[Configuracoes], Container]


def criar_app(
    configuracoes: Configuracoes, *, fabrica_container: FabricaContainer = montar_container
) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        for pendencia in configuracoes.pendencias():
            _log.warning("configuração pendente", extra={"pendencia": pendencia})
        container = fabrica_container(configuracoes)
        app.state.container = container
        app.state.casos_de_uso = container.casos_web
        app.state.configuracao_web = container.configuracao_web
        await container.iniciar()
        _log.info(
            "aplicação iniciada",
            extra={
                "versao": __version__,
                "fuso": configuracoes.nome_fuso,
                "ia": configuracoes.ia_habilitada,
                "transcricao": configuracoes.transcricao_habilitada,
                "aviso_whatsapp": configuracoes.aviso_whatsapp_habilitado,
                "aviso_email": configuracoes.email_habilitado,
            },
        )
        try:
            yield
        finally:
            await container.encerrar()
            _log.info("aplicação encerrada")

    app = FastAPI(
        title="Agente WhatsApp - Consultório Odontológico",
        version=__version__,
        lifespan=ciclo_de_vida,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    registrar_tratadores_de_erro(app)
    app.include_router(webhook.router)
    app.include_router(agenda.router)
    app.include_router(pacientes.router)
    if configuracoes.api.docs_habilitada:
        app.include_router(criar_router_documentacao(app))

    @app.get("/health", include_in_schema=False)
    async def saude(request: Request) -> JSONResponse:
        container: Container = request.app.state.container
        banco = await container.banco_disponivel()
        return JSONResponse(
            {
                "status": "ok" if banco else "erro",
                "banco": "ok" if banco else "indisponivel",
                "fila": container.fila.tamanho,
                "versao": __version__,
            },
            status_code=200 if banco else 503,
        )

    return app
