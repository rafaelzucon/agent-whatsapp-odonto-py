from datetime import UTC, datetime
from typing import Any

from odonto.adaptador.entrada.web.schemas_webhook import PayloadWebhook
from odonto.dominio.modelo.enums import TipoMensagem

PHONE_ID = "1234567890"


def payload(*mensagens: dict[str, Any], campo: str = "messages", **extra: Any) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": campo,
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "551130000000",
                                "phone_number_id": PHONE_ID,
                            },
                            "contacts": [{"profile": {"name": "Fulano"}, "wa_id": "5511987654321"}],
                            "messages": list(mensagens),
                            **extra,
                        },
                    }
                ],
            }
        ],
    }


def mensagem(tipo: str, **conteudo: Any) -> dict[str, Any]:
    return {
        "from": "5511987654321",
        "id": f"wamid.{tipo}",
        "timestamp": "1795000000",
        "type": tipo,
        **conteudo,
    }


def test_mensagem_de_texto_vira_comando() -> None:
    dados = payload(mensagem("text", text={"body": "Olá, quero marcar"}))

    [comando] = PayloadWebhook.model_validate(dados).comandos(PHONE_ID)

    assert comando.wa_id == "5511987654321"
    assert comando.wa_message_id == "wamid.text"
    assert comando.tipo is TipoMensagem.TEXTO
    assert comando.texto == "Olá, quero marcar"
    assert comando.momento == datetime.fromtimestamp(1795000000, UTC)


def test_audio_vira_comando_com_midia() -> None:
    dados = payload(
        mensagem("audio", audio={"id": "MIDIA1", "mime_type": "audio/ogg; codecs=opus"})
    )

    [comando] = PayloadWebhook.model_validate(dados).comandos()

    assert comando.tipo is TipoMensagem.AUDIO
    assert comando.midia_id == "MIDIA1"
    assert comando.texto is None


def test_resposta_de_botao_e_interativa_viram_texto() -> None:
    dados = payload(
        mensagem("button", button={"text": "SIM", "payload": "sim"}),
        mensagem(
            "interactive",
            interactive={"type": "button_reply", "button_reply": {"id": "1", "title": "NÃO"}},
        ),
    )

    comandos = PayloadWebhook.model_validate(dados).comandos()

    assert [(c.tipo, c.texto) for c in comandos] == [
        (TipoMensagem.TEXTO, "SIM"),
        (TipoMensagem.TEXTO, "NÃO"),
    ]


def test_tipos_nao_suportados_viram_outro() -> None:
    dados = payload(
        mensagem("image", image={"id": "IMG"}), mensagem("sticker", sticker={"id": "S"})
    )

    assert {c.tipo for c in PayloadWebhook.model_validate(dados).comandos()} == {TipoMensagem.OUTRO}


def test_campos_desconhecidos_sao_ignorados() -> None:
    dados = payload(
        mensagem("text", text={"body": "oi"}, context={"forwarded": True}, novo={"x": 1})
    )
    dados["campo_novo_da_meta"] = 123

    assert len(PayloadWebhook.model_validate(dados).comandos()) == 1


def test_atualizacoes_de_status_e_outros_campos_nao_geram_comandos() -> None:
    status = payload(statuses=[{"id": "wamid.x", "status": "delivered"}])
    outro_campo = payload(mensagem("text", text={"body": "oi"}), campo="account_update")

    assert PayloadWebhook.model_validate(status).comandos() == []
    assert PayloadWebhook.model_validate(outro_campo).comandos() == []


def test_mensagens_de_outro_numero_do_consultorio_sao_descartadas() -> None:
    dados = payload(mensagem("text", text={"body": "oi"}))

    assert PayloadWebhook.model_validate(dados).comandos("outro-phone-id") == []
