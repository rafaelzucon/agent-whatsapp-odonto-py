"""Porta de transcrição de áudio."""

from typing import Protocol


class TranscritorAudio(Protocol):
    async def transcrever(self, audio: bytes, mime_type: str) -> str:
        """Transcreve o áudio (em português).

        Pós-condições: devolve o texto transcrito, que pode ser vazio (áudio sem fala).
        Levanta ``FalhaIntegracaoError`` em erro de rede, timeout ou resposta de erro da API.
        """
        ...
