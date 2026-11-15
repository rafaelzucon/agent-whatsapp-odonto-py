"""Classificação determinística da queixa pelas palavras-chave do catálogo.

É o plano B quando a IA falha, devolve um código inexistente ou tem confiança baixa.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.servico.texto import contem_termo, normalizar

CONFIANCA_BASE: Final = 0.4
CONFIANCA_POR_PALAVRA: Final = 0.1
CONFIANCA_MAXIMA: Final = 0.9


@dataclass(frozen=True, slots=True)
class ClassificacaoPorPalavraChave:
    problema: ProblemaOdontologico
    confianca: float
    termos: tuple[str, ...]


class ClassificadorPorPalavraChave:
    """Escolhe o item do catálogo com mais palavras-chave encontradas no texto.

    Pontuação: soma do número de palavras de cada termo encontrado ("dor de dente" vale 3,
    "cárie" vale 1). Empate: a prioridade mais alta e, depois, a ordem do catálogo.
    """

    __slots__ = ("_intervalo",)

    def __init__(self, *, intervalo: int = 1) -> None:
        self._intervalo = intervalo

    def classificar(
        self, texto: str, catalogo: Sequence[ProblemaOdontologico]
    ) -> ClassificacaoPorPalavraChave | None:
        normalizado = normalizar(texto)
        melhor: tuple[int, int, int] | None = None
        escolhido: ClassificacaoPorPalavraChave | None = None
        for posicao, problema in enumerate(catalogo):
            if not problema.ativo:
                continue
            termos = tuple(
                termo
                for termo in problema.palavras_chave
                if termo.strip() and contem_termo(normalizado, termo, self._intervalo)
            )
            if not termos:
                continue
            pontos = sum(len(normalizar(termo).split()) for termo in termos)
            criterio = (pontos, problema.prioridade.nivel, -posicao)
            if melhor is None or criterio > melhor:
                melhor = criterio
                confianca = min(CONFIANCA_MAXIMA, CONFIANCA_BASE + CONFIANCA_POR_PALAVRA * pontos)
                escolhido = ClassificacaoPorPalavraChave(problema, round(confianca, 2), termos)
        return escolhido
