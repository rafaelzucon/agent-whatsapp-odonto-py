"""Portas de IA: dois ``Protocol`` separados (segregação de interface).

A IA só classifica a queixa e interpreta datas. Ela recebe apenas o texto da queixa ou da data,
nunca nome, RG, telefone ou identificadores internos, e nunca decide disponibilidade.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from odonto.dominio.modelo.enums import Prioridade
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.valores import PreferenciaHorario


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificacaoIA:
    """Resposta da IA. O código pode não existir no catálogo: o caso de uso confere."""

    codigo: str
    confianca: float
    prioridade: Prioridade | None = None
    sintomas: tuple[str, ...] = ()
    sinais_alarme: bool = False


class ClassificadorProblemaIA(Protocol):
    async def classificar(
        self, queixa: str, catalogo: Sequence[ProblemaOdontologico]
    ) -> ClassificacaoIA:
        """Escolhe o item do catálogo que melhor descreve a queixa.

        Pré-condições: ``queixa`` não vazia; ``catalogo`` com ao menos um item.
        Pós-condições: nunca devolve ``None``; ``confianca`` entre 0 e 1.
        Levanta ``FalhaIntegracaoError`` em erro de rede, timeout, recusa ou resposta inválida.
        """
        ...


class InterpretadorDataHoraIA(Protocol):
    async def interpretar(self, texto: str, agora: datetime) -> PreferenciaHorario | None:
        """Extrai data, hora e/ou período do texto, com ``agora`` (com fuso) de referência.

        Pós-condições: ``None`` quando não entendeu (texto ambíguo ou sem data/hora).
        Levanta ``FalhaIntegracaoError`` em erro de rede, timeout ou resposta inválida.
        """
        ...
