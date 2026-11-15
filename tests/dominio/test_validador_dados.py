"""Validação do que o paciente digita: RG + UF, nome, data de nascimento, SIM/NÃO e cortesia."""

from datetime import date

import pytest

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import Uf
from odonto.dominio.servico.validador_dados import ValidadorDados
from tests.apoio import HOJE


@pytest.mark.parametrize(
    ("texto", "numero", "uf"),
    [
        ("12.345.678-9 SP", "123456789", Uf.SP),
        ("RG 12.345.678-X SSP/SP", "12345678X", Uf.SP),
        ("12.345.678-x sp", "12345678X", Uf.SP),
        ("12345678 minas gerais", "12345678", Uf.MG),
        ("SSPSP 123456789", "123456789", Uf.SP),
        ("123.456.789-0 ssp-ba", "1234567890", Uf.BA),
        ("rg 12345678 de brasilia", "12345678", Uf.DF),
        ("MG-12.345.678", "12345678", Uf.MG),
        ("Meu RG é 9876543, emitido no Rio de Janeiro", "9876543", Uf.RJ),
        ("1234567 São Paulo", "1234567", Uf.SP),
    ],
)
def test_rg_em_formatos_livres(texto: str, numero: str, uf: Uf) -> None:
    documento = ValidadorDados.rg(texto)
    assert (documento.numero, documento.uf) == (numero, uf)


@pytest.mark.parametrize(
    ("texto", "campo"),
    [
        ("1234 SP", "rg"),
        ("12345678", "uf"),
        ("12345678 XX", "uf"),
        ("não sei", "rg"),
        ("", "rg"),
    ],
)
def test_rg_invalido(texto: str, campo: str) -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        ValidadorDados.rg(texto)
    assert erro.value.campo == campo


@pytest.mark.parametrize(
    ("texto", "nome"),
    [
        ("meu nome é joão de souza", "João de Souza"),
        ("Me chamo ANA PAULA DOS SANTOS", "Ana Paula dos Santos"),
        ("O nome completo: maria d'ávila", "Maria d'Ávila"),
        ("  pedro   henrique  ", "Pedro Henrique"),
        ("Ana-Clara Souza", "Ana-Clara Souza"),
    ],
)
def test_nome_completo(texto: str, nome: str) -> None:
    assert ValidadorDados.nome_completo(texto) == nome


@pytest.mark.parametrize(
    "texto", ["Oi bom dia", "joão", "quero marcar consulta", "Maria 123", "", "@@@ ###"]
)
def test_nome_invalido(texto: str) -> None:
    with pytest.raises(DadoInvalidoError):
        ValidadorDados.nome_completo(texto)


def test_nome_do_responsavel_usa_o_proprio_campo() -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        ValidadorDados.nome_completo("joana", "responsavel")
    assert erro.value.campo == "responsavel"


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("15/03/1990", date(1990, 3, 15)),
        ("15-03-1990", date(1990, 3, 15)),
        ("15.03.90", date(1990, 3, 15)),
        ("15031990", date(1990, 3, 15)),
        ("1º de janeiro de 2000", date(2000, 1, 1)),
        ("nasci em 5 de março de 1985", date(1985, 3, 5)),
        ("01/06/15", date(2015, 6, 1)),
    ],
)
def test_data_de_nascimento(texto: str, esperada: date) -> None:
    assert ValidadorDados.data_nascimento(texto, HOJE) == esperada


@pytest.mark.parametrize("texto", ["31/02/2000", "19/11/2026", "01/01/1890", "ontem", "15/13/1990"])
def test_data_de_nascimento_invalida(texto: str) -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        ValidadorDados.data_nascimento(texto, HOJE)
    assert erro.value.campo == "data_nascimento"


@pytest.mark.parametrize(
    ("texto", "resposta"),
    [
        ("sim", True),
        ("SIM", True),
        ("Sim!", True),
        ("s", True),
        ("claro", True),
        ("pode ser", True),
        ("sem dúvida", True),
        ("👍", True),
        ("não", False),
        ("nao", False),
        ("NÃO", False),
        ("Não, obrigado", False),
        ("n", False),
        ("👎", False),
        ("sim não", False),
        ("não sei", None),
        ("Sim 123", None),
        ("não posso amanhã", None),
        ("talvez", None),
        ("", None),
    ],
)
def test_sim_nao_com_e_sem_acento(texto: str, resposta: bool | None) -> None:
    assert ValidadorDados.sim_nao(texto) is resposta


@pytest.mark.parametrize(
    ("texto", "cortesia"),
    [
        ("obrigado", True),
        ("Obrigada!!", True),
        ("ok", True),
        ("valeu, até mais", True),
        ("Obrigada! Até sexta 👍", True),
        ("👍🙏", True),
        ("...", True),
        ("oi", False),
        ("bom dia", False),
        ("quero remarcar", False),
        ("ok, mas preciso mudar o horário", False),
    ],
)
def test_cortesia(texto: str, cortesia: bool) -> None:
    assert ValidadorDados.e_cortesia(texto) is cortesia
