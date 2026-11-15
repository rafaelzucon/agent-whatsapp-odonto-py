from datetime import date, timedelta
from uuid import uuid4

from odonto.adaptador.saida.persistencia.mappers import (
    consulta_do_orm,
    consulta_para_orm,
    dados_conversa_do_json,
    dados_conversa_para_json,
    paciente_do_orm,
    paciente_para_orm,
)
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import DadosConversa
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.valores import DocumentoRg, Horario, NumeroProntuario
from tests.apoio import AGORA, RG, WA_ID, em


def test_dados_da_conversa_completos_ida_e_volta() -> None:
    dados = DadosConversa(
        documento=DocumentoRg.criar("12.345.678-X", "MG"),
        nome="João da Silva",
        data_nascimento=date(2012, 2, 29),
        responsavel="Ana da Silva",
        paciente_id=uuid4(),
        nome_paciente="João da Silva",
        numero_prontuario=NumeroProntuario(42),
        queixa_id=uuid4(),
        prioridade=Prioridade.URGENCIA,
        horario_sugerido=em(2026, 11, 20, 10, 30),
        consulta_futura=em(2026, 12, 1, 8),
        consulta_id=uuid4(),
    )

    assert dados_conversa_do_json(dados_conversa_para_json(dados)) == dados


def test_dados_da_conversa_vazios_ida_e_volta() -> None:
    texto = dados_conversa_para_json(DadosConversa())

    assert dados_conversa_do_json(texto) == DadosConversa()
    assert texto == "{}"


def test_horario_preserva_o_fuso() -> None:
    dados = DadosConversa(horario_sugerido=em(2026, 11, 20, 10, 30))

    volta = dados_conversa_do_json(dados_conversa_para_json(dados))

    assert volta.horario_sugerido is not None
    assert volta.horario_sugerido.utcoffset() == timedelta(hours=-3)


def test_paciente_ida_e_volta() -> None:
    paciente = Paciente.cadastrar(
        documento=RG,
        nome="Maria Souza",
        data_nascimento=date(1990, 3, 15),
        responsavel=None,
        wa_id=WA_ID,
        momento=AGORA,
    )

    orm = paciente_para_orm(paciente, rg_hash="h" * 64)
    volta = paciente_do_orm(orm)

    assert orm.rg_hash == "h" * 64
    assert (volta.id, volta.documento, volta.nome, volta.data_nascimento) == (
        paciente.id,
        paciente.documento,
        paciente.nome,
        paciente.data_nascimento,
    )
    assert volta.telefones == paciente.telefones


def test_consulta_ida_e_volta() -> None:
    consulta = Consulta.agendar(
        paciente_id=uuid4(),
        queixa_id=uuid4(),
        horario=Horario(em(2026, 11, 20, 10), em(2026, 11, 20, 10, 30)),
        prioridade=Prioridade.URGENCIA,
        origem=OrigemAgendamento.WHATSAPP,
        momento=AGORA,
    )

    volta = consulta_do_orm(consulta_para_orm(consulta))

    assert (volta.id, volta.horario, volta.status, volta.prioridade, volta.origem) == (
        consulta.id,
        consulta.horario,
        consulta.status,
        consulta.prioridade,
        consulta.origem,
    )
    assert volta.coletar_eventos() == ()
