"""Portas do WhatsApp: envio de mensagens e download de mídia (interfaces separadas)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from odonto.dominio.modelo.valores import WaId


@dataclass(frozen=True, slots=True)
class MidiaBaixada:
    conteudo: bytes = field(repr=False)
    mime_type: str


class EnviadorWhatsApp(Protocol):
    async def enviar_texto(self, destino: WaId, texto: str) -> str:
        """Envia texto livre (permitido só dentro da janela de 24h do paciente).

        Pós-condições: devolve o ``wa_message_id`` da mensagem enviada.
        Levanta ``FalhaIntegracaoError`` em erro de rede ou resposta de erro da API.
        """
        ...

    async def enviar_template(
        self, destino: WaId, template: str, parametros: Sequence[str], *, idioma: str = "pt_BR"
    ) -> str:
        """Envia um template aprovado na Meta, com os parâmetros do corpo na ordem dada.

        Pós-condições: devolve o ``wa_message_id``.
        Levanta ``FalhaIntegracaoError`` em erro de rede ou resposta de erro da API.
        """
        ...


class ProvedorMidia(Protocol):
    async def baixar(self, midia_id: str) -> MidiaBaixada:
        """Baixa a mídia (ex.: áudio) recebida no webhook.

        Levanta ``FalhaIntegracaoError`` se a mídia não existir mais ou a API falhar.
        """
        ...
