"""Modelos Pydantic do payload do webhook da WhatsApp Cloud API.

Campos desconhecidos são ignorados (a Meta acrescenta campos sem aviso). Só ``value.messages``
interessa; ``statuses`` (entregue, lida), ecos do app (``smb_message_echoes``) e outros
campos são descartados.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from odonto.aplicacao.portas.entrada.conversa import MensagemRecebidaCommand
from odonto.dominio.modelo.enums import TipoMensagem


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Texto(_Modelo):
    body: str


class Midia(_Modelo):
    id: str
    mime_type: str | None = None


class Botao(_Modelo):
    text: str | None = None
    payload: str | None = None


class RespostaInterativa(_Modelo):
    id: str | None = None
    title: str | None = None


class Interativo(_Modelo):
    type: str
    button_reply: RespostaInterativa | None = None
    list_reply: RespostaInterativa | None = None


class MensagemWebhook(_Modelo):
    remetente: str = Field(alias="from")
    id: str
    timestamp: str
    type: str
    text: Texto | None = None
    audio: Midia | None = None
    button: Botao | None = None
    interactive: Interativo | None = None

    def para_comando(self) -> MensagemRecebidaCommand:
        tipo, texto, midia_id = TipoMensagem.OUTRO, None, None
        match self.type:
            case "text" if self.text is not None:
                tipo, texto = TipoMensagem.TEXTO, self.text.body
            case "audio" if self.audio is not None:
                tipo, midia_id = TipoMensagem.AUDIO, self.audio.id
            case "button" if self.button is not None and self.button.text:
                tipo, texto = TipoMensagem.TEXTO, self.button.text
            case "interactive" if self.interactive is not None:
                resposta = self.interactive.button_reply or self.interactive.list_reply
                if resposta is not None and resposta.title:
                    tipo, texto = TipoMensagem.TEXTO, resposta.title
        return MensagemRecebidaCommand(
            wa_id=self.remetente,
            wa_message_id=self.id,
            tipo=tipo,
            texto=texto,
            midia_id=midia_id,
            momento=_momento(self.timestamp),
        )


class Metadados(_Modelo):
    phone_number_id: str | None = None


class Valor(_Modelo):
    metadata: Metadados | None = None
    messages: list[MensagemWebhook] = Field(default_factory=list)


class Mudanca(_Modelo):
    field: str
    value: Valor


class Entrada(_Modelo):
    changes: list[Mudanca] = Field(default_factory=list)


class PayloadWebhook(_Modelo):
    object: str
    entry: list[Entrada] = Field(default_factory=list)

    def comandos(self, phone_number_id: str | None = None) -> list[MensagemRecebidaCommand]:
        """Mensagens recebidas pelo número do consultório (outros números são ignorados)."""
        return [
            mensagem.para_comando()
            for entrada in self.entry
            for mudanca in entrada.changes
            if mudanca.field == "messages"
            and (
                phone_number_id is None
                or mudanca.value.metadata is None
                or mudanca.value.metadata.phone_number_id == phone_number_id
            )
            for mensagem in mudanca.value.messages
        ]


def _momento(timestamp: str) -> datetime:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=UTC)
    except ValueError, OverflowError, OSError:
        return datetime.now(UTC)
