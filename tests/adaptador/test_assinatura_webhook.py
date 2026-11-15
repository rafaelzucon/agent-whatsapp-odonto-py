import hashlib
import hmac

import pytest

from odonto.adaptador.entrada.web.assinatura_webhook import assinatura_valida, calcular_assinatura

SEGREDO = "segredo-do-app"
CORPO = b'{"object":"whatsapp_business_account","entry":[]}'


def test_calcula_no_formato_da_meta() -> None:
    esperado = "sha256=" + hmac.new(SEGREDO.encode(), CORPO, hashlib.sha256).hexdigest()

    assert calcular_assinatura(CORPO, SEGREDO) == esperado


def test_aceita_assinatura_correta() -> None:
    assert assinatura_valida(CORPO, calcular_assinatura(CORPO, SEGREDO), SEGREDO)


@pytest.mark.parametrize(
    "cabecalho",
    [
        None,
        "",
        "sha256=",
        "sha256=" + "0" * 64,
        calcular_assinatura(CORPO, "outro-segredo"),
        calcular_assinatura(CORPO + b" ", SEGREDO),
        calcular_assinatura(CORPO, SEGREDO).removeprefix("sha256="),
    ],
)
def test_rejeita_assinatura_ausente_ou_errada(cabecalho: str | None) -> None:
    assert not assinatura_valida(CORPO, cabecalho, SEGREDO)


def test_sem_segredo_configurado_rejeita_tudo() -> None:
    assert not assinatura_valida(CORPO, calcular_assinatura(CORPO, ""), "")
