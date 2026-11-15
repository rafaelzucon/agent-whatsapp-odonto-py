"""Criação do engine assíncrono (psycopg 3) com o cifrador das colunas sensíveis."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from odonto.adaptador.saida.persistencia.criptografia import ServicoCriptografia
from odonto.adaptador.saida.persistencia.tipos import vincular_cifrador


def criar_engine(url: str, criptografia: ServicoCriptografia, *, eco: bool = False) -> AsyncEngine:
    """``url`` no formato ``postgresql+psycopg://usuario:senha@host:5432/banco``."""
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, echo=eco)
    vincular_cifrador(engine, criptografia)
    return engine


def criar_fabrica_sessoes(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: os objetos continuam legíveis depois do commit (sem lazy load).
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=True)
