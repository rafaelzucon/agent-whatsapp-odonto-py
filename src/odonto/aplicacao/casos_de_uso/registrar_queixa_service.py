"""Registro da queixa no prontuário, com a classificação no catálogo."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from odonto.aplicacao.configuracao import ConfiguracaoClassificacao
from odonto.aplicacao.excecoes import (
    ConfiguracaoInvalidaError,
    FalhaIntegracaoError,
    RecursoNaoEncontradoError,
)
from odonto.aplicacao.portas.entrada.prontuario import QueixaResumo, RegistrarQueixaCommand
from odonto.aplicacao.portas.saida.ia import ClassificacaoIA, ClassificadorProblemaIA
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.modelo.enums import OrigemClassificacao, Prioridade
from odonto.dominio.modelo.problema import CODIGO_AVALIACAO_GERAL, ProblemaOdontologico
from odonto.dominio.servico.classificador_palavra_chave import ClassificadorPorPalavraChave
from odonto.dominio.servico.detector_sinais_alarme import DetectorSinaisAlarme

logger = logging.getLogger(__name__)

TERMO_ALARME_IA = "sinais de alarme indicados pela IA"


@dataclass(frozen=True, slots=True, kw_only=True)
class _Classificacao:
    problema: ProblemaOdontologico
    confianca: float
    origem: OrigemClassificacao
    sintomas: tuple[str, ...] = ()


class RegistrarQueixaService:
    """Sinais de alarme → IA (se confiante) → palavra-chave → "Avaliação geral / outro".

    A prioridade final é a mais alta entre a do item do catálogo, a sugerida pela IA e a do
    detector de sinais de alarme (que, se acionado, força EMERGENCIA).
    """

    def __init__(
        self,
        *,
        uow: UnidadeDeTrabalho,
        relogio: Relogio,
        classificador_ia: ClassificadorProblemaIA | None,
        configuracao: ConfiguracaoClassificacao,
    ) -> None:
        self._uow = uow
        self._relogio = relogio
        self._ia = classificador_ia
        self._configuracao = configuracao
        self._detector = DetectorSinaisAlarme(configuracao.palavras_alarme)
        self._palavra_chave = ClassificadorPorPalavraChave()

    async def executar(self, comando: RegistrarQueixaCommand) -> QueixaResumo:
        alarme = self._detector.analisar(comando.texto)
        async with self._uow as uow:
            catalogo = await uow.catalogo.listar(somente_ativos=True)
        resposta_ia = await self._consultar_ia(comando.texto, catalogo)
        classificacao = self._escolher(comando.texto, catalogo, resposta_ia)

        prioridades = [classificacao.problema.prioridade]
        if resposta_ia is not None and resposta_ia.prioridade is not None:
            prioridades.append(resposta_ia.prioridade)
        termos_alarme = list(alarme.termos)
        if resposta_ia is not None and resposta_ia.sinais_alarme and not termos_alarme:
            termos_alarme.append(TERMO_ALARME_IA)
        if termos_alarme:
            prioridades.append(Prioridade.EMERGENCIA)
        prioridade = Prioridade.mais_alta(*prioridades)

        agora = self._relogio.agora()
        async with self._uow as uow:
            prontuario = await uow.prontuarios.buscar_por_paciente(comando.paciente_id)
            if prontuario is None:
                raise RecursoNaoEncontradoError("Prontuário do paciente", comando.paciente_id)
            queixa = prontuario.registrar_queixa(
                texto=comando.texto,
                problema=classificacao.problema,
                prioridade=prioridade,
                confianca=classificacao.confianca,
                origem=classificacao.origem,
                momento=agora,
                sintomas=classificacao.sintomas,
                termos_alarme=termos_alarme,
            )
            await uow.prontuarios.salvar(prontuario)
            await uow.commit()
        logger.info(
            "queixa registrada",
            extra={
                "queixa_id": str(queixa.id),
                "problema": queixa.problema.codigo,
                "prioridade": prioridade.value,
                "origem": classificacao.origem.value,
            },
        )
        return QueixaResumo.de(queixa)

    async def _consultar_ia(
        self, texto: str, catalogo: Sequence[ProblemaOdontologico]
    ) -> ClassificacaoIA | None:
        if self._ia is None or not catalogo:
            return None
        try:
            return await self._ia.classificar(texto, catalogo)
        except FalhaIntegracaoError:
            logger.warning("falha na classificação por IA; usando palavras-chave")
            return None

    def _escolher(
        self,
        texto: str,
        catalogo: Sequence[ProblemaOdontologico],
        resposta_ia: ClassificacaoIA | None,
    ) -> _Classificacao:
        por_codigo = {problema.codigo: problema for problema in catalogo}
        if resposta_ia is not None:
            problema = por_codigo.get(resposta_ia.codigo)
            if problema is None:
                logger.warning("IA devolveu código fora do catálogo; usando palavras-chave")
            elif resposta_ia.confianca >= self._configuracao.confianca_minima:
                return _Classificacao(
                    problema=problema,
                    confianca=resposta_ia.confianca,
                    origem=OrigemClassificacao.IA,
                    sintomas=resposta_ia.sintomas,
                )
        por_palavra = self._palavra_chave.classificar(texto, catalogo)
        if por_palavra is not None:
            return _Classificacao(
                problema=por_palavra.problema,
                confianca=por_palavra.confianca,
                origem=OrigemClassificacao.PALAVRA_CHAVE,
            )
        geral = por_codigo.get(CODIGO_AVALIACAO_GERAL)
        if geral is None:
            raise ConfiguracaoInvalidaError(
                f"O catálogo precisa do item ativo {CODIGO_AVALIACAO_GERAL}."
            )
        return _Classificacao(
            problema=geral, confianca=0.0, origem=OrigemClassificacao.PALAVRA_CHAVE
        )
