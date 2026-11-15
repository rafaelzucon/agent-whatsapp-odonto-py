"""Configurações de teste isoladas do ``.env`` e das variáveis de ambiente da máquina."""

import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from odonto.infraestrutura.config import VARIAVEL_ARQUIVO, Configuracoes, carregar_configuracoes

RAIZ = Path(__file__).resolve().parents[2]
YAML_DO_PROJETO = RAIZ / "config" / "odonto.yaml"

CHAVE_A = base64.b64encode(bytes(range(32))).decode()
CHAVE_B = base64.b64encode(bytes(range(32, 64))).decode()

type FabricaConfiguracoes = Callable[..., Configuracoes]


@pytest.fixture
def isolado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Diretório sem ``.env`` e sem variáveis que o pydantic-settings leria."""
    monkeypatch.chdir(tmp_path)
    for nome in [*Configuracoes.model_fields, VARIAVEL_ARQUIVO]:
        monkeypatch.delenv(nome.upper(), raising=False)
    return tmp_path


@pytest.fixture
def configuracoes(isolado: Path, monkeypatch: pytest.MonkeyPatch) -> FabricaConfiguracoes:
    """Carrega o YAML informado (padrão: o do projeto) com o mínimo obrigatório."""

    def fabricar(yaml: Path | str | None = YAML_DO_PROJETO, **valores: Any) -> Configuracoes:
        if isinstance(yaml, str):
            arquivo = isolado / "odonto.yaml"
            arquivo.write_text(yaml, encoding="utf-8")
            yaml = arquivo
        if yaml is not None:
            monkeypatch.setenv(VARIAVEL_ARQUIVO, str(yaml))
        obrigatorios: dict[str, Any] = {
            "database_url": "postgresql://odonto:senha@banco:5432/odonto",
            "chave_criptografia": CHAVE_A,
            "chave_hmac_documento": CHAVE_B,
        }
        return carregar_configuracoes(**(obrigatorios | valores))

    return fabricar
