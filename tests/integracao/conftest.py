import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from odonto.adaptador.saida.persistencia.banco import criar_engine, criar_fabrica_sessoes
from odonto.adaptador.saida.persistencia.catalogo_yaml import ler_catalogo
from odonto.adaptador.saida.persistencia.criptografia import (
    HmacCifradorDocumento,
    ServicoCriptografia,
)
from odonto.adaptador.saida.persistencia.orm import Base, ProblemaOdontologicoOrm
from odonto.adaptador.saida.persistencia.unidade_de_trabalho import SqlAlchemyUnidadeDeTrabalho
from odonto.dominio.modelo.eventos import EventoDominio

URL = os.environ.get("ODONTO_TESTE_DATABASE_URL")

pytestmark = pytest.mark.integracao


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if URL:
        return
    pular = pytest.mark.skip(reason="defina ODONTO_TESTE_DATABASE_URL para testar no PostgreSQL")
    for item in items:
        if "integracao" in item.keywords:
            item.add_marker(pular)


@dataclass
class PublicadorRegistrador:
    eventos: list[EventoDominio] = field(default_factory=list)

    async def publicar(self, eventos: Sequence[EventoDominio]) -> None:
        self.eventos.extend(eventos)


@dataclass
class Banco:
    engine: AsyncEngine
    uow: SqlAlchemyUnidadeDeTrabalho
    publicador: PublicadorRegistrador
    cifrador: HmacCifradorDocumento


@pytest.fixture
async def banco() -> AsyncIterator[Banco]:
    assert URL is not None
    engine = criar_engine(URL, ServicoCriptografia(os.urandom(32)))
    async with engine.begin() as conexao:
        await conexao.run_sync(Base.metadata.drop_all)
        await conexao.run_sync(Base.metadata.create_all)
    publicador = PublicadorRegistrador()
    uow = SqlAlchemyUnidadeDeTrabalho(criar_fabrica_sessoes(engine), publicador)
    async with uow:
        for posicao, p in enumerate(ler_catalogo(), start=1):
            uow.sessao_atual().add(
                ProblemaOdontologicoOrm(
                    codigo=p.codigo,
                    nome=p.nome,
                    descricao=p.descricao,
                    especialidade=p.especialidade,
                    prioridade=p.prioridade.value,
                    cid10=p.cid10,
                    palavras_chave=list(p.palavras_chave),
                    ativo=True,
                    ordem=posicao,
                )
            )
        await uow.commit()
    yield Banco(engine, uow, publicador, HmacCifradorDocumento(os.urandom(32)))
    await engine.dispose()
