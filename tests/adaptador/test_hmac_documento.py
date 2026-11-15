import os

import pytest

from odonto.adaptador.saida.persistencia.criptografia import (
    ChaveInvalidaError,
    HmacCifradorDocumento,
)
from odonto.dominio.modelo.valores import DocumentoRg

CIFRADOR = HmacCifradorDocumento(os.urandom(32))


def test_mesmo_rg_com_pontuacao_diferente_gera_o_mesmo_hash() -> None:
    a = CIFRADOR.hash_busca(DocumentoRg.criar("12.345.678-9", "SP"))
    b = CIFRADOR.hash_busca(DocumentoRg.criar("123456789", "sp"))

    assert a == b
    assert len(a) == 64
    assert "123456789" not in a


def test_uf_diferente_gera_hash_diferente() -> None:
    assert CIFRADOR.hash_busca(DocumentoRg.criar("123456789", "SP")) != CIFRADOR.hash_busca(
        DocumentoRg.criar("123456789", "RJ")
    )


def test_chave_diferente_gera_hash_diferente() -> None:
    rg = DocumentoRg.criar("123456789", "SP")

    assert CIFRADOR.hash_busca(rg) != HmacCifradorDocumento(os.urandom(32)).hash_busca(rg)


def test_chave_de_tamanho_errado_e_rejeitada() -> None:
    with pytest.raises(ChaveInvalidaError):
        HmacCifradorDocumento(b"curta")
