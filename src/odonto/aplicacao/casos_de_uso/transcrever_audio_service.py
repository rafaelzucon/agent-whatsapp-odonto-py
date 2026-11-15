"""Transcrição dos áudios enviados pelos pacientes."""

import logging

from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.portas.saida.transcricao import TranscritorAudio
from odonto.aplicacao.portas.saida.whatsapp import ProvedorMidia

logger = logging.getLogger(__name__)


class TranscreverAudioService:
    """Sem transcritor configurado (``TRANSCRICAO_PROVEDOR=none``), devolve sempre ``None``."""

    def __init__(self, *, midias: ProvedorMidia, transcritor: TranscritorAudio | None) -> None:
        self._midias = midias
        self._transcritor = transcritor

    async def executar(self, midia_id: str) -> str | None:
        if self._transcritor is None:
            return None
        try:
            midia = await self._midias.baixar(midia_id)
            texto = await self._transcritor.transcrever(midia.conteudo, midia.mime_type)
        except FalhaIntegracaoError:
            logger.warning("falha ao transcrever áudio; o paciente será orientado a usar texto")
            return None
        return texto.strip() or None
