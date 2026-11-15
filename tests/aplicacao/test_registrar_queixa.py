"""Classificação da queixa: IA, palavras-chave, avaliação geral e prioridade final."""

from uuid import uuid7

import pytest

from odonto.aplicacao.casos_de_uso.reclassificar_queixa_service import ReclassificarQueixaService
from odonto.aplicacao.excecoes import FalhaIntegracaoError, RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.prontuario import (
    ReclassificarQueixaCommand,
    RegistrarQueixaCommand,
)
from odonto.aplicacao.portas.saida.ia import ClassificacaoIA
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import OrigemClassificacao, Prioridade
from odonto.dominio.modelo.eventos import EmergenciaDetectada
from odonto.dominio.modelo.paciente import Paciente
from tests.aplicacao.fakes import Ambiente


async def registrar(
    texto: str, resposta_ia: ClassificacaoIA | Exception | None
) -> tuple[Ambiente, Paciente]:
    ambiente = Ambiente(classificacao_ia=resposta_ia)
    paciente = await ambiente.cadastrar_paciente_existente()
    await ambiente.registrar_queixa.executar(
        RegistrarQueixaCommand(paciente_id=paciente.id, texto=texto)
    )
    return ambiente, paciente


async def test_ia_confiante_define_o_problema() -> None:
    ia = ClassificacaoIA(codigo="GENGIVITE", confianca=0.85, sintomas=("sangramento",))
    ambiente, paciente = await registrar("minha gengiva sangra quando escovo", ia)
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.problema.codigo == "GENGIVITE"
    assert queixa.origem is OrigemClassificacao.IA
    assert queixa.confianca == pytest.approx(0.85)
    assert queixa.sintomas == ("sangramento",)
    assert queixa.prioridade is Prioridade.ROTINA


async def test_falha_da_ia_usa_palavras_chave() -> None:
    ambiente, paciente = await registrar("estou com dor de dente", FalhaIntegracaoError("timeout"))
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.problema.codigo == "DOR_DE_DENTE"
    assert queixa.origem is OrigemClassificacao.PALAVRA_CHAVE
    assert queixa.prioridade is Prioridade.URGENCIA


async def test_confianca_baixa_usa_palavras_chave() -> None:
    ia = ClassificacaoIA(codigo="GENGIVITE", confianca=0.3)
    ambiente, paciente = await registrar("tenho um dente furado", ia)
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.problema.codigo == "CARIE"
    assert queixa.origem is OrigemClassificacao.PALAVRA_CHAVE


async def test_codigo_inexistente_e_sem_palavra_chave_vira_avaliacao_geral() -> None:
    ia = ClassificacaoIA(codigo="INVENTADO", confianca=0.99)
    ambiente, paciente = await registrar("quero conversar com o dentista", ia)
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.problema.codigo == "AVALIACAO_GERAL_OUTRO"
    assert queixa.confianca == 0.0


async def test_codigo_inativo_nao_e_aceito() -> None:
    ia = ClassificacaoIA(codigo="ITEM_INATIVO", confianca=0.99)
    ambiente, paciente = await registrar("quero fazer limpeza", ia)
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.problema.codigo == "LIMPEZA_PROFILAXIA"


def ia(codigo: str, **extras: object) -> ClassificacaoIA:
    return ClassificacaoIA(codigo=codigo, confianca=0.9, **extras)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("texto", "resposta_ia", "esperada"),
    [
        # A IA pode elevar a prioridade do item do catálogo...
        ("dente furado", ia("CARIE", prioridade=Prioridade.URGENCIA), Prioridade.URGENCIA),
        # ...mas nunca rebaixar.
        ("dor de dente", ia("DOR_DE_DENTE", prioridade=Prioridade.ROTINA), Prioridade.URGENCIA),
        # Sinal de alarme no texto força emergência.
        ("dente furado e falta de ar", ia("CARIE"), Prioridade.EMERGENCIA),
        # Sinal de alarme apontado pela IA também.
        ("dente furado", ia("CARIE", sinais_alarme=True), Prioridade.EMERGENCIA),
        # Item de emergência do catálogo, sem IA.
        ("bati o dente e ele caiu", None, Prioridade.EMERGENCIA),
    ],
)
async def test_prioridade_final(
    texto: str, resposta_ia: ClassificacaoIA | None, esperada: Prioridade
) -> None:
    ambiente, paciente = await registrar(texto, resposta_ia)
    (queixa,) = ambiente.prontuario_de(paciente.id).queixas
    assert queixa.prioridade is esperada


async def test_emergencia_publica_evento_com_os_termos() -> None:
    ambiente, _ = await registrar(
        "dente furado e falta de ar", ClassificacaoIA(codigo="CARIE", confianca=0.9)
    )
    (evento,) = [e for e in ambiente.publicador.eventos if isinstance(e, EmergenciaDetectada)]
    assert evento.termos_alarme == ("falta de ar",)
    assert evento.problema_codigo == "CARIE"


async def test_alarme_pela_ia_registra_termo_generico() -> None:
    ia = ClassificacaoIA(codigo="CARIE", confianca=0.9, sinais_alarme=True)
    ambiente, _ = await registrar("dente furado", ia)
    (evento,) = [e for e in ambiente.publicador.eventos if isinstance(e, EmergenciaDetectada)]
    assert evento.termos_alarme == ("sinais de alarme indicados pela IA",)


async def test_paciente_sem_prontuario() -> None:
    ambiente = Ambiente()
    with pytest.raises(RecursoNaoEncontradoError):
        await ambiente.registrar_queixa.executar(
            RegistrarQueixaCommand(paciente_id=uuid7(), texto="dor de dente")
        )


class TestReclassificacao:
    async def test_reclassifica_manualmente(self) -> None:
        ambiente, paciente = await registrar("quero conversar", None)
        (queixa,) = ambiente.prontuario_de(paciente.id).queixas
        servico = ReclassificarQueixaService(uow=ambiente.uow, relogio=ambiente.relogio)
        resumo = await servico.executar(
            ReclassificarQueixaCommand(queixa_id=queixa.id, codigo_problema="GENGIVITE")
        )
        assert resumo.problema_codigo == "GENGIVITE"
        (gravada,) = ambiente.prontuario_de(paciente.id).queixas
        assert gravada.origem is OrigemClassificacao.MANUAL

    async def test_codigo_fora_do_catalogo(self) -> None:
        ambiente, paciente = await registrar("quero conversar", None)
        (queixa,) = ambiente.prontuario_de(paciente.id).queixas
        servico = ReclassificarQueixaService(uow=ambiente.uow, relogio=ambiente.relogio)
        with pytest.raises(DadoInvalidoError):
            await servico.executar(
                ReclassificarQueixaCommand(queixa_id=queixa.id, codigo_problema="XYZ")
            )
