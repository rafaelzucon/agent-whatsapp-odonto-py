"""Porta de proteção do RG: hash determinístico para busca."""

from typing import Protocol

from odonto.dominio.modelo.valores import DocumentoRg


class CifradorDocumento(Protocol):
    def hash_busca(self, documento: DocumentoRg) -> str:
        """HMAC-SHA256 (chave própria) do RG normalizado + UF, em hexadecimal.

        Pós-condições: o mesmo RG + UF gera sempre o mesmo hash; UF diferente gera hash
        diferente; o hash não permite recuperar o RG.
        """
        ...
