"""Interpretação determinística de datas e horários em linguagem natural.

Referência: quarta-feira, 18/11/2026, 09:00.
"""

from datetime import date, time

import pytest

from odonto.dominio.modelo.enums import PeriodoDia
from odonto.dominio.modelo.valores import PreferenciaHorario
from odonto.dominio.servico.interpretador_data_hora import InterpretadorDataHoraDeterministico
from tests.apoio import AGORA

QUINTA = date(2026, 11, 19)
SEXTA = date(2026, 11, 20)
SEGUNDA = date(2026, 11, 23)


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("amanhã", PreferenciaHorario(data=QUINTA)),
        ("amanha as 10h", PreferenciaHorario(data=QUINTA, hora=time(10, 0))),
        ("amanhã à tarde", PreferenciaHorario(data=QUINTA, periodo=PeriodoDia.TARDE)),
        ("depois de amanhã de manhã", PreferenciaHorario(data=SEXTA, periodo=PeriodoDia.MANHA)),
        ("sexta às 10h", PreferenciaHorario(data=SEXTA, hora=time(10, 0))),
        ("sexta de manhã", PreferenciaHorario(data=SEXTA, periodo=PeriodoDia.MANHA)),
        ("Sexta-feira, 20/11, 14:30", PreferenciaHorario(data=SEXTA, hora=time(14, 30))),
        ("segunda que vem às 9 e meia", PreferenciaHorario(data=SEGUNDA, hora=time(9, 30))),
        ("próxima segunda 15h", PreferenciaHorario(data=SEGUNDA, hora=time(15, 0))),
        ("às 3 da tarde", PreferenciaHorario(hora=time(15, 0), periodo=PeriodoDia.TARDE)),
        ("às 3", PreferenciaHorario(hora=time(15, 0))),
        ("meio-dia e meia", PreferenciaHorario(hora=time(12, 30))),
        ("dia 25", PreferenciaHorario(data=date(2026, 11, 25))),
        ("25 de dezembro", PreferenciaHorario(data=date(2026, 12, 25))),
        ("10/01", PreferenciaHorario(data=date(2027, 1, 10))),
        ("10/01/2027 8h", PreferenciaHorario(data=date(2027, 1, 10), hora=time(8, 0))),
        ("hoje à tarde", PreferenciaHorario(data=AGORA.date(), periodo=PeriodoDia.TARDE)),
        ("de tarde", PreferenciaHorario(periodo=PeriodoDia.TARDE)),
        ("bom dia! pode ser amanhã às 8h?", PreferenciaHorario(data=QUINTA, hora=time(8, 0))),
    ],
)
def test_interpreta_expressoes_comuns(texto: str, esperada: PreferenciaHorario) -> None:
    assert InterpretadorDataHoraDeterministico().interpretar(texto, AGORA) == esperada


@pytest.mark.parametrize(
    "texto",
    [
        "15h de manhã",
        "sexta 25/11",
        "amanha as 10h ou 11h",
        "não posso amanhã",
        "semana que vem",
        "quando tiver vaga",
        "31/02",
        "25h",
        "",
    ],
)
def test_ambiguo_ou_invalido_fica_para_a_ia(texto: str) -> None:
    assert InterpretadorDataHoraDeterministico().interpretar(texto, AGORA) is None


def test_data_recente_sem_ano_fica_no_passado() -> None:
    # 05/11 ficou para trás há menos de 30 dias: é a data que o paciente escreveu (a agenda
    # depois responde que já passou), não 05/11 do ano que vem.
    resultado = InterpretadorDataHoraDeterministico().interpretar("05/11", AGORA)
    assert resultado == PreferenciaHorario(data=date(2026, 11, 5))
