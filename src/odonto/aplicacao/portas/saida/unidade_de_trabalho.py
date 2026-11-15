"""Unidade de Trabalho (Unit of Work): transação, repositórios e publicação de eventos."""

from types import TracebackType
from typing import Protocol, Self

from odonto.aplicacao.portas.saida.repositorios import (
    BloqueioAgendaRepositorio,
    CatalogoProblemasRepositorio,
    ConsultaRepositorio,
    ConversaRepositorio,
    MensagemRepositorio,
    PacienteRepositorio,
    ProntuarioRepositorio,
)


class UnidadeDeTrabalho(Protocol):
    """Uma transação do banco com acesso aos repositórios.

    Uso: ``async with uow: ...; await uow.commit()``. Sem ``commit``, tudo é desfeito na saída
    do bloco (também quando há exceção).

    - Reentrante: um ``async with`` aninhado, no mesmo fluxo assíncrono, participa da transação
      externa, e o ``commit`` aninhado não efetiva nada; só o do bloco mais externo. Assim um
      caso de uso pode chamar outro e tudo fica numa transação só.
    - Eventos: os agregados passados a ``adicionar``/``salvar`` têm os eventos de domínio
      coletados no commit e publicados (``PublicadorEventos``) só depois do commit bem-sucedido.
    - Os repositórios só podem ser usados dentro do bloco ``async with``.
    """

    @property
    def pacientes(self) -> PacienteRepositorio: ...

    @property
    def prontuarios(self) -> ProntuarioRepositorio: ...

    @property
    def catalogo(self) -> CatalogoProblemasRepositorio: ...

    @property
    def consultas(self) -> ConsultaRepositorio: ...

    @property
    def bloqueios(self) -> BloqueioAgendaRepositorio: ...

    @property
    def conversas(self) -> ConversaRepositorio: ...

    @property
    def mensagens(self) -> MensagemRepositorio: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastreio: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
