"""Detector de sinais de alarme: palavras que tornam a queixa uma EMERGÊNCIA."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from odonto.dominio.servico.texto import contem_termo, normalizar

# Lista padrão (configurável em ``classificacao.palavras_alarme``), já sem acentos.
PALAVRAS_ALARME_PADRAO: Final = (
    "falta de ar",
    "dificuldade para respirar",
    "dificuldade de respirar",
    "dificuldade pra respirar",
    "nao consigo respirar",
    "sem conseguir respirar",
    "dificuldade para engolir",
    "dificuldade de engolir",
    "dificuldade pra engolir",
    "nao consigo engolir",
    "sem conseguir engolir",
    "rosto inchado",
    "rosto inchando",
    "rosto esta inchado",
    "cara inchada",
    "cara esta inchada",
    "face inchada",
    "inchaco no rosto",
    "inchaco na cara",
    "inchaco na face",
    "inchou o rosto",
    "inchou a cara",
    "pescoco inchado",
    "inchaco no pescoco",
    "olho inchado",
    "olho fechando",
    "febre alta",
    "sangramento que nao para",
    "sangramento nao para",
    "sangue nao para",
    "nao para de sangrar",
    "sangrando sem parar",
    "sangra sem parar",
    "hemorragia",
    "dente caiu",
    "dente da frente caiu",
    "caiu o dente",
    "caiu meu dente",
    "dente arrancado",
    "arrancou o dente",
    "arrancou meu dente",
    "bati o dente",
    "bateu o dente",
    "bati a boca",
    "bateu a boca",
    "acidente",
    "trauma",
    "traumatismo",
    "pancada",
)
INTERVALO_PADRAO: Final = 1

# Frases comuns que contêm um termo de alarme sem indicar emergência: "a restauração do dente
# caiu" (não é o dente que caiu) e "tenho trauma de dentista" (medo). São apagadas antes da busca.
_EXPRESSOES_BENIGNAS: Final = re.compile(
    r"(?<![a-z0-9])(?:"
    r"(?:restauracao|restauracoes|obturacao|obturacoes|coroa|protese|pedaco|pedacinho|lasca"
    r"|resina|massinha|faceta|lente|pino|provisorio|ponte|bloco|parte|canto|ponta)"
    r"\s+(?:d[aeo]s?\s+)?(?:(?:meu|minha|um|uma|seu|sua)\s+)?dentes?"
    r"|traumas?\s+(?:de|com|do|da)\s+(?:dentista|agulha|anestesia|tratamento|consulta|infancia)"
    r")(?![a-z0-9])"
)


@dataclass(frozen=True, slots=True)
class ResultadoAlarme:
    """Termos de alarme encontrados (vazio quando não há sinal de alarme)."""

    termos: tuple[str, ...] = ()

    @property
    def acionado(self) -> bool:
        return bool(self.termos)


class DetectorSinaisAlarme:
    """Procura sinais de alarme no texto, sem acentos e sem diferenciar maiúsculas.

    Tolera até ``intervalo`` palavras extras dentro de um termo ("rosto todo inchado") e ignora
    termos negados ("sem febre alta"). Se acionado, a prioridade da queixa vira EMERGENCIA,
    seja qual for a classificação da IA.
    """

    __slots__ = ("_intervalo", "_termos")

    def __init__(
        self, palavras: Iterable[str] = PALAVRAS_ALARME_PADRAO, *, intervalo: int = INTERVALO_PADRAO
    ) -> None:
        self._termos = tuple(dict.fromkeys(normalizar(p) for p in palavras if p.strip()))
        self._intervalo = intervalo

    def analisar(self, texto: str) -> ResultadoAlarme:
        normalizado = _EXPRESSOES_BENIGNAS.sub(" ", normalizar(texto))
        return ResultadoAlarme(
            tuple(t for t in self._termos if contem_termo(normalizado, t, self._intervalo))
        )
