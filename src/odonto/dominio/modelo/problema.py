"""Item do catálogo de problemas odontológicos (referência CID-10)."""

import re
from dataclasses import dataclass
from typing import Final

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import Prioridade

CODIGO_AVALIACAO_GERAL: Final = "AVALIACAO_GERAL_OUTRO"
_REGEX_CODIGO: Final = re.compile(r"[A-Z][A-Z0-9_]{1,59}")
_REGEX_CID10: Final = re.compile(r"[A-Z]\d{2}(?:\.\d{1,2})?")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProblemaOdontologico:
    """Problema, condição ou motivo de consulta conhecido (o "código" é o identificador)."""

    codigo: str
    nome: str
    descricao: str
    especialidade: str
    prioridade: Prioridade
    cid10: str
    palavras_chave: tuple[str, ...] = ()
    ativo: bool = True

    def __post_init__(self) -> None:
        if not _REGEX_CODIGO.fullmatch(self.codigo):
            raise DadoInvalidoError("codigo", f"Código de problema inválido: {self.codigo!r}.")
        if not _REGEX_CID10.fullmatch(self.cid10):
            raise DadoInvalidoError("cid10", f"Código CID-10 inválido: {self.cid10!r}.")
        if not self.nome.strip():
            raise DadoInvalidoError("nome", "O problema precisa de um nome.")

    @property
    def e_avaliacao_geral(self) -> bool:
        return self.codigo == CODIGO_AVALIACAO_GERAL
