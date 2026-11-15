"""Interpretação determinística de data e hora em português ("amanhã às 14h", "25/11 10:30").

É a primeira tentativa, sem IA. Só aceita frases em que todas as palavras são data, hora,
período ou palavras de ligação; qualquer outra palavra devolve ``None`` e a decisão passa para
a IA. O resultado é só a *preferência* do paciente: a disponibilidade é decidida pela ``Agenda``.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Final

from odonto.dominio.modelo.enums import PeriodoDia
from odonto.dominio.modelo.tempo import exigir_fuso
from odonto.dominio.modelo.valores import PreferenciaHorario
from odonto.dominio.servico.texto import MESES, normalizar

# Data sem ano que já passou há até 30 dias é tratada como engano (a agenda sugere o próximo
# horário livre); mais antiga que isso, é do ano que vem ("10/01" pedido em novembro).
TOLERANCIA_DATA_PASSADA: Final = timedelta(days=30)
_ULTIMA_HORA_SEM_PERIODO_A_TARDE: Final = 6
_MEIO_DIA: Final = 12

_DIAS_SEMANA: Final = MappingProxyType(
    {
        "segunda": 0,
        "seg": 0,
        "terca": 1,
        "quarta": 2,
        "qua": 2,
        "quinta": 3,
        "qui": 3,
        "sexta": 4,
        "sex": 4,
        "sabado": 5,
        "sab": 5,
        "domingo": 6,
        "dom": 6,
    }
)
_PERIODOS: Final = MappingProxyType(
    {
        "manha": PeriodoDia.MANHA,
        "manhazinha": PeriodoDia.MANHA,
        "cedo": PeriodoDia.MANHA,
        "cedinho": PeriodoDia.MANHA,
        "tarde": PeriodoDia.TARDE,
        "tardezinha": PeriodoDia.TARDE,
        "noite": PeriodoDia.NOITE,
        "noitinha": PeriodoDia.NOITE,
    }
)
_PALAVRAS_DE_LIGACAO: Final = frozenset(
    {
        "a",
        "as",
        "o",
        "os",
        "de",
        "do",
        "da",
        "das",
        "dos",
        "dia",
        "no",
        "na",
        "nos",
        "nas",
        "em",
        "para",
        "pra",
        "pro",
        "por",
        "volta",
        "umas",
        "uns",
        "la",
        "pelas",
        "pelo",
        "pela",
        "pode",
        "poderia",
        "ser",
        "seria",
        "sera",
        "quero",
        "queria",
        "gostaria",
        "prefiro",
        "preferencia",
        "preferencialmente",
        "melhor",
        "se",
        "possivel",
        "der",
        "agendar",
        "marcar",
        "agenda",
        "consulta",
        "horario",
        "hora",
        "horas",
        "h",
        "e",
        "proxima",
        "proximo",
        "que",
        "vem",
        "essa",
        "esse",
        "esta",
        "este",
        "nessa",
        "nesse",
        "nesta",
        "neste",
        "sim",
        "ok",
        "tipo",
        "mais",
        "ou",
        "menos",
        "partir",
        "depois",
        "apos",
        "inicio",
        "comeco",
        "fim",
        "final",
        "parte",
        "periodo",
        "durante",
        "feira",
        "eu",
        "posso",
        "consigo",
        "vou",
        "tenho",
        "disponibilidade",
        "disponivel",
        "livre",
        "favor",
        "obrigado",
        "obrigada",
        "entao",
        "certo",
        "beleza",
        "isso",
        "ai",
    }
)

_MESES_REGEX: Final = "|".join(sorted(MESES, key=len, reverse=True))
_SEMANA_REGEX: Final = "|".join(sorted(_DIAS_SEMANA, key=len, reverse=True))
_PERIODOS_REGEX: Final = "|".join(sorted(_PERIODOS, key=len, reverse=True))
_SUFIXO_HORA: Final = r"(?:h|hs|hr|hrs|hora|horas)"

_SAUDACAO: Final = re.compile(r"(?<![a-z])(?:bom\s+dia|boa\s+tarde|boa\s+noite|ola|oi)(?![a-z])")
_QUANTO_ANTES: Final = re.compile(
    r"(?<![a-z])(?:o\s+quanto\s+antes|o\s+mais\s+(?:rapido|cedo)\s+possivel"
    r"|mais\s+cedo\s+possivel|assim\s+que\s+(?:possivel|der)|qualquer\s+(?:dia|horario|hora|data)"
    r"|primeiro\s+horario(?:\s+(?:livre|disponivel))?)(?![a-z])"
)
_DATA_COM_BARRA: Final = re.compile(
    r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{4}|\d{2}))?(?![\d/])"
)
_DATA_COM_TRACO: Final = re.compile(
    r"(?<![\d.\-])(\d{1,2})[\-.](\d{1,2})[\-.](\d{4}|\d{2})(?![\d])"
)
_DATA_POR_EXTENSO: Final = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s*o?\s*(?:de\s+)?({_MESES_REGEX})(?![a-z])\.?(?:\s+(?:de\s+)?(\d{{4}}))?"
)
_DIA_DO_MES: Final = re.compile(r"(?<![a-z])dia\s+(\d{1,2})(?![\d:h])")
_DEPOIS_DE_AMANHA: Final = re.compile(r"(?<![a-z])depois\s+de\s+amanha(?![a-z])")
_AMANHA: Final = re.compile(r"(?<![a-z])amanha(?![a-z])")
_HOJE: Final = re.compile(r"(?<![a-z])(?:hoje|hj)(?![a-z])")
_DIA_DA_SEMANA: Final = re.compile(
    rf"(?<![a-z])({_SEMANA_REGEX})(?:\s*-?\s*feira)?(?:\s+que\s+vem)?(?![a-z])"
)
_MEIO_DIA_REGEX: Final = re.compile(r"(?<![a-z])meio\s*-?\s*dia(\s+e\s+meia)?(?![a-z])")
_HORA_COM_SUFIXO: Final = re.compile(
    rf"(?<![\d/:])(\d{{1,2}})\s*{_SUFIXO_HORA}"
    r"(?:\s*e\s+(meia)|\s*(?:e\s+)?(\d{2})\s*(?:min|minutos)?)?(?![a-z0-9])"
)
_HORA_COM_DOIS_PONTOS: Final = re.compile(
    rf"(?<![\d/:])(\d{{1,2}}):(\d{{2}})(?:\s*{_SUFIXO_HORA})?(?![\d:])"
)
_HORA_COM_PREPOSICAO: Final = re.compile(
    r"(?<![a-z])(?:as|a|umas|pelas)\s+(\d{1,2})(?:\s+e\s+(meia))?(?![\d/:a-z])"
)
_HORA_E_MEIA: Final = re.compile(r"(?<![\d/:])(\d{1,2})\s+e\s+(meia)(?![a-z])")
_HORA_ANTES_DO_PERIODO: Final = re.compile(
    rf"(?<![\d/:])(\d{{1,2}})(?=\s+(?:da|de|a)\s+(?:{_PERIODOS_REGEX})(?![a-z]))"
)
_PERIODO: Final = re.compile(rf"(?<![a-z])({_PERIODOS_REGEX})(?![a-z])")
_PALAVRA: Final = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class _Achados:
    """Tudo o que foi reconhecido no texto (valores repetidos e diferentes = ambiguidade)."""

    hoje: date
    datas: set[date] = field(default_factory=set)
    dias_semana: set[int] = field(default_factory=set)
    horas: set[time] = field(default_factory=set)
    periodos: set[PeriodoDia] = field(default_factory=set)
    o_quanto_antes: bool = False
    invalido: bool = False

    def marcar_o_quanto_antes(self) -> None:
        self.o_quanto_antes = True

    def data(self, valor: date | None) -> None:
        if valor is None:
            self.invalido = True
        else:
            self.datas.add(valor)

    def hora(self, hora: int, minuto: int = 0) -> None:
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            self.horas.add(time(hora, minuto))
        else:
            self.invalido = True


def _criar_data(ano: int, mes: int, dia: int) -> date | None:
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _ano_com_quatro_digitos(ano: str) -> int:
    return int(ano) if len(ano) == 4 else 2000 + int(ano)


def _data_sem_ano(dia: int, mes: int, hoje: date) -> date | None:
    for ano in (hoje.year, hoje.year + 1):
        candidata = _criar_data(ano, mes, dia)
        if candidata is not None and hoje - candidata <= TOLERANCIA_DATA_PASSADA:
            return candidata
    return None


def _data(dia: str, mes: int, ano: str | None, hoje: date) -> date | None:
    if ano is None:
        return _data_sem_ano(int(dia), mes, hoje)
    return _criar_data(_ano_com_quatro_digitos(ano), mes, int(dia))


def _dia_do_mes(dia: int, hoje: date) -> date | None:
    """ "dia 25": neste mês se ainda não passou; senão, no mês que vem."""
    if dia >= hoje.day:
        return _criar_data(hoje.year, hoje.month, dia)
    ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
    return _criar_data(ano, mes, dia)


def _minuto(meia: str | None, minutos: str | None) -> int:
    if meia:
        return 30
    return int(minutos) if minutos else 0


def _consumir(texto: str, padrao: re.Pattern[str], tratar: Callable[[re.Match[str]], None]) -> str:
    """Trata cada ocorrência do padrão e a apaga do texto (o que sobrar é verificado no fim)."""

    def substituir(achado: re.Match[str]) -> str:
        tratar(achado)
        return " "

    return padrao.sub(substituir, texto)


class InterpretadorDataHoraDeterministico:
    """Reconhece datas (25/11, 25 de novembro, dia 25, hoje, amanhã, sexta), horas (10h, 10:30,
    às 10 e meia, meio-dia) e períodos (manhã, tarde, noite)."""

    __slots__ = ()

    def interpretar(self, texto: str, agora: datetime) -> PreferenciaHorario | None:
        """Devolve a preferência ou ``None`` se o texto não for só data e hora, ou for ambíguo."""
        hoje = exigir_fuso(agora, "agora").date()
        achados = _Achados(hoje)
        restante = self._consumir_tudo(normalizar(texto), achados)
        sobras = [p for p in _PALAVRA.findall(restante) if p not in _PALAVRAS_DE_LIGACAO]
        if sobras or achados.invalido:
            return None
        return self._montar(achados)

    @staticmethod
    def _consumir_tudo(texto: str, a: _Achados) -> str:
        hoje = a.hoje
        etapas: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], None]], ...] = (
            (_SAUDACAO, lambda m: None),
            (_QUANTO_ANTES, lambda m: a.marcar_o_quanto_antes()),
            (_DATA_COM_BARRA, lambda m: a.data(_data(m[1], int(m[2]), m[3], hoje))),
            (_DATA_COM_TRACO, lambda m: a.data(_data(m[1], int(m[2]), m[3], hoje))),
            (_DATA_POR_EXTENSO, lambda m: a.data(_data(m[1], MESES[m[2]], m[3], hoje))),
            (_DIA_DO_MES, lambda m: a.data(_dia_do_mes(int(m[1]), hoje))),
            (_DEPOIS_DE_AMANHA, lambda m: a.data(hoje + timedelta(days=2))),
            (_AMANHA, lambda m: a.data(hoje + timedelta(days=1))),
            (_HOJE, lambda m: a.data(hoje)),
            (_DIA_DA_SEMANA, lambda m: a.dias_semana.add(_DIAS_SEMANA[m[1]])),
            (_MEIO_DIA_REGEX, lambda m: a.hora(_MEIO_DIA, 30 if m[1] else 0)),
            (_HORA_COM_DOIS_PONTOS, lambda m: a.hora(int(m[1]), int(m[2]))),
            (_HORA_COM_SUFIXO, lambda m: a.hora(int(m[1]), _minuto(m[2], m[3]))),
            (_HORA_COM_PREPOSICAO, lambda m: a.hora(int(m[1]), _minuto(m[2], None))),
            (_HORA_E_MEIA, lambda m: a.hora(int(m[1]), 30)),
            (_HORA_ANTES_DO_PERIODO, lambda m: a.hora(int(m[1]))),
            (_PERIODO, lambda m: a.periodos.add(_PERIODOS[m[1]])),
        )
        for padrao, tratar in etapas:
            texto = _consumir(texto, padrao, tratar)
        return texto

    @staticmethod
    def _montar(a: _Achados) -> PreferenciaHorario | None:
        if len(a.datas) > 1 or len(a.dias_semana) > 1 or len(a.horas) > 1 or len(a.periodos) > 1:
            return None
        data = next(iter(a.datas), None)
        periodo = next(iter(a.periodos), None)
        if a.dias_semana:
            dia_semana = next(iter(a.dias_semana))
            if data is None:
                data = a.hoje + timedelta(days=(dia_semana - a.hoje.weekday() - 1) % 7 + 1)
            elif data.weekday() != dia_semana:
                return None
        if data is None and a.o_quanto_antes:
            data = a.hoje
        hora = next(iter(a.horas), None)
        if hora is not None:
            hora = InterpretadorDataHoraDeterministico._ajustar_hora(hora, periodo)
            if hora is None:
                return None
        if data is None and hora is None and periodo is None:
            return None
        return PreferenciaHorario(data=data, hora=hora, periodo=periodo)

    @staticmethod
    def _ajustar_hora(hora: time, periodo: PeriodoDia | None) -> time | None:
        """ "3 da tarde" vira 15h; "3h" sem período também (ninguém marca às 3 da madrugada)."""
        match periodo:
            case PeriodoDia.TARDE | PeriodoDia.NOITE if hora.hour < _MEIO_DIA:
                return hora.replace(hour=hora.hour + _MEIO_DIA)
            case PeriodoDia.MANHA if hora.hour >= _MEIO_DIA:
                return None
            case None if 1 <= hora.hour <= _ULTIMA_HORA_SEM_PERIODO_A_TARDE:
                return hora.replace(hour=hora.hour + _MEIO_DIA)
            case _:
                return hora
