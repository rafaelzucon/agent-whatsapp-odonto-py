"""Unidade de Trabalho com SQLAlchemy assíncrono.

Uma instância (criada no container) atende toda a aplicação. A transação corrente fica numa
``ContextVar``: cada tarefa asyncio (requisição HTTP, mensagem da fila, job) tem a sua, e um
``async with`` aninhado na mesma tarefa participa da transação externa (reentrância).
"""

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from odonto.adaptador.saida.persistencia.repositorios import (
    SqlAlchemyBloqueioRepositorio,
    SqlAlchemyCatalogoRepositorio,
    SqlAlchemyConsultaRepositorio,
    SqlAlchemyConversaRepositorio,
    SqlAlchemyMensagemRepositorio,
    SqlAlchemyPacienteRepositorio,
    SqlAlchemyProntuarioRepositorio,
)
from odonto.aplicacao.portas.saida.fila import PublicadorEventos
from odonto.dominio.modelo.agregado import AgregadoRaiz
from odonto.dominio.modelo.eventos import EventoDominio

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Transacao:
    sessao: AsyncSession
    token: Token[_Transacao | None]
    profundidade: int = 1
    rastreados: list[AgregadoRaiz] = field(default_factory=list)


class SqlAlchemyUnidadeDeTrabalho:
    """Implementa ``UnidadeDeTrabalho`` (ver o contrato na porta)."""

    def __init__(
        self,
        fabrica_sessoes: async_sessionmaker[AsyncSession],
        publicador: PublicadorEventos,
    ) -> None:
        self._fabrica = fabrica_sessoes
        self._publicador = publicador
        self._atual: ContextVar[_Transacao | None] = ContextVar(
            f"odonto_uow_{id(self)}", default=None
        )
        self._pacientes = SqlAlchemyPacienteRepositorio(self)
        self._prontuarios = SqlAlchemyProntuarioRepositorio(self)
        self._catalogo = SqlAlchemyCatalogoRepositorio(self)
        self._consultas = SqlAlchemyConsultaRepositorio(self)
        self._bloqueios = SqlAlchemyBloqueioRepositorio(self)
        self._conversas = SqlAlchemyConversaRepositorio(self)
        self._mensagens = SqlAlchemyMensagemRepositorio(self)

    @property
    def pacientes(self) -> SqlAlchemyPacienteRepositorio:
        return self._pacientes

    @property
    def prontuarios(self) -> SqlAlchemyProntuarioRepositorio:
        return self._prontuarios

    @property
    def catalogo(self) -> SqlAlchemyCatalogoRepositorio:
        return self._catalogo

    @property
    def consultas(self) -> SqlAlchemyConsultaRepositorio:
        return self._consultas

    @property
    def bloqueios(self) -> SqlAlchemyBloqueioRepositorio:
        return self._bloqueios

    @property
    def conversas(self) -> SqlAlchemyConversaRepositorio:
        return self._conversas

    @property
    def mensagens(self) -> SqlAlchemyMensagemRepositorio:
        return self._mensagens

    def _transacao(self) -> _Transacao:
        transacao = self._atual.get()
        if transacao is None:
            raise RuntimeError("Repositório usado fora de 'async with unidade_de_trabalho'.")
        return transacao

    def sessao_atual(self) -> AsyncSession:
        return self._transacao().sessao

    def rastrear(self, agregado: AgregadoRaiz) -> None:
        """Guarda o agregado para coletar os eventos dele no commit."""
        rastreados = self._transacao().rastreados
        if all(existente is not agregado for existente in rastreados):
            rastreados.append(agregado)

    async def __aenter__(self) -> Self:
        transacao = self._atual.get()
        if transacao is not None:
            transacao.profundidade += 1
            return self
        sessao = self._fabrica()
        transacao = _Transacao(sessao=sessao, token=self._atual.set(None))
        self._atual.set(transacao)
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastreio: TracebackType | None,
    ) -> None:
        transacao = self._transacao()
        transacao.profundidade -= 1
        if transacao.profundidade > 0:
            return
        try:
            await transacao.sessao.rollback()  # desfaz o que não foi efetivado com commit
        finally:
            await transacao.sessao.close()
            self._atual.reset(transacao.token)

    async def commit(self) -> None:
        transacao = self._transacao()
        if transacao.profundidade != 1:
            return  # o bloco externo decide
        await transacao.sessao.commit()
        eventos: list[EventoDominio] = [
            evento for agregado in transacao.rastreados for evento in agregado.coletar_eventos()
        ]
        transacao.rastreados.clear()
        if eventos:
            try:
                await self._publicador.publicar(eventos)
            except Exception:
                _log.exception("falha ao publicar eventos de domínio", extra={"qtd": len(eventos)})

    async def rollback(self) -> None:
        transacao = self._transacao()
        if transacao.profundidade == 1:
            await transacao.sessao.rollback()
            transacao.rastreados.clear()
