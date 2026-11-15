"""Normalização de texto em português para comparações tolerantes a acentos, caixa e espaços."""

import re
import unicodedata
from functools import lru_cache
from types import MappingProxyType
from typing import Final

MESES: Final = MappingProxyType(
    {
        "janeiro": 1,
        "jan": 1,
        "fevereiro": 2,
        "fev": 2,
        "marco": 3,
        "mar": 3,
        "abril": 4,
        "abr": 4,
        "maio": 5,
        "mai": 5,
        "junho": 6,
        "jun": 6,
        "julho": 7,
        "jul": 7,
        "agosto": 8,
        "ago": 8,
        "setembro": 9,
        "set": 9,
        "outubro": 10,
        "out": 10,
        "novembro": 11,
        "nov": 11,
        "dezembro": 12,
        "dez": 12,
    }
)

_REGEX_PALAVRA_TERMO: Final = re.compile(r"[a-z0-9]+")
_NEGACOES: Final = ("nao", "sem", "nem", "nunca", "jamais")
_JANELA_NEGACAO: Final = 2
_REGEX_FIM_DE_ORACAO: Final = re.compile(r"[.,;:!?\n]")


def remover_acentos(texto: str) -> str:
    """Remove acentos e cedilha, preservando maiúsculas e minúsculas ("Ação" → "Acao")."""
    decomposto = unicodedata.normalize("NFKD", unicodedata.normalize("NFC", texto))
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere))


def normalizar(texto: str) -> str:
    """Texto sem acentos, em minúsculas e com espaços simples (a pontuação é mantida)."""
    return " ".join(remover_acentos(texto).casefold().split())


@lru_cache(maxsize=4096)
def padrao_termo(termo: str, intervalo: int = 0) -> re.Pattern[str]:
    """Expressão que encontra ``termo`` num texto normalizado, palavra por palavra.

    Cada palavra aceita plural simples (s/es) e, entre elas, até ``intervalo`` palavras extras
    (com intervalo 1, "rosto inchado" também encontra "rosto todo inchado"). A palavra extra
    não pode ser uma negação: "rosto não inchado" não corresponde a "rosto inchado".
    """
    pedacos = [rf"{re.escape(p)}(?:e?s)?" for p in _REGEX_PALAVRA_TERMO.findall(normalizar(termo))]
    if not pedacos:
        raise ValueError(f"Termo sem palavras: {termo!r}.")
    palavra_extra = rf"(?!(?:{'|'.join(_NEGACOES)})\W)\w+\W+"
    separador = r"\W+" if intervalo == 0 else rf"\W+(?:{palavra_extra}){{0,{intervalo}}}"
    return re.compile(rf"(?<![a-z0-9]){separador.join(pedacos)}(?![a-z0-9])")


def negado(texto_normalizado: str, posicao: int) -> bool:
    """Há negação ("não", "sem", "nem"...) nas duas palavras antes de ``posicao``?

    A busca não atravessa pontuação: em "não aguento, rosto inchado" o termo não está negado.
    """
    oracao = _REGEX_FIM_DE_ORACAO.split(texto_normalizado[:posicao])[-1]
    anteriores = _REGEX_PALAVRA_TERMO.findall(oracao)[-_JANELA_NEGACAO:]
    return any(palavra in _NEGACOES for palavra in anteriores)


def contem_termo(texto_normalizado: str, termo: str, intervalo: int = 0) -> bool:
    """Indica se o termo aparece no texto (já normalizado) sem estar negado."""
    return any(
        not negado(texto_normalizado, achado.start())
        for achado in padrao_termo(termo, intervalo).finditer(texto_normalizado)
    )
