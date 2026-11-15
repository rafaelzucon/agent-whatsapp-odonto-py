"""Classificação por palavras-chave: o plano B quando a IA falha ou tem baixa confiança."""

import pytest

from odonto.dominio.modelo.enums import Prioridade
from odonto.dominio.servico.classificador_palavra_chave import ClassificadorPorPalavraChave
from tests.apoio import CATALOGO_TESTE, problema

classificador = ClassificadorPorPalavraChave()


@pytest.mark.parametrize(
    ("texto", "codigo", "confianca", "termos"),
    [
        ("estou com dor de dente", "DOR_DE_DENTE", 0.7, ("dor de dente",)),
        ("tenho uma cárie, buraco no dente", "CARIE", 0.8, ("carie", "buraco no dente")),
        ("quero fazer LIMPEZA", "LIMPEZA_PROFILAXIA", 0.5, ("limpeza",)),
        ("dor no dente e gengiva sangrando", "DOR_DE_DENTE", 0.7, ("dor no dente",)),
    ],
)
def test_escolhe_o_item_com_mais_palavras_encontradas(
    texto: str, codigo: str, confianca: float, termos: tuple[str, ...]
) -> None:
    resultado = classificador.classificar(texto, CATALOGO_TESTE)
    assert resultado is not None
    assert (resultado.problema.codigo, resultado.confianca, resultado.termos) == (
        codigo,
        confianca,
        termos,
    )


def test_confianca_tem_teto() -> None:
    resultado = classificador.classificar(
        "dente furado, buraco no dente e dente escuro", CATALOGO_TESTE
    )
    assert resultado is not None
    assert resultado.problema.codigo == "CARIE"
    assert resultado.confianca == 0.9


def test_empate_fica_com_a_prioridade_mais_alta() -> None:
    resultado = classificador.classificar("dente furado e o dente caiu", CATALOGO_TESTE)
    assert resultado is not None
    assert resultado.problema.codigo == "AVULSAO_TRAUMA"


def test_empate_com_mesma_prioridade_fica_com_a_ordem_do_catalogo() -> None:
    resultado = classificador.classificar("limpeza e cárie", CATALOGO_TESTE)
    assert resultado is not None
    assert resultado.problema.codigo == "CARIE"


def test_ignora_itens_inativos() -> None:
    catalogo = (
        problema("ITEM_INATIVO", palavras_chave=("limpeza",), ativo=False),
        problema("LIMPEZA", prioridade=Prioridade.ROTINA, palavras_chave=("limpeza",)),
    )
    resultado = classificador.classificar("limpeza", catalogo)
    assert resultado is not None
    assert resultado.problema.codigo == "LIMPEZA"
    assert classificador.classificar("limpeza", catalogo[:1]) is None


@pytest.mark.parametrize("texto", ["olá, bom dia", "não tenho cárie", ""])
def test_sem_palavra_chave_devolve_none(texto: str) -> None:
    assert classificador.classificar(texto, CATALOGO_TESTE) is None
