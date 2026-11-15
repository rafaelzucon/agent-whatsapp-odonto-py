"""Cliente da WhatsApp Cloud API (Graph API da Meta) com httpx. Sem bibliotecas não oficiais."""

import logging
import re
from collections.abc import Sequence
from typing import Any

import httpx

from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.portas.saida.whatsapp import MidiaBaixada
from odonto.dominio.modelo.valores import WaId

_log = logging.getLogger(__name__)

URL_GRAPH = "https://graph.facebook.com"
VERSAO_PADRAO = "v24.0"
TAMANHO_MAXIMO_PARAMETRO = 200
TAMANHO_MAXIMO_MIDIA = 16 * 1024 * 1024  # limite de áudio da Cloud API
_ESPACOS = re.compile(r"\s+")


def sanitizar_parametro(valor: str) -> str:
    """Parâmetros de template não aceitam quebra de linha, tabulação nem 4+ espaços seguidos."""
    limpo = _ESPACOS.sub(" ", valor).strip()
    if len(limpo) > TAMANHO_MAXIMO_PARAMETRO:
        limpo = limpo[: TAMANHO_MAXIMO_PARAMETRO - 1].rstrip() + "…"
    return limpo or "-"


class WhatsAppCloudApi:
    """Implementa ``EnviadorWhatsApp`` e ``ProvedorMidia``."""

    def __init__(
        self,
        cliente: httpx.AsyncClient,
        *,
        phone_number_id: str,
        access_token: str,
        versao_api: str = VERSAO_PADRAO,
        url_base: str = URL_GRAPH,
    ) -> None:
        self._cliente = cliente
        self._phone_number_id = phone_number_id
        self._cabecalhos = {"Authorization": f"Bearer {access_token}"}
        self._url_api = f"{url_base.rstrip('/')}/{versao_api}"

    async def enviar_texto(self, destino: WaId, texto: str) -> str:
        return await self._enviar(
            destino,
            {"type": "text", "text": {"body": texto, "preview_url": False}},
        )

    async def enviar_template(
        self, destino: WaId, template: str, parametros: Sequence[str], *, idioma: str = "pt_BR"
    ) -> str:
        corpo: dict[str, Any] = {"name": template, "language": {"code": idioma}}
        if parametros:
            corpo["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": sanitizar_parametro(p)} for p in parametros
                    ],
                }
            ]
        return await self._enviar(destino, {"type": "template", "template": corpo})

    async def _enviar(self, destino: WaId, conteudo: dict[str, Any]) -> str:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destino.valor,
            **conteudo,
        }
        url = f"{self._url_api}/{self._phone_number_id}/messages"
        dados = await self._requisitar("POST", url, json=payload)
        try:
            return str(dados["messages"][0]["id"])
        except (KeyError, IndexError, TypeError) as erro:
            raise FalhaIntegracaoError("Resposta inesperada da Cloud API ao enviar.") from erro

    async def baixar(self, midia_id: str) -> MidiaBaixada:
        info = await self._requisitar("GET", f"{self._url_api}/{midia_id}")
        url, mime = info.get("url"), info.get("mime_type")
        if not isinstance(url, str) or not isinstance(mime, str):
            raise FalhaIntegracaoError("A Cloud API não devolveu a URL da mídia.")
        tamanho = info.get("file_size")
        if isinstance(tamanho, int) and tamanho > TAMANHO_MAXIMO_MIDIA:
            raise FalhaIntegracaoError("Mídia maior que o limite aceito.")
        try:
            resposta = await self._cliente.get(url, headers=self._cabecalhos)
            resposta.raise_for_status()
        except httpx.HTTPError as erro:
            raise FalhaIntegracaoError(f"Falha ao baixar a mídia: {type(erro).__name__}.") from erro
        return MidiaBaixada(conteudo=resposta.content, mime_type=mime)

    async def _requisitar(self, metodo: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resposta = await self._cliente.request(metodo, url, headers=self._cabecalhos, **kwargs)
        except httpx.HTTPError as erro:
            raise FalhaIntegracaoError(
                f"Falha de rede na Cloud API: {type(erro).__name__}."
            ) from erro
        if resposta.is_error:
            # Só o código e o tipo do erro vão para o log (a mensagem pode ecoar dados enviados).
            erro_api = _erro_da_resposta(resposta)
            _log.warning(
                "erro na Cloud API",
                extra={"status": resposta.status_code, "codigo_meta": erro_api.get("code")},
            )
            raise FalhaIntegracaoError(
                f"Cloud API respondeu {resposta.status_code} "
                f"(código {erro_api.get('code')}, {erro_api.get('type')})."
            )
        try:
            dados = resposta.json()
        except ValueError as erro:
            raise FalhaIntegracaoError("A Cloud API devolveu um corpo que não é JSON.") from erro
        if not isinstance(dados, dict):
            raise FalhaIntegracaoError("A Cloud API devolveu um JSON inesperado.")
        return dados


def _erro_da_resposta(resposta: httpx.Response) -> dict[str, Any]:
    try:
        corpo = resposta.json()
    except ValueError:
        return {}
    erro = corpo.get("error") if isinstance(corpo, dict) else None
    return erro if isinstance(erro, dict) else {}
