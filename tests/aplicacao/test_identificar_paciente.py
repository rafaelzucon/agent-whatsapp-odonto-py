"""Identificação e cadastro do paciente (busca pelo hash do RG + UF)."""

from datetime import timedelta

from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaCommand
from odonto.aplicacao.portas.entrada.pacientes import (
    CadastrarPacienteCommand,
    IdentificarPacienteCommand,
)
from odonto.dominio.modelo.enums import OrigemAgendamento
from odonto.dominio.modelo.valores import DocumentoRg, WaId
from tests.aplicacao.fakes import Ambiente
from tests.apoio import NASCIMENTO_ADULTO, RG, WA_ID, em


async def test_encontra_pelo_hash_do_documento_em_qualquer_formato() -> None:
    ambiente = Ambiente()
    paciente = await ambiente.cadastrar_paciente_existente()
    assert ambiente.banco.estado.hashes == {"hash:123456789:SP": paciente.id}

    identificado = await ambiente.identificar.executar(
        IdentificarPacienteCommand(documento=DocumentoRg.criar("12345678-9", "sp"), wa_id=WA_ID)
    )

    assert identificado is not None
    assert identificado.paciente_id == paciente.id
    assert identificado.primeiro_nome == "Maria"
    assert identificado.consulta_futura is None
    assert ambiente.pacientes[0].telefones == [WaId("5511900001111"), WA_ID]


async def test_uf_diferente_nao_encontra() -> None:
    ambiente = Ambiente()
    await ambiente.cadastrar_paciente_existente()
    identificado = await ambiente.identificar.executar(
        IdentificarPacienteCommand(documento=DocumentoRg.criar("12.345.678-9", "RJ"), wa_id=WA_ID)
    )
    assert identificado is None


async def test_informa_a_proxima_consulta_agendada() -> None:
    ambiente = Ambiente()
    paciente = await ambiente.cadastrar_paciente_existente()
    inicio = em(2026, 11, 23, 15, 0)
    await ambiente.agendar.executar(
        AgendarConsultaCommand(
            paciente_id=paciente.id, inicio=inicio, origem=OrigemAgendamento.RECEPCAO
        )
    )
    identificado = await ambiente.identificar.executar(
        IdentificarPacienteCommand(documento=RG, wa_id=WA_ID)
    )
    assert identificado is not None
    assert identificado.consulta_futura == inicio


async def test_cadastro_e_idempotente_pelo_documento() -> None:
    ambiente = Ambiente()
    primeiro = await ambiente.cadastrar_paciente_existente()
    ambiente.relogio.avancar(timedelta(minutes=5))
    repetido = await ambiente.cadastrar.executar(
        CadastrarPacienteCommand(
            documento=RG,
            nome="Maria S.",
            data_nascimento=NASCIMENTO_ADULTO,
            responsavel=None,
            wa_id=WA_ID,
        )
    )
    assert repetido.paciente_id == primeiro.id
    assert str(repetido.numero_prontuario) == "PR-000001"
    (paciente,) = ambiente.pacientes
    assert paciente.nome == "Maria da Silva"
    assert WA_ID in paciente.telefones
