"""Documentação OpenAPI (``/docs``): desabilitada por padrão e, quando ligada, protegida pelo token.

No navegador, abra ``/docs?token=<ADMIN_TOKEN>`` (o token também é aceito no cabeçalho).
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from odonto.adaptador.entrada.web.dependencias import (
    CABECALHO_ADMIN,
    ConfigWeb,
    token_admin_valido,
)


def _verificar(configuracao: ConfigWeb, token: str | None, cabecalho: str | None) -> None:
    if not token_admin_valido(token or cabecalho, configuracao.admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")


def criar_router_documentacao(app: FastAPI) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/openapi.json")
    async def openapi(
        configuracao: ConfigWeb,
        token: Annotated[str | None, Query()] = None,
        cabecalho: Annotated[str | None, Header(alias=CABECALHO_ADMIN)] = None,
    ) -> JSONResponse:
        _verificar(configuracao, token, cabecalho)
        return JSONResponse(app.openapi())

    @router.get("/docs")
    async def docs(
        configuracao: ConfigWeb,
        token: Annotated[str | None, Query()] = None,
        cabecalho: Annotated[str | None, Header(alias=CABECALHO_ADMIN)] = None,
    ) -> HTMLResponse:
        _verificar(configuracao, token, cabecalho)
        return get_swagger_ui_html(
            openapi_url=f"/openapi.json?token={quote(token or cabecalho or '')}",
            title=f"{app.title} - documentação",
        )

    return router
