from datetime import time, timedelta

import pytest

from odonto.aplicacao.excecoes import ConfiguracaoInvalidaError
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import ChaveMensagem, DiaSemana
from odonto.infraestrutura.container import (
    configuracao_agenda,
    configuracao_conversa,
    configuracao_recebimento,
    configuracao_web,
    mensagens_conversa,
    montar_container,
    validar_configuracoes,
)
from tests.infraestrutura.conftest import FabricaConfiguracoes


def test_yaml_do_projeto_vira_configuracao_da_aplicacao(
    configuracoes: FabricaConfiguracoes,
) -> None:
    cfg = configuracoes(consultorio_whatsapp_notificacao="5511999990000")

    validar_configuracoes(cfg)
    agenda = configuracao_agenda(cfg)
    conversa = configuracao_conversa(cfg)

    assert agenda.funcionamento.abertura == time(8)
    assert agenda.funcionamento.duracao_consulta == timedelta(minutes=30)
    assert DiaSemana.SAB not in agenda.funcionamento.dias_atendimento
    assert str(agenda.funcionamento.fuso) == "America/Sao_Paulo"
    assert conversa.regras.expiracao == timedelta(hours=2)
    assert "Rua Exemplo" in conversa.endereco
    assert "NOME_CONSULTORIO" in mensagens_conversa(cfg).textos[ChaveMensagem.BOAS_VINDAS]
    # A variante sem o nono dígito também é ignorada (a Meta às vezes entrega assim).
    assert configuracao_recebimento(cfg).numeros_ignorados == {"5511999990000", "551199990000"}


def test_chave_de_mensagem_desconhecida_falha_cedo(configuracoes: FabricaConfiguracoes) -> None:
    cfg = configuracoes("conversa:\n  mensagens:\n    ola: 'Oi'\n")

    with pytest.raises(ConfiguracaoInvalidaError, match="ola"):
        validar_configuracoes(cfg)


def test_almoco_fora_do_expediente_falha_cedo(configuracoes: FabricaConfiguracoes) -> None:
    cfg = configuracoes('agendamento:\n  almoco_inicio: "19:00"\n  almoco_fim: "20:00"\n')

    with pytest.raises(DadoInvalidoError):
        validar_configuracoes(cfg)


def test_configuracao_web_sem_whatsapp(configuracoes: FabricaConfiguracoes) -> None:
    web = configuracao_web(configuracoes(None, admin_token="a" * 20))

    assert web.admin_token == "a" * 20
    assert web.phone_number_id is None
    assert web.app_secret == ""


async def test_monta_e_encerra_sem_tocar_no_banco(configuracoes: FabricaConfiguracoes) -> None:
    container = montar_container(
        configuracoes(None, anthropic_api_key="sk-ant", openai_api_key="sk-openai")
    )

    assert container.fila.tamanho == 0
    assert len(container.fechamentos) == 4  # engine, httpx, anthropic, openai
    await container.encerrar()
