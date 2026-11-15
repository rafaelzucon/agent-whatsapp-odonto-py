"""Tipo de coluna ``TextoCifrado``: cifra ao gravar e decifra ao ler, de forma transparente."""

from typing import Any, Protocol, override

from sqlalchemy import Dialect, Text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.types import TypeDecorator

_ATRIBUTO = "odonto_cifrador"


class Cifrador(Protocol):
    def cifrar(self, texto: str) -> str: ...

    def decifrar(self, valor: str) -> str: ...


def vincular_cifrador(engine: AsyncEngine, cifrador: Cifrador) -> None:
    """Associa o serviço de criptografia ao dialeto do engine.

    A chave fica presa ao engine criado pelo container (sem estado global): cada engine pode
    ter a sua, e os testes usam um dialeto próprio.
    """
    setattr(engine.sync_engine.dialect, _ATRIBUTO, cifrador)


def _cifrador(dialect: Dialect) -> Cifrador:
    cifrador: Cifrador | None = getattr(dialect, _ATRIBUTO, None)
    if cifrador is None:
        raise RuntimeError("Engine sem cifrador: chame vincular_cifrador() ao criá-lo.")
    return cifrador


class TextoCifrado(TypeDecorator[str]):
    """Coluna ``text`` com o valor em AES-256-GCM (Base64 de nonce || cifrado+tag)."""

    impl = Text
    cache_ok = True

    @override
    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else _cifrador(dialect).cifrar(value)

    @override
    def process_result_value(self, value: Any | None, dialect: Dialect) -> str | None:
        return None if value is None else _cifrador(dialect).decifrar(str(value))
