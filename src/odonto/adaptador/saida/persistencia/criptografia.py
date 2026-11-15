"""Criptografia dos dados pessoais (AES-256-GCM) e hash de busca do RG (HMAC-SHA256)."""

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from odonto.dominio.modelo.valores import DocumentoRg

TAMANHO_CHAVE = 32
TAMANHO_NONCE = 12


class ChaveInvalidaError(ValueError):
    """Chave ausente, em Base64 inválido ou com tamanho diferente de 32 bytes."""


class DadoCorrompidoError(ValueError):
    """O texto cifrado não pôde ser decifrado (chave errada ou dado adulterado)."""


def decodificar_chave(valor: str, nome: str) -> bytes:
    """Decodifica uma chave Base64 de 32 bytes, rejeitando qualquer outro tamanho."""
    try:
        chave = base64.b64decode(valor.strip(), validate=True)
    except binascii.Error, ValueError:
        raise ChaveInvalidaError(f"{nome} não está em Base64 válido.") from None
    if len(chave) != TAMANHO_CHAVE:
        raise ChaveInvalidaError(
            f"{nome} deve ter {TAMANHO_CHAVE} bytes (tem {len(chave)}). "
            "Gere com: openssl rand -base64 32"
        )
    return chave


class ServicoCriptografia:
    """AES-256-GCM com nonce aleatório de 12 bytes. Formato: Base64(nonce || cifrado+tag)."""

    __slots__ = ("_aes",)

    def __init__(self, chave: bytes) -> None:
        if len(chave) != TAMANHO_CHAVE:
            raise ChaveInvalidaError(f"A chave de criptografia deve ter {TAMANHO_CHAVE} bytes.")
        self._aes = AESGCM(chave)

    def cifrar(self, texto: str) -> str:
        nonce = os.urandom(TAMANHO_NONCE)
        cifrado = self._aes.encrypt(nonce, texto.encode("utf-8"), None)
        return base64.b64encode(nonce + cifrado).decode("ascii")

    def decifrar(self, valor: str) -> str:
        try:
            bruto = base64.b64decode(valor, validate=True)
            nonce, cifrado = bruto[:TAMANHO_NONCE], bruto[TAMANHO_NONCE:]
            return self._aes.decrypt(nonce, cifrado, None).decode("utf-8")
        except (binascii.Error, ValueError, InvalidTag) as erro:
            raise DadoCorrompidoError("Não foi possível decifrar o dado armazenado.") from erro


class HmacCifradorDocumento:
    """Implementa ``CifradorDocumento``: HMAC-SHA256 do RG normalizado + UF, em hexadecimal.

    Determinístico (permite busca e índice único), mas sem a chave não é possível descobrir o
    RG por força bruta a partir do hash.
    """

    __slots__ = ("_chave",)

    def __init__(self, chave: bytes) -> None:
        if len(chave) != TAMANHO_CHAVE:
            raise ChaveInvalidaError(f"A chave HMAC deve ter {TAMANHO_CHAVE} bytes.")
        self._chave = chave

    def hash_busca(self, documento: DocumentoRg) -> str:
        mensagem = documento.chave_normalizada.encode("utf-8")
        return hmac.new(self._chave, mensagem, hashlib.sha256).hexdigest()
