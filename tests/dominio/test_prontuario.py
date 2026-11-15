"""Prontuário: registro e reclassificação de queixas."""

from uuid import uuid7

import pytest

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import OrigemClassificacao, Prioridade
from odonto.dominio.modelo.eventos import EmergenciaDetectada
from odonto.dominio.modelo.prontuario import Prontuario
from odonto.dominio.modelo.valores import NumeroProntuario
from tests.apoio import AGORA, buscar_no_catalogo

CARIE = buscar_no_catalogo("CARIE")
TRAUMA = buscar_no_catalogo("AVULSAO_TRAUMA")
DOR = buscar_no_catalogo("DOR_DE_DENTE")


def abrir() -> Prontuario:
    return Prontuario.abrir(paciente_id=uuid7(), numero=NumeroProntuario(7), momento=AGORA)


def test_queixa_de_rotina_nao_gera_evento() -> None:
    prontuario = abrir()
    queixa = prontuario.registrar_queixa(
        texto="  tenho uma cárie  ",
        problema=CARIE,
        prioridade=Prioridade.ROTINA,
        confianca=0.9,
        origem=OrigemClassificacao.IA,
        momento=AGORA,
        sintomas=["buraco no dente"],
    )
    assert queixa.texto_original == "tenho uma cárie"
    assert queixa.sintomas == ("buraco no dente",)
    assert prontuario.buscar_queixa(queixa.id) is queixa
    assert prontuario.coletar_eventos() == ()


def test_emergencia_gera_evento_uma_unica_vez() -> None:
    prontuario = abrir()
    queixa = prontuario.registrar_queixa(
        texto="meu dente caiu",
        problema=TRAUMA,
        prioridade=Prioridade.EMERGENCIA,
        confianca=0.8,
        origem=OrigemClassificacao.PALAVRA_CHAVE,
        momento=AGORA,
        termos_alarme=["dente caiu"],
    )
    (evento,) = prontuario.coletar_eventos()
    assert isinstance(evento, EmergenciaDetectada)
    assert evento.queixa_id == queixa.id
    assert evento.problema_codigo == "AVULSAO_TRAUMA"
    assert evento.termos_alarme == ("dente caiu",)
    assert prontuario.coletar_eventos() == ()


@pytest.mark.parametrize(("texto", "confianca"), [("   ", 0.5), ("dor", 1.5), ("dor", -0.1)])
def test_rejeita_queixa_invalida(texto: str, confianca: float) -> None:
    with pytest.raises(DadoInvalidoError):
        abrir().registrar_queixa(
            texto=texto,
            problema=CARIE,
            prioridade=Prioridade.ROTINA,
            confianca=confianca,
            origem=OrigemClassificacao.IA,
            momento=AGORA,
        )


def test_reclassificacao_manual_usa_prioridade_do_catalogo() -> None:
    prontuario = abrir()
    queixa = prontuario.registrar_queixa(
        texto="dói o dente",
        problema=CARIE,
        prioridade=Prioridade.ROTINA,
        confianca=0.4,
        origem=OrigemClassificacao.PALAVRA_CHAVE,
        momento=AGORA,
    )
    prontuario.reclassificar_queixa(queixa.id, problema=DOR, momento=AGORA)
    assert queixa.problema == DOR
    assert queixa.prioridade is Prioridade.URGENCIA
    assert queixa.origem is OrigemClassificacao.MANUAL
    assert queixa.confianca == 1.0
    assert queixa.reclassificada_em == AGORA

    prontuario.reclassificar_queixa(
        queixa.id, problema=DOR, momento=AGORA, prioridade=Prioridade.EMERGENCIA
    )
    assert queixa.prioridade is Prioridade.EMERGENCIA


def test_reclassificar_queixa_de_outro_prontuario() -> None:
    with pytest.raises(DadoInvalidoError):
        abrir().reclassificar_queixa(uuid7(), problema=DOR, momento=AGORA)


def test_vincular_consulta_a_queixa() -> None:
    prontuario = abrir()
    queixa = prontuario.registrar_queixa(
        texto="cárie",
        problema=CARIE,
        prioridade=Prioridade.ROTINA,
        confianca=0.9,
        origem=OrigemClassificacao.IA,
        momento=AGORA,
    )
    consulta_id = uuid7()
    assert prontuario.vincular_consulta(queixa.id, consulta_id).consulta_id == consulta_id
    with pytest.raises(DadoInvalidoError):
        prontuario.vincular_consulta(uuid7(), consulta_id)
