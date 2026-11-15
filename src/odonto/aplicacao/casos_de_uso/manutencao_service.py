"""Rotinas periódicas: expiração das conversas inativas e retenção das mensagens (LGPD)."""

import logging
from datetime import timedelta

from odonto.aplicacao.configuracao import ConfiguracaoRetencao
from odonto.aplicacao.portas.entrada.conversa import ResultadoExpurgo
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.modelo.conversa import RegrasConversa

logger = logging.getLogger(__name__)


class ExpirarConversasService:
    """Encerra as conversas paradas e descarta os cadastros parciais (minimização de dados)."""

    def __init__(self, *, uow: UnidadeDeTrabalho, relogio: Relogio, regras: RegrasConversa) -> None:
        self._uow = uow
        self._relogio = relogio
        self._regras = regras

    async def executar(self) -> int:
        agora = self._relogio.agora()
        async with self._uow as uow:
            inativas = await uow.conversas.listar_inativas(agora - self._regras.expiracao)
            for conversa in inativas:
                conversa.expirar(agora)
                await uow.conversas.salvar(conversa)
            await uow.commit()
        if inativas:
            logger.info("conversas expiradas", extra={"quantidade": len(inativas)})
        return len(inativas)


class ExpurgarMensagensService:
    """Apaga mensagens antigas e conversas encerradas. Pacientes, prontuários e consultas
    nunca são apagados automaticamente (guarda legal do prontuário)."""

    def __init__(
        self, *, uow: UnidadeDeTrabalho, relogio: Relogio, configuracao: ConfiguracaoRetencao
    ) -> None:
        self._uow = uow
        self._relogio = relogio
        self._configuracao = configuracao

    async def executar(self) -> ResultadoExpurgo:
        limite = self._relogio.agora() - timedelta(days=self._configuracao.mensagens_dias)
        async with self._uow as uow:
            mensagens = await uow.mensagens.remover_anteriores_a(limite)
            conversas = await uow.conversas.remover_encerradas_antes(limite)
            await uow.commit()
        logger.info("expurgo concluído", extra={"mensagens": mensagens, "conversas": conversas})
        return ResultadoExpurgo(mensagens=mensagens, conversas=conversas)
