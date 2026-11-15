"""Erros da API no formato ``application/problem+json`` (RFC 9457)."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from odonto.aplicacao.excecoes import (
    ConfiguracaoInvalidaError,
    FalhaIntegracaoError,
    RecursoNaoEncontradoError,
)
from odonto.dominio.excecoes import (
    DadoInvalidoError,
    ErroDominio,
    HorarioIndisponivelError,
    JanelaAtendimentoExpiradaError,
    TransicaoInvalidaError,
)

_log = logging.getLogger(__name__)
TIPO_MIDIA = "application/problem+json"


def problema(
    status_http: int, titulo: str, detalhe: str | None = None, **extras: object
) -> JSONResponse:
    corpo: dict[str, object] = {"type": "about:blank", "title": titulo, "status": status_http}
    if detalhe:
        corpo["detail"] = detalhe
    corpo.update({chave: valor for chave, valor in extras.items() if valor is not None})
    return JSONResponse(corpo, status_code=status_http, media_type=TIPO_MIDIA)


async def _dado_invalido(_: Request, erro: Exception) -> JSONResponse:
    if not isinstance(erro, DadoInvalidoError):  # pragma: no cover - registro garante o tipo
        raise erro
    return problema(400, "Dado inválido", erro.mensagem, campo=erro.campo)


async def _nao_encontrado(_: Request, erro: Exception) -> JSONResponse:
    return problema(404, "Não encontrado", str(erro))


async def _horario_indisponivel(_: Request, erro: Exception) -> JSONResponse:
    if not isinstance(erro, HorarioIndisponivelError):  # pragma: no cover - registro garante o tipo
        raise erro
    return problema(
        409,
        "Horário indisponível",
        str(erro),
        motivo=erro.motivo.value,
        inicio=erro.inicio.isoformat(),
    )


async def _conflito(_: Request, erro: Exception) -> JSONResponse:
    return problema(409, "Operação não permitida", str(erro))


async def _falha_integracao(_: Request, erro: Exception) -> JSONResponse:
    _log.warning("falha de integração na API", extra={"erro": type(erro).__name__})
    return problema(502, "Serviço externo indisponível", str(erro))


async def _erro_interno(_: Request, erro: Exception) -> JSONResponse:
    _log.exception("erro não tratado na API", exc_info=erro)
    return problema(500, "Erro interno")


async def _validacao(_: Request, erro: Exception) -> JSONResponse:
    if not isinstance(erro, RequestValidationError):  # pragma: no cover - registro garante o tipo
        raise erro
    erros = [
        {"campo": ".".join(str(p) for p in e.get("loc", ())), "mensagem": e.get("msg")}
        for e in erro.errors()
    ]
    return problema(400, "Requisição inválida", "Confira os campos informados.", erros=erros)


async def _http(_: Request, erro: Exception) -> JSONResponse:
    if not isinstance(erro, StarletteHTTPException):  # pragma: no cover - registro garante o tipo
        raise erro
    resposta = problema(erro.status_code, _titulo_http(erro.status_code), str(erro.detail))
    if erro.headers:
        resposta.headers.update(erro.headers)
    return resposta


def _titulo_http(codigo: int) -> str:
    return {
        status.HTTP_401_UNAUTHORIZED: "Não autorizado",
        status.HTTP_403_FORBIDDEN: "Proibido",
        status.HTTP_404_NOT_FOUND: "Não encontrado",
        status.HTTP_405_METHOD_NOT_ALLOWED: "Método não permitido",
    }.get(codigo, "Erro")


def registrar_tratadores_de_erro(app: FastAPI) -> None:
    app.add_exception_handler(DadoInvalidoError, _dado_invalido)
    app.add_exception_handler(RecursoNaoEncontradoError, _nao_encontrado)
    app.add_exception_handler(HorarioIndisponivelError, _horario_indisponivel)
    app.add_exception_handler(TransicaoInvalidaError, _conflito)
    app.add_exception_handler(JanelaAtendimentoExpiradaError, _conflito)
    app.add_exception_handler(ErroDominio, _conflito)
    app.add_exception_handler(FalhaIntegracaoError, _falha_integracao)
    app.add_exception_handler(ConfiguracaoInvalidaError, _erro_interno)
    app.add_exception_handler(RequestValidationError, _validacao)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _erro_interno)
