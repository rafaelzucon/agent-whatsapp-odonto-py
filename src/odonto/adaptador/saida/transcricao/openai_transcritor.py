"""Transcrição de áudio com o SDK oficial da OpenAI (idioma português)."""

from openai import AsyncOpenAI, OpenAIError

from odonto.aplicacao.excecoes import FalhaIntegracaoError

MODELO_PADRAO = "gpt-transcribe"
_EXTENSOES = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "m4a",
    "audio/amr": "amr",
    "audio/wav": "wav",
    "audio/webm": "webm",
}


def criar_cliente_openai(api_key: str, *, timeout_segundos: float) -> AsyncOpenAI:
    """Fábrica usada pela raiz de composição (a infraestrutura não importa o SDK)."""
    return AsyncOpenAI(api_key=api_key, timeout=timeout_segundos, max_retries=3)


def nome_arquivo(mime_type: str) -> str:
    """Nome com a extensão certa: a API identifica o formato pela extensão do arquivo."""
    base = mime_type.split(";", 1)[0].strip().lower()
    return f"audio.{_EXTENSOES.get(base, 'ogg')}"


class OpenAITranscritor:
    """Implementa ``TranscritorAudio``."""

    def __init__(self, cliente: AsyncOpenAI, *, modelo: str = MODELO_PADRAO) -> None:
        self._cliente = cliente
        self._modelo = modelo

    async def transcrever(self, audio: bytes, mime_type: str) -> str:
        arquivo = (nome_arquivo(mime_type), audio, mime_type.split(";", 1)[0].strip())
        try:
            resultado = await self._cliente.audio.transcriptions.create(
                file=arquivo, model=self._modelo, language="pt"
            )
        except OpenAIError as erro:
            raise FalhaIntegracaoError(f"Transcrição falhou: {type(erro).__name__}.") from erro
        return resultado.text.strip()
