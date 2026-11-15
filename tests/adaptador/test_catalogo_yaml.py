import re

from odonto.adaptador.saida.persistencia.catalogo_yaml import ler_catalogo
from odonto.dominio.modelo.enums import Prioridade
from odonto.dominio.modelo.problema import CODIGO_AVALIACAO_GERAL
from odonto.dominio.servico.classificador_palavra_chave import ClassificadorPorPalavraChave

CATALOGO = ler_catalogo()
POR_CODIGO = {p.codigo: p for p in CATALOGO}


def test_catalogo_tem_codigos_unicos_e_avaliacao_geral() -> None:
    assert len(CATALOGO) >= 50
    assert len(POR_CODIGO) == len(CATALOGO)
    assert CODIGO_AVALIACAO_GERAL in POR_CODIGO


def test_todos_os_itens_tem_cid10_e_palavras_chave() -> None:
    for problema in CATALOGO:
        assert re.fullmatch(r"[A-Z]\d{2}(\.\d{1,2})?", problema.cid10), problema.codigo
        assert problema.descricao
        assert problema.especialidade
        if problema.codigo != CODIGO_AVALIACAO_GERAL:
            assert problema.palavras_chave, problema.codigo


def test_ha_itens_de_todas_as_prioridades() -> None:
    assert {p.prioridade for p in CATALOGO} == set(Prioridade)


def test_frases_coloquiais_sao_classificadas_pelo_catalogo_real() -> None:
    classificador = ClassificadorPorPalavraChave()
    casos = {
        "meu dente caiu depois de uma pancada": Prioridade.EMERGENCIA,
        "estou com uma afta enorme na língua": Prioridade.ROTINA,
        "quero fazer uma limpeza": Prioridade.ROTINA,
    }
    for frase, prioridade in casos.items():
        resultado = classificador.classificar(frase, CATALOGO)
        assert resultado is not None, frase
        assert resultado.problema.prioridade is prioridade, (frase, resultado.problema.codigo)
