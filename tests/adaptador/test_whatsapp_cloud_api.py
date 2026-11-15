import json

import httpx
import pytest
import respx

from odonto.adaptador.saida.whatsapp.cloud_api import WhatsAppCloudApi, sanitizar_parametro
from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.dominio.modelo.valores import WaId

URL = "https://graph.facebook.com/v24.0"
DESTINO = WaId("5511987654321")


@pytest.fixture
async def api() -> WhatsAppCloudApi:  # type: ignore[misc]
    async with httpx.AsyncClient() as cliente:
        yield WhatsAppCloudApi(cliente, phone_number_id="PNID", access_token="TOKEN")


@respx.mock
async def test_envia_texto(api: WhatsAppCloudApi) -> None:
    rota = respx.post(f"{URL}/PNID/messages").respond(
        200, json={"messages": [{"id": "wamid.enviada"}]}
    )

    wa_message_id = await api.enviar_texto(DESTINO, "Olá!")

    assert wa_message_id == "wamid.enviada"
    requisicao = rota.calls.last.request
    assert requisicao.headers["Authorization"] == "Bearer TOKEN"
    assert json.loads(requisicao.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5511987654321",
        "type": "text",
        "text": {"body": "Olá!", "preview_url": False},
    }


@respx.mock
async def test_envia_template_com_parametros_sanitizados(api: WhatsAppCloudApi) -> None:
    rota = respx.post(f"{URL}/PNID/messages").respond(200, json={"messages": [{"id": "wamid.t"}]})

    await api.enviar_template(DESTINO, "novo_agendamento", ["Maria\nSilva", "25/11 10:00", "", "x"])

    template = json.loads(rota.calls.last.request.content)["template"]
    assert template["name"] == "novo_agendamento"
    assert template["language"] == {"code": "pt_BR"}
    textos = [p["text"] for p in template["components"][0]["parameters"]]
    assert textos == ["Maria Silva", "25/11 10:00", "-", "x"]


@respx.mock
async def test_erro_da_api_vira_falha_de_integracao(api: WhatsAppCloudApi) -> None:
    respx.post(f"{URL}/PNID/messages").respond(
        400, json={"error": {"code": 131047, "type": "OAuthException", "message": "Re-engagement"}}
    )

    with pytest.raises(FalhaIntegracaoError, match="131047"):
        await api.enviar_texto(DESTINO, "Olá!")


@respx.mock
async def test_falha_de_rede_vira_falha_de_integracao(api: WhatsAppCloudApi) -> None:
    respx.post(f"{URL}/PNID/messages").mock(side_effect=httpx.ConnectTimeout("timeout"))

    with pytest.raises(FalhaIntegracaoError, match="rede"):
        await api.enviar_texto(DESTINO, "Olá!")


@respx.mock
async def test_sem_credenciais_falha_sem_chamar_a_rede() -> None:
    async with httpx.AsyncClient() as cliente:
        api = WhatsAppCloudApi(cliente, phone_number_id="", access_token="")

        with pytest.raises(FalhaIntegracaoError, match="não configurada"):
            await api.enviar_texto(DESTINO, "Olá!")

    assert not respx.calls


@respx.mock
async def test_baixa_midia_em_duas_etapas(api: WhatsAppCloudApi) -> None:
    respx.get(f"{URL}/MIDIA1").respond(
        200,
        json={"url": "https://lookaside.fbsbx.com/m/1", "mime_type": "audio/ogg", "file_size": 3},
    )
    download = respx.get("https://lookaside.fbsbx.com/m/1").respond(200, content=b"OGG")

    midia = await api.baixar("MIDIA1")

    assert (midia.conteudo, midia.mime_type) == (b"OGG", "audio/ogg")
    assert download.calls.last.request.headers["Authorization"] == "Bearer TOKEN"


@respx.mock
async def test_recusa_midia_grande_demais(api: WhatsAppCloudApi) -> None:
    respx.get(f"{URL}/MIDIA1").respond(
        200, json={"url": "https://x/1", "mime_type": "audio/ogg", "file_size": 50 * 1024 * 1024}
    )

    with pytest.raises(FalhaIntegracaoError, match="limite"):
        await api.baixar("MIDIA1")


def test_sanitizar_parametro_limita_tamanho() -> None:
    assert len(sanitizar_parametro("a" * 500)) == 200
    assert sanitizar_parametro("  a\t\tb    c ") == "a b c"
