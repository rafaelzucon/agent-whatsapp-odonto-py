import base64
import os

import pytest

from odonto.adaptador.saida.persistencia.criptografia import (
    ChaveInvalidaError,
    DadoCorrompidoError,
    ServicoCriptografia,
    decodificar_chave,
)

CHAVE = os.urandom(32)


def test_cifra_e_decifra_texto_com_acentos() -> None:
    servico = ServicoCriptografia(CHAVE)

    cifrado = servico.cifrar("Maria Conceição")

    assert "Maria" not in cifrado
    assert servico.decifrar(cifrado) == "Maria Conceição"


def test_nonce_aleatorio_gera_cifrados_diferentes_para_o_mesmo_texto() -> None:
    servico = ServicoCriptografia(CHAVE)

    assert servico.cifrar("dor de dente") != servico.cifrar("dor de dente")


def test_formato_e_base64_de_nonce_mais_cifrado_e_tag() -> None:
    bruto = base64.b64decode(ServicoCriptografia(CHAVE).cifrar("abc"))

    assert len(bruto) == 12 + 3 + 16


def test_dado_adulterado_e_rejeitado() -> None:
    servico = ServicoCriptografia(CHAVE)
    bruto = bytearray(base64.b64decode(servico.cifrar("texto")))
    bruto[-1] ^= 0x01

    with pytest.raises(DadoCorrompidoError):
        servico.decifrar(base64.b64encode(bytes(bruto)).decode())


def test_chave_diferente_nao_decifra() -> None:
    cifrado = ServicoCriptografia(CHAVE).cifrar("texto")

    with pytest.raises(DadoCorrompidoError):
        ServicoCriptografia(os.urandom(32)).decifrar(cifrado)


def test_texto_que_nao_e_base64_e_rejeitado() -> None:
    with pytest.raises(DadoCorrompidoError):
        ServicoCriptografia(CHAVE).decifrar("isso não é base64!")


@pytest.mark.parametrize("tamanho", [16, 31, 33, 64])
def test_chave_de_tamanho_errado_e_rejeitada_na_inicializacao(tamanho: int) -> None:
    valor = base64.b64encode(os.urandom(tamanho)).decode()

    with pytest.raises(ChaveInvalidaError, match="CHAVE_CRIPTOGRAFIA"):
        decodificar_chave(valor, "CHAVE_CRIPTOGRAFIA")
    with pytest.raises(ChaveInvalidaError):
        ServicoCriptografia(os.urandom(tamanho))


def test_chave_em_base64_invalido_e_rejeitada() -> None:
    with pytest.raises(ChaveInvalidaError, match="Base64"):
        decodificar_chave("@@@ não é base64 @@@", "CHAVE_CRIPTOGRAFIA")


def test_decodifica_chave_valida() -> None:
    assert decodificar_chave(base64.b64encode(CHAVE).decode(), "X") == CHAVE
