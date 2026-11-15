"""Validação da assinatura ``X-Hub-Signature-256`` enviada pela Meta em cada webhook."""

import hashlib
import hmac

PREFIXO = "sha256="


def calcular_assinatura(corpo: bytes, segredo: str) -> str:
    """Valor esperado do cabeçalho: ``sha256=`` + HMAC-SHA256 (hex) do corpo com o App Secret."""
    return PREFIXO + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def assinatura_valida(corpo: bytes, cabecalho: str | None, segredo: str) -> bool:
    """Compara em tempo constante. Sem segredo configurado, nenhuma assinatura é válida."""
    if not cabecalho or not segredo or not cabecalho.startswith(PREFIXO):
        return False
    return hmac.compare_digest(calcular_assinatura(corpo, segredo), cabecalho.strip())
