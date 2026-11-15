"""As migrações do Alembic criam exatamente o schema dos modelos ORM e carregam o catálogo."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text

from odonto.adaptador.saida.persistencia.catalogo_yaml import ler_catalogo
from odonto.adaptador.saida.persistencia.orm import Base
from tests.integracao.conftest import URL

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def engine_limpo() -> Iterator[Engine]:
    assert URL is not None
    engine = create_engine(URL)
    with engine.begin() as conexao:
        conexao.execute(text("DROP SCHEMA public CASCADE"))
        conexao.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def _config() -> Config:
    assert URL is not None
    config = Config(RAIZ / "alembic.ini")
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    config.set_main_option("sqlalchemy.url", URL)
    config.attributes["configurar_logs"] = False
    return config


def test_upgrade_reproduz_o_metadata_e_carrega_o_catalogo(engine_limpo: Engine) -> None:
    command.upgrade(_config(), "head")

    with engine_limpo.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
        total = conexao.scalar(text("SELECT count(*) FROM problema_odontologico"))
        primeiro = conexao.scalar(text("SELECT codigo FROM problema_odontologico WHERE ordem = 1"))
        numero = conexao.scalar(text("SELECT nextval('prontuario_numero_seq')"))

    assert diferencas == []
    assert total == len(ler_catalogo())
    assert primeiro == ler_catalogo()[0].codigo
    assert numero == 1


def test_downgrade_remove_tudo(engine_limpo: Engine) -> None:
    config = _config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with engine_limpo.connect() as conexao:
        tabelas = conexao.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).all()
    assert tabelas == ["alembic_version"]
