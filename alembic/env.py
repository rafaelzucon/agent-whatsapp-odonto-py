"""Ambiente do Alembic em modo assíncrono (psycopg 3).

A URL vem de ``DATABASE_URL`` (ou de ``sqlalchemy.url`` passada por quem chama, como os
testes). ``Base.metadata`` é a referência para o ``alembic check`` e o autogenerate.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from odonto.adaptador.saida.persistencia.orm import Base
from odonto.infraestrutura.config import normalizar_url_banco

config = context.config
if config.config_file_name is not None and config.attributes.get("configurar_logs", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Defina DATABASE_URL para rodar as migrações.")
    return normalizar_url_banco(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _executar(conexao: Connection) -> None:
    context.configure(connection=conexao, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _executar_async() -> None:
    engine = async_engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as conexao:
        await conexao.run_sync(_executar)
    await engine.dispose()


def run_migrations_online() -> None:
    conexao: Connection | None = config.attributes.get("connection")
    if conexao is not None:
        _executar(conexao)
    else:
        asyncio.run(_executar_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
