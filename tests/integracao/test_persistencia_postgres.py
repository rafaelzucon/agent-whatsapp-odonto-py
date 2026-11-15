from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from odonto.dominio.excecoes import HorarioIndisponivelError, MotivoIndisponibilidade
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import Conversa
from odonto.dominio.modelo.enums import (
    OrigemAgendamento,
    OrigemClassificacao,
    Prioridade,
    TipoMensagem,
)
from odonto.dominio.modelo.eventos import ConsultaAgendada
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.prontuario import Prontuario
from odonto.dominio.modelo.valores import DocumentoRg, Horario, WaId
from tests.integracao.conftest import Banco

pytestmark = pytest.mark.integracao

AGORA = datetime.now(UTC).replace(microsecond=0)
WA = WaId("5511999990000")
RG = DocumentoRg.criar("12.345.678-x", "sp")


def mensagem(wa_message_id: str) -> Mensagem:
    return Mensagem.recebida(
        wa_id=WA,
        wa_message_id=wa_message_id,
        tipo=TipoMensagem.TEXTO,
        texto="oi, estou com dor",
        midia_id=None,
        momento=AGORA,
        criada_em=AGORA,
    )


async def test_fluxo_completo_com_criptografia_conflito_e_eventos(banco: Banco) -> None:
    uow = banco.uow
    horario = Horario.com_duracao(AGORA + timedelta(days=2), timedelta(minutes=30))
    async with uow:
        paciente = Paciente.cadastrar(
            documento=RG,
            nome="Maria Silva",
            data_nascimento=date(1990, 1, 2),
            responsavel=None,
            wa_id=WA,
            momento=AGORA,
        )
        await uow.pacientes.adicionar(paciente, hash_documento=banco.cifrador.hash_busca(RG))
        async with uow:  # transação aninhada: o commit interno não efetiva
            prontuario = Prontuario.abrir(
                paciente_id=paciente.id,
                numero=await uow.prontuarios.proximo_numero(),
                momento=AGORA,
            )
            await uow.prontuarios.adicionar(prontuario)
            await uow.commit()
        problema = await uow.catalogo.buscar_por_codigo("DOR_DE_DENTE")
        assert problema is not None
        queixa = prontuario.registrar_queixa(
            texto="dor de dente forte",
            problema=problema,
            prioridade=Prioridade.URGENCIA,
            confianca=0.9,
            origem=OrigemClassificacao.IA,
            momento=AGORA,
            sintomas=["latejante"],
        )
        consulta = Consulta.agendar(
            paciente_id=paciente.id,
            queixa_id=queixa.id,
            horario=horario,
            prioridade=Prioridade.URGENCIA,
            origem=OrigemAgendamento.WHATSAPP,
            momento=AGORA,
        )
        await uow.prontuarios.salvar(prontuario)
        await uow.consultas.adicionar(consulta)
        prontuario.vincular_consulta(queixa.id, consulta.id)
        await uow.prontuarios.salvar(prontuario)

        concorrente = Consulta.agendar(
            paciente_id=paciente.id,
            queixa_id=None,
            horario=horario,
            prioridade=Prioridade.ROTINA,
            origem=OrigemAgendamento.RECEPCAO,
            momento=AGORA,
        )
        with pytest.raises(HorarioIndisponivelError) as erro:
            await uow.consultas.adicionar(concorrente)
        assert erro.value.motivo is MotivoIndisponibilidade.OCUPADO
        # O savepoint isolou a falha: a transação continua utilizável.
        assert len(await uow.consultas.listar_entre(AGORA, AGORA + timedelta(days=5))) == 1
        assert banco.publicador.eventos == []
        await uow.commit()

    assert [type(e) for e in banco.publicador.eventos] == [ConsultaAgendada]

    async with uow:
        hash_rg = banco.cifrador.hash_busca(DocumentoRg.criar("12345678X", "SP"))
        encontrado = await uow.pacientes.buscar_por_hash_documento(hash_rg)
        assert encontrado is not None
        assert (encontrado.nome, encontrado.documento, encontrado.telefones) == (
            "Maria Silva",
            RG,
            [WA],
        )
        lido = await uow.prontuarios.buscar_por_queixa(queixa.id)
        assert lido is not None
        [queixa_lida] = lido.queixas
        assert queixa_lida.texto_original == "dor de dente forte"
        assert queixa_lida.consulta_id == consulta.id

    async with banco.engine.connect() as conexao:
        nome, rg_hash = (
            await conexao.execute(text("select nome_cifrado, rg_hash from paciente"))
        ).one()
        texto_queixa = (
            await conexao.execute(text("select texto_cifrado from queixa_relatada"))
        ).scalar_one()
    assert "Maria" not in nome
    assert "dor" not in texto_queixa
    assert rg_hash == hash_rg


async def test_mensagem_repetida_nao_e_gravada_duas_vezes(banco: Banco) -> None:
    async with banco.uow as uow:
        conversa, _ = Conversa.iniciar(WA, AGORA)
        await uow.conversas.salvar(conversa)
        assert await uow.mensagens.adicionar_se_nova(mensagem("wamid.1"))
        await uow.commit()
    async with banco.uow as uow:
        assert not await uow.mensagens.adicionar_se_nova(mensagem("wamid.1"))
        assert len(await uow.mensagens.listar_pendentes()) == 1


async def test_saida_sem_commit_desfaz_tudo(banco: Banco) -> None:
    inicio = AGORA + timedelta(days=1)
    async with banco.uow as uow:
        await uow.bloqueios.adicionar(
            BloqueioAgenda.criar(
                inicio=inicio, fim=inicio + timedelta(hours=1), motivo="curso", momento=AGORA
            )
        )
    async with banco.uow as uow:
        assert await uow.bloqueios.listar_entre(AGORA, AGORA + timedelta(days=5)) == []
