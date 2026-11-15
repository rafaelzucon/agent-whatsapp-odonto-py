"""Avisos ao consultório: conteúdo, ordem dos parâmetros e isolamento de falhas dos canais."""

from uuid import uuid7

from odonto.aplicacao.portas.saida.notificacao import TipoAlerta
from odonto.dominio.modelo.enums import EtapaConversa, OrigemAgendamento, Prioridade
from odonto.dominio.modelo.eventos import (
    AtendimentoHumanoNecessario,
    ConsentimentoRecusado,
    ConsultaAgendada,
    EmergenciaDetectada,
)
from odonto.dominio.modelo.paciente import Paciente
from tests.aplicacao.fakes import Ambiente, CanalFalso
from tests.apoio import AGORA, WA_ID, em


def agendada(paciente: Paciente, origem: OrigemAgendamento) -> ConsultaAgendada:
    return ConsultaAgendada(
        consulta_id=uuid7(),
        paciente_id=paciente.id,
        queixa_id=None,
        inicio=em(2026, 11, 20, 14, 30),
        prioridade=Prioridade.ROTINA,
        origem=origem,
        ocorrido_em=AGORA,
    )


async def test_falha_de_um_canal_nao_impede_os_outros() -> None:
    quebrado, email, log = (
        CanalFalso("whatsapp", falhar=True),
        CanalFalso("email"),
        CanalFalso("log"),
    )
    ambiente = Ambiente(canais=[quebrado, email, log])
    paciente = await ambiente.cadastrar_paciente_existente()

    await ambiente.notificar.notificar(agendada(paciente, OrigemAgendamento.WHATSAPP))

    assert quebrado.avisos == []
    assert len(email.avisos) == len(log.avisos) == 1


async def test_aviso_de_agendamento_tem_4_parametros_na_ordem() -> None:
    canal = CanalFalso()
    ambiente = Ambiente(canais=[canal])
    paciente = await ambiente.cadastrar_paciente_existente()

    await ambiente.notificar.notificar(agendada(paciente, OrigemAgendamento.WHATSAPP))

    (aviso,) = canal.avisos
    assert aviso.parametros_template() == (
        "Maria da Silva",
        "sexta-feira, 20/11/2026 às 14:30",
        "Não informado",
        "Rotina",
    )
    assert aviso.prontuario == "PR-000001"


async def test_agendamento_feito_pela_recepcao_nao_gera_aviso() -> None:
    canal = CanalFalso()
    ambiente = Ambiente(canais=[canal])
    paciente = await ambiente.cadastrar_paciente_existente()
    await ambiente.notificar.notificar(agendada(paciente, OrigemAgendamento.RECEPCAO))
    assert canal.avisos == []


async def test_alerta_de_emergencia_tem_3_parametros_na_ordem() -> None:
    canal = CanalFalso()
    ambiente = Ambiente(canais=[canal])
    paciente = await ambiente.cadastrar_paciente_existente()

    await ambiente.notificar.notificar(
        EmergenciaDetectada(
            paciente_id=paciente.id,
            queixa_id=uuid7(),
            problema_codigo="CELULITE_ABSCESSO_FACE",
            problema_nome="Celulite ou abscesso na face",
            termos_alarme=("rosto inchado", "febre alta"),
            ocorrido_em=AGORA,
        )
    )

    (alerta,) = canal.alertas
    assert alerta.parametros_template() == (
        "Emergência odontológica",
        "Maria da Silva",
        "Celulite ou abscesso na face; sinais: rosto inchado, febre alta",
    )
    assert alerta.prioridade is Prioridade.EMERGENCIA
    assert alerta.contato == "5511900001111"


async def test_alertas_sem_paciente_identificam_pelo_final_do_numero() -> None:
    canal = CanalFalso()
    ambiente = Ambiente(canais=[canal])

    await ambiente.notificar.notificar(ConsentimentoRecusado(wa_id=WA_ID, ocorrido_em=AGORA))
    await ambiente.notificar.notificar(
        AtendimentoHumanoNecessario(
            wa_id=WA_ID,
            paciente_id=None,
            motivo="Respostas inválidas repetidas",
            etapa=EtapaConversa.AGUARDANDO_RG,
            prioridade=None,
            ocorrido_em=AGORA,
        )
    )

    recusa, humano = canal.alertas
    assert recusa.tipo is TipoAlerta.CONSENTIMENTO_RECUSADO
    assert recusa.paciente == humano.paciente == "WhatsApp com final 4321"
    assert humano.tipo is TipoAlerta.ATENDIMENTO_HUMANO
    assert humano.resumo == "Respostas inválidas repetidas"
    assert humano.contato == WA_ID.valor
