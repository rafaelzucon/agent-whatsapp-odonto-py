from datetime import date, time
from pathlib import Path

import pytest
from pydantic import ValidationError

from odonto.dominio.modelo.enums import DiaSemana
from odonto.infraestrutura.config import VARIAVEL_ARQUIVO, carregar_configuracoes
from tests.infraestrutura.conftest import CHAVE_A, FabricaConfiguracoes


def test_yaml_do_projeto_carrega(configuracoes: FabricaConfiguracoes) -> None:
    cfg = configuracoes()

    assert cfg.database_url == "postgresql+psycopg://odonto:senha@banco:5432/odonto"
    assert cfg.nome_fuso == "America/Sao_Paulo"
    assert cfg.agendamento.almoco_inicio == time(12)
    assert cfg.agendamento.dias_atendimento[0] is DiaSemana.SEG
    assert date(2026, 12, 25) in cfg.agendamento.feriados
    assert cfg.conversa.mensagens["boas_vindas"].startswith("Olá!")
    assert cfg.api.docs_habilitada is False


def test_horario_sem_aspas_no_yaml_vira_hora(configuracoes: FabricaConfiguracoes) -> None:
    cfg = configuracoes("agendamento:\n  almoco_inicio: 12:00\n  almoco_fim: 13:30\n")

    assert cfg.agendamento.almoco_inicio == time(12)
    assert cfg.agendamento.almoco_fim == time(13, 30)


def test_variavel_de_ambiente_tem_precedencia_sobre_o_yaml(
    configuracoes: FabricaConfiguracoes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FUSO", "America/Manaus")
    monkeypatch.setenv("LOG_NIVEL", "DEBUG")

    cfg = configuracoes()

    assert cfg.nome_fuso == "America/Manaus"
    assert cfg.log_nivel == "DEBUG"


def test_sem_yaml_usa_padroes_e_tz(configuracoes: FabricaConfiguracoes) -> None:
    cfg = configuracoes(None, tz="America/Recife")

    assert cfg.nome_fuso == "America/Recife"
    assert cfg.agendamento.duracao_minutos == 30


@pytest.mark.parametrize(
    ("valores", "trecho"),
    [
        ({"chave_hmac_documento": CHAVE_A}, "devem ser diferentes"),
        ({"chave_criptografia": "curta"}, "Gere com"),
        ({"admin_token": "curto"}, "16+"),
        ({"database_url": "mysql://x"}, "postgresql://"),
        ({"fuso": "Marte/Olimpo"}, "Fuso horário desconhecido"),
        ({"whatsapp_api_version": "24"}, "whatsapp_api_version"),
    ],
)
def test_valores_invalidos_sao_recusados(
    configuracoes: FabricaConfiguracoes, valores: dict[str, str], trecho: str
) -> None:
    with pytest.raises(ValidationError, match=trecho):
        configuracoes(None, **valores)


def test_secao_desconhecida_no_yaml_e_recusada(configuracoes: FabricaConfiguracoes) -> None:
    with pytest.raises(ValidationError, match="extra"):
        configuracoes("agendamento:\n  duracao: 30\n")


def test_arquivo_informado_inexistente_e_erro(
    isolado: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VARIAVEL_ARQUIVO, str(isolado / "nao_existe.yaml"))

    with pytest.raises(FileNotFoundError):
        carregar_configuracoes()


def test_recursos_opcionais_e_pendencias(configuracoes: FabricaConfiguracoes) -> None:
    vazio = configuracoes(None)
    completo = configuracoes(
        None,
        whatsapp_phone_number_id="123",
        whatsapp_access_token="token",
        whatsapp_app_secret="segredo",
        whatsapp_verify_token="verificacao",
        consultorio_whatsapp_notificacao="5511999990000",
        admin_token="x" * 16,
        anthropic_api_key="sk-ant",
        openai_api_key="sk-openai",
        smtp_host="smtp.exemplo.com",
        consultorio_email="recepcao@exemplo.com",
    )

    assert not vazio.ia_habilitada
    assert not vazio.transcricao_habilitada
    assert not vazio.email_habilitado
    assert len(vazio.pendencias()) == 7
    assert completo.ia_habilitada
    assert completo.transcricao_habilitada
    assert completo.aviso_whatsapp_habilitado
    assert completo.email_habilitado
    assert completo.pendencias() == []
    assert configuracoes(None, transcricao_provedor="none").pendencias() == [
        p for p in vazio.pendencias() if not p.startswith("OPENAI")
    ]
