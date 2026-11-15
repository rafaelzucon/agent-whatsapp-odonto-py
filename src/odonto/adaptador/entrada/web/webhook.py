"""Webhook da WhatsApp Cloud API: handshake (GET) e recebimento de mensagens (POST)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from odonto.adaptador.entrada.web.assinatura_webhook import assinatura_valida
from odonto.adaptador.entrada.web.dependencias import Casos, ConfigWeb, token_admin_valido
from odonto.adaptador.entrada.web.schemas_webhook import PayloadWebhook

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"], include_in_schema=False)


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verificar(
    configuracao: ConfigWeb,
    modo: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    desafio: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    """Handshake da Meta ao cadastrar a URL do webhook."""
    if (
        modo == "subscribe"
        and desafio is not None
        and token_admin_valido(token, configuracao.verify_token)
    ):
        return PlainTextResponse(desafio)
    return PlainTextResponse("Proibido", status_code=status.HTTP_403_FORBIDDEN)


@router.post("/whatsapp")
async def receber(request: Request, configuracao: ConfigWeb, casos: Casos) -> Response:
    corpo = await request.body()
    if not assinatura_valida(
        corpo, request.headers.get("X-Hub-Signature-256"), configuracao.app_secret
    ):
        _log.warning("webhook com assinatura inválida")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = PayloadWebhook.model_validate_json(corpo)
    except ValidationError as erro:
        # 200 mesmo assim: a Meta reenviaria por dias um payload que nunca vamos entender.
        _log.warning(
            "payload do webhook em formato inesperado", extra={"erros": erro.error_count()}
        )
        return Response(status_code=status.HTTP_200_OK)
    comandos = payload.comandos(configuracao.phone_number_id)
    if comandos:
        resultado = await casos.receber_mensagens.executar(comandos)
        _log.info(
            "webhook recebido",
            extra={
                "novas": resultado.novas,
                "duplicadas": resultado.duplicadas,
                "ignoradas": resultado.ignoradas,
            },
        )
    return Response(status_code=status.HTTP_200_OK)
