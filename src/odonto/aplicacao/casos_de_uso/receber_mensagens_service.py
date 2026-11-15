"""Recebimento das mensagens do webhook: gravação idempotente e enfileiramento."""

import logging
from collections.abc import Sequence

from odonto.aplicacao.configuracao import ConfiguracaoRecebimento
from odonto.aplicacao.portas.entrada.conversa import MensagemRecebidaCommand, ResultadoRecebimento
from odonto.aplicacao.portas.saida.fila import FilaProcessamento, ItemProcessarMensagem
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.valores import WaId

logger = logging.getLogger(__name__)


class ReceberMensagensService:
    def __init__(
        self,
        *,
        uow: UnidadeDeTrabalho,
        fila: FilaProcessamento,
        relogio: Relogio,
        configuracao: ConfiguracaoRecebimento,
    ) -> None:
        self._uow = uow
        self._fila = fila
        self._relogio = relogio
        self._configuracao = configuracao

    async def executar(self, comandos: Sequence[MensagemRecebidaCommand]) -> ResultadoRecebimento:
        agora = self._relogio.agora()
        novas: list[Mensagem] = []
        duplicadas = ignoradas = 0
        async with self._uow as uow:
            for comando in comandos:
                if self._configuracao.ignora(comando.wa_id):
                    ignoradas += 1
                    continue
                try:
                    wa_id = WaId(comando.wa_id)
                except DadoInvalidoError:
                    logger.warning("wa_id inválido no webhook; mensagem ignorada")
                    ignoradas += 1
                    continue
                mensagem = Mensagem.recebida(
                    wa_id=wa_id,
                    wa_message_id=comando.wa_message_id,
                    tipo=comando.tipo,
                    texto=comando.texto,
                    midia_id=comando.midia_id,
                    momento=comando.momento,
                    criada_em=agora,
                )
                if await uow.mensagens.adicionar_se_nova(mensagem):
                    novas.append(mensagem)
                else:
                    duplicadas += 1
            await uow.commit()
        for mensagem in novas:
            await self._fila.enfileirar(ItemProcessarMensagem(mensagem.id, mensagem.wa_id))
        resultado = ResultadoRecebimento(len(novas), duplicadas, ignoradas)
        logger.info(
            "mensagens recebidas",
            extra={"novas": resultado.novas, "duplicadas": duplicadas, "ignoradas": ignoradas},
        )
        return resultado


class ReenfileirarPendentesService:
    """Na inicialização, não perder as mensagens gravadas e ainda não processadas."""

    def __init__(self, *, uow: UnidadeDeTrabalho, fila: FilaProcessamento) -> None:
        self._uow = uow
        self._fila = fila

    async def executar(self) -> int:
        async with self._uow as uow:
            pendentes = await uow.mensagens.listar_pendentes()
        for mensagem in pendentes:
            await self._fila.enfileirar(ItemProcessarMensagem(mensagem.id, mensagem.wa_id))
        if pendentes:
            logger.info("mensagens pendentes reenfileiradas", extra={"quantidade": len(pendentes)})
        return len(pendentes)
