"""Sinais de alarme: transformam a queixa em EMERGÊNCIA, seja qual for a classificação."""

import pytest

from odonto.dominio.servico.detector_sinais_alarme import DetectorSinaisAlarme


@pytest.mark.parametrize(
    ("texto", "termos"),
    [
        ("estou com FALTA DE AR", ("falta de ar",)),
        (
            "Meu rosto está todo inchado e estou com febre alta",
            ("rosto esta inchado", "febre alta"),
        ),
        ("não aguento, rosto inchado", ("rosto inchado",)),
        ("bati o dente na mesa", ("bati o dente",)),
        ("Sofri um acidente de moto e o dente caiu", ("dente caiu", "acidente")),
    ],
)
def test_aciona_com_sinais_de_alarme(texto: str, termos: tuple[str, ...]) -> None:
    resultado = DetectorSinaisAlarme().analisar(texto)
    assert resultado.acionado
    assert resultado.termos == termos


@pytest.mark.parametrize(
    "texto",
    [
        "não tenho falta de ar",
        "dor sem febre alta",
        "nem febre alta nem falta de ar",
        "o rosto não está inchado",
        "A restauração do dente caiu",
        "caiu um pedaço do dente",
        "meu dente de leite caiu",
        "tenho trauma de dentista",
        "dor de dente",
        "",
    ],
)
def test_nao_aciona_com_negacao_ou_expressao_benigna(texto: str) -> None:
    resultado = DetectorSinaisAlarme().analisar(texto)
    assert not resultado.acionado
    assert resultado.termos == ()


def test_tolera_palavras_extras_dentro_do_termo_conforme_intervalo() -> None:
    assert DetectorSinaisAlarme().analisar("rosto todo inchado").acionado
    assert not DetectorSinaisAlarme(intervalo=0).analisar("rosto todo inchado").acionado
    assert not DetectorSinaisAlarme().analisar("rosto muito muito inchado").acionado


def test_lista_configuravel_e_normalizada() -> None:
    detector = DetectorSinaisAlarme(["Língua roxa", "  ", "língua roxa"])
    assert detector.analisar("minha LINGUA está roxa").termos == ("lingua roxa",)
    assert not detector.analisar("febre alta").acionado
