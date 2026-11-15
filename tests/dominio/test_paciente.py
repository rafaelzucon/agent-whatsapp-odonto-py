"""Cadastro do paciente: nome completo, idade plausível e responsável legal do menor."""

from datetime import date
from uuid import uuid7

import pytest

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.valores import WaId
from tests.apoio import AGORA, HOJE, NASCIMENTO_ADULTO, NASCIMENTO_MENOR, RG, WA_ID


def cadastrar(**alteracoes: object) -> Paciente:
    campos: dict[str, object] = {
        "documento": RG,
        "nome": "  Maria   da Silva ",
        "data_nascimento": NASCIMENTO_ADULTO,
        "responsavel": None,
        "wa_id": WA_ID,
        "momento": AGORA,
    }
    campos.update(alteracoes)
    return Paciente.cadastrar(**campos)  # type: ignore[arg-type]


def test_cadastra_adulto_com_consentimento_e_telefone() -> None:
    paciente = cadastrar()
    assert paciente.nome == "Maria da Silva"
    assert paciente.primeiro_nome == "Maria"
    assert paciente.telefones == [WA_ID]
    assert paciente.consentimento_lgpd
    assert paciente.consentimento_em == AGORA
    assert paciente.idade(HOJE) == 36
    assert not paciente.e_menor_de_idade(HOJE)


def test_menor_de_idade_exige_responsavel() -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        cadastrar(data_nascimento=NASCIMENTO_MENOR)
    assert erro.value.campo == "responsavel"


def test_menor_de_idade_com_responsavel() -> None:
    paciente = cadastrar(data_nascimento=NASCIMENTO_MENOR, responsavel="joana  da silva")
    assert paciente.e_menor_de_idade(HOJE)
    assert paciente.responsavel == "joana da silva"


@pytest.mark.parametrize("nascimento", [date(2026, 11, 19), date(1900, 1, 1)])
def test_rejeita_data_de_nascimento_implausivel(nascimento: date) -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        cadastrar(data_nascimento=nascimento)
    assert erro.value.campo == "data_nascimento"


@pytest.mark.parametrize("nome", ["Maria", "  ", "Maria 123", "A" * 60 + " " + "B" * 60])
def test_rejeita_nome_incompleto_ou_longo(nome: str) -> None:
    with pytest.raises(DadoInvalidoError) as erro:
        cadastrar(nome=nome)
    assert erro.value.campo == "nome"


def test_vincular_telefone_nao_duplica() -> None:
    paciente = cadastrar()
    outro = WaId("5511912345678")
    assert paciente.vincular_telefone(outro)
    assert not paciente.vincular_telefone(outro)
    assert paciente.telefones == [WA_ID, outro]


def test_dados_pessoais_fora_do_repr() -> None:
    texto = repr(cadastrar())
    assert "Maria" not in texto
    assert "1990" not in texto
    assert RG.numero not in texto


def test_igualdade_por_identidade() -> None:
    identificador = uuid7()
    assert cadastrar(id=identificador) == cadastrar(id=identificador, nome="Outro Nome")
    assert cadastrar() != cadastrar()
