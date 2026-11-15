"""Agenda: disponibilidade, busca do horário livre mais próximo e horário de verão.

Referência: quarta-feira, 18/11/2026, 09:00. Expediente de segunda a sexta, das 8h às 18h,
almoço das 12h às 13h, consultas de 30 minutos e 2 horas de antecedência mínima.
"""

from datetime import date, datetime, time, timedelta

import pytest

from odonto.dominio.excecoes import (
    DadoInvalidoError,
    HorarioIndisponivelError,
    MotivoIndisponibilidade,
)
from odonto.dominio.modelo.enums import DiaSemana, MotivoSugestao, PeriodoDia
from odonto.dominio.modelo.valores import Horario, PreferenciaHorario
from odonto.dominio.servico.agenda import (
    Agenda,
    HorarioDisponivel,
    HorarioSugerido,
    SemHorarioLivre,
)
from tests.apoio import AGORA, em, funcionamento

TODOS_OS_DIAS = frozenset(DiaSemana)
QUINTA = date(2026, 11, 19)
SEXTA = date(2026, 11, 20)
MEIA_HORA = timedelta(minutes=30)


def ocupado(inicio_hora: int, minuto: int = 0, dia: date = QUINTA) -> Horario:
    return Horario.com_duracao(em(dia.year, dia.month, dia.day, inicio_hora, minuto), MEIA_HORA)


def dia_inteiro(dia: date) -> Horario:
    return Horario(em(dia.year, dia.month, dia.day), em(dia.year, dia.month, dia.day, 23, 59))


class TestHorarioFuncionamento:
    def test_grade_respeita_turnos(self) -> None:
        grade = funcionamento().grade()
        assert len(grade) == 18
        assert grade[0] == time(8, 0)
        assert time(11, 30) in grade
        assert time(12, 0) not in grade
        assert time(12, 30) not in grade
        assert grade[-1] == time(17, 30)

    @pytest.mark.parametrize(
        "alteracoes",
        [
            {"abertura": time(18, 0), "fechamento": time(8, 0)},
            {"almoco_inicio": time(12, 0), "almoco_fim": None},
            {"almoco_inicio": time(7, 0), "almoco_fim": time(9, 0)},
            {"duracao_consulta": timedelta(0)},
            {"duracao_consulta": timedelta(minutes=30, seconds=1)},
            {"duracao_consulta": timedelta(hours=6)},
            {"antecedencia_minima": timedelta(hours=-1)},
            {"dias_atendimento": frozenset()},
            {"abertura": time(8, 0, 30)},
        ],
    )
    def test_rejeita_configuracao_invalida(self, alteracoes: dict[str, object]) -> None:
        with pytest.raises(DadoInvalidoError):
            funcionamento(**alteracoes)

    @pytest.mark.parametrize("dias", [0, 367])
    def test_limite_de_dias_de_busca(self, dias: int) -> None:
        with pytest.raises(DadoInvalidoError):
            Agenda(funcionamento(), dias_busca_maxima=dias)


class TestDisponibilidade:
    def test_horario_valido(self) -> None:
        agenda = Agenda(funcionamento())
        horario = agenda.validar(em(2026, 11, 19, 10, 0), AGORA)
        assert horario == Horario(em(2026, 11, 19, 10, 0), em(2026, 11, 19, 10, 30))
        resultado = agenda.resolver(PreferenciaHorario(data=QUINTA, hora=time(10, 0)), AGORA)
        assert resultado == HorarioDisponivel(em(2026, 11, 19, 10, 0))

    @pytest.mark.parametrize(
        ("inicio", "motivo"),
        [
            (em(2026, 11, 18, 8, 30), MotivoIndisponibilidade.NO_PASSADO),
            (em(2026, 11, 18, 10, 30), MotivoIndisponibilidade.ANTECEDENCIA_MINIMA),
            (em(2026, 11, 21, 10, 0), MotivoIndisponibilidade.DIA_SEM_ATENDIMENTO),
            (em(2026, 11, 19, 7, 30), MotivoIndisponibilidade.FORA_DO_EXPEDIENTE),
            (em(2026, 11, 19, 17, 45), MotivoIndisponibilidade.FORA_DO_EXPEDIENTE),
            (em(2026, 11, 19, 18, 0), MotivoIndisponibilidade.FORA_DO_EXPEDIENTE),
            (em(2026, 11, 19, 12, 0), MotivoIndisponibilidade.INTERVALO_ALMOCO),
            (em(2026, 11, 19, 11, 45), MotivoIndisponibilidade.INTERVALO_ALMOCO),
            (em(2026, 11, 19, 10, 10), MotivoIndisponibilidade.FORA_DA_GRADE),
        ],
    )
    def test_motivos_de_indisponibilidade(
        self, inicio: datetime, motivo: MotivoIndisponibilidade
    ) -> None:
        agenda = Agenda(funcionamento())
        assert agenda.motivo_indisponibilidade(inicio, AGORA) is motivo
        with pytest.raises(HorarioIndisponivelError) as erro:
            agenda.validar(inicio, AGORA)
        assert erro.value.motivo is motivo

    def test_feriado(self) -> None:
        agenda = Agenda(funcionamento(), feriados=[SEXTA])
        assert agenda.motivo_indisponibilidade(em(2026, 11, 20, 10), AGORA) is (
            MotivoIndisponibilidade.FERIADO
        )
        resultado = agenda.resolver(PreferenciaHorario(data=SEXTA, hora=time(10, 0)), AGORA)
        # Sexta é feriado e o fim de semana não tem atendimento: segunda, 23/11, às 8h.
        assert resultado == HorarioSugerido(
            em(2026, 11, 23, 8, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_bloqueio(self) -> None:
        agenda = Agenda(
            funcionamento(), bloqueios=[Horario(em(2026, 11, 19, 9, 0), em(2026, 11, 19, 10, 0))]
        )
        assert agenda.motivo_indisponibilidade(em(2026, 11, 19, 9, 30), AGORA) is (
            MotivoIndisponibilidade.BLOQUEADO
        )
        assert agenda.esta_livre(em(2026, 11, 19, 10, 0), AGORA)
        assert agenda.esta_livre(em(2026, 11, 19, 8, 30), AGORA)

    def test_bloqueio_de_varios_dias(self) -> None:
        agenda = Agenda(
            funcionamento(), bloqueios=[Horario(em(2026, 11, 19, 14, 0), em(2026, 11, 23, 9, 0))]
        )
        assert not agenda.esta_livre(em(2026, 11, 20, 10, 0), AGORA)
        assert not agenda.esta_livre(em(2026, 11, 23, 8, 30), AGORA)
        assert agenda.esta_livre(em(2026, 11, 23, 9, 0), AGORA)

    def test_recepcao_agenda_sem_antecedencia_minima(self) -> None:
        agenda = Agenda(funcionamento())
        inicio = em(2026, 11, 18, 9, 30)
        assert not agenda.esta_livre(inicio, AGORA)
        assert agenda.esta_livre(inicio, AGORA, respeitar_antecedencia=False)

    def test_horarios_livres_do_dia(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[ocupado(10)])
        livres = agenda.horarios_livres(QUINTA, QUINTA, AGORA)
        assert len(livres) == 17
        assert em(2026, 11, 19, 10, 0) not in livres
        # Hoje, para a recepção: só o que ainda não passou (09:30 em diante).
        hoje = agenda.horarios_livres(AGORA.date(), AGORA.date(), AGORA)
        assert hoje[0] == em(2026, 11, 18, 9, 30)
        assert len(hoje) == 15


class TestBuscaDoHorarioMaisProximo:
    def test_ocupado_sugere_o_mais_proximo_no_mesmo_dia(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[ocupado(10)])
        resultado = agenda.resolver(PreferenciaHorario(data=QUINTA, hora=time(10, 0)), AGORA)
        # 09:30 e 10:30 estão à mesma distância: o empate fica com o horário depois do pedido.
        assert resultado == HorarioSugerido(
            em(2026, 11, 19, 10, 30), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_mais_proximo_pode_ser_antes_do_pedido(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[ocupado(17), ocupado(17, 30), ocupado(16, 30)])
        resultado = agenda.resolver(PreferenciaHorario(data=QUINTA, hora=time(17, 0)), AGORA)
        assert resultado == HorarioSugerido(
            em(2026, 11, 19, 16, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_so_data_sugere_o_primeiro_livre_do_dia(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[ocupado(8)])
        assert agenda.resolver(PreferenciaHorario(data=QUINTA), AGORA) == HorarioSugerido(
            em(2026, 11, 19, 8, 30), MotivoSugestao.PREFERENCIA_INCOMPLETA
        )
        tarde = PreferenciaHorario(data=QUINTA, periodo=PeriodoDia.TARDE)
        assert agenda.resolver(tarde, AGORA) == HorarioSugerido(
            em(2026, 11, 19, 13, 0), MotivoSugestao.PREFERENCIA_INCOMPLETA
        )

    def test_so_periodo_busca_a_partir_de_agora(self) -> None:
        agenda = Agenda(funcionamento())
        manha = agenda.resolver(PreferenciaHorario(periodo=PeriodoDia.MANHA), AGORA)
        # Agora são 9h e a antecedência é de 2h: o primeiro horário da manhã é 11h de hoje.
        assert manha == HorarioSugerido(
            em(2026, 11, 18, 11, 0), MotivoSugestao.PREFERENCIA_INCOMPLETA
        )
        tarde = agenda.resolver(PreferenciaHorario(periodo=PeriodoDia.TARDE), AGORA)
        assert tarde == HorarioSugerido(
            em(2026, 11, 18, 13, 0), MotivoSugestao.PREFERENCIA_INCOMPLETA
        )

    def test_periodo_sem_atendimento_sugere_outro_horario(self) -> None:
        agenda = Agenda(funcionamento())
        noite = agenda.resolver(PreferenciaHorario(periodo=PeriodoDia.NOITE), AGORA)
        assert noite == HorarioSugerido(
            em(2026, 11, 18, 11, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_dia_cheio_sugere_o_dia_seguinte(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[dia_inteiro(QUINTA)])
        assert agenda.resolver(PreferenciaHorario(data=QUINTA), AGORA) == HorarioSugerido(
            em(2026, 11, 20, 8, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )
        com_hora = PreferenciaHorario(data=QUINTA, hora=time(10, 0))
        assert agenda.resolver(com_hora, AGORA) == HorarioSugerido(
            em(2026, 11, 20, 8, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_dia_cheio_mantem_o_periodo_pedido(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[dia_inteiro(QUINTA)])
        tarde = PreferenciaHorario(data=QUINTA, periodo=PeriodoDia.TARDE)
        assert agenda.resolver(tarde, AGORA) == HorarioSugerido(
            em(2026, 11, 20, 13, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_antecedencia_minima_sugere_o_primeiro_horario_permitido(self) -> None:
        agenda = Agenda(funcionamento())
        resultado = agenda.resolver(PreferenciaHorario(hora=time(10, 0)), AGORA)
        assert resultado == HorarioSugerido(
            em(2026, 11, 18, 11, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_hora_que_ja_passou_hoje_vale_para_amanha(self) -> None:
        resultado = Agenda(funcionamento()).resolver(PreferenciaHorario(hora=time(8, 0)), AGORA)
        assert resultado == HorarioDisponivel(em(2026, 11, 19, 8, 0))

    def test_data_no_passado_sugere_o_primeiro_livre(self) -> None:
        passado = PreferenciaHorario(data=date(2026, 11, 10))
        assert Agenda(funcionamento()).resolver(passado, AGORA) == HorarioSugerido(
            em(2026, 11, 18, 11, 0), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_primeiro_livre_para_emergencia(self) -> None:
        agenda = Agenda(funcionamento(antecedencia_minima=timedelta(0)))
        assert agenda.primeiro_livre(AGORA) == HorarioSugerido(
            em(2026, 11, 18, 9, 30), MotivoSugestao.PRIMEIRO_LIVRE
        )

    def test_alternativa_depois_de_conflito(self) -> None:
        agenda = Agenda(funcionamento(), ocupados=[ocupado(10)])
        assert agenda.alternativa_para(em(2026, 11, 19, 10, 0), AGORA) == HorarioSugerido(
            em(2026, 11, 19, 10, 30), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_alternativa_anterior_quando_nao_ha_horario_depois(self) -> None:
        agenda = Agenda(
            funcionamento(),
            bloqueios=[Horario(em(2026, 11, 19, 10, 0), em(2026, 11, 30, 0, 0))],
            dias_busca_maxima=5,
        )
        assert agenda.alternativa_para(em(2026, 11, 19, 10, 0), AGORA) == HorarioSugerido(
            em(2026, 11, 19, 9, 30), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def test_limite_de_busca(self) -> None:
        bloqueio = Horario(em(2026, 11, 18, 0, 0), em(2026, 11, 26, 0, 0))
        curta = Agenda(funcionamento(), bloqueios=[bloqueio], dias_busca_maxima=5)
        assert curta.primeiro_livre(AGORA) == SemHorarioLivre()
        assert curta.resolver(PreferenciaHorario(periodo=PeriodoDia.MANHA), AGORA) == (
            SemHorarioLivre()
        )
        longa = Agenda(funcionamento(), bloqueios=[bloqueio], dias_busca_maxima=10)
        assert longa.primeiro_livre(AGORA) == HorarioSugerido(
            em(2026, 11, 26, 8, 0), MotivoSugestao.PRIMEIRO_LIVRE
        )


class TestHorarioDeVerao:
    """O Brasil teve horário de verão até 2019; o fuso America/Sao_Paulo guarda o histórico."""

    def test_inicio_do_horario_de_verao(self) -> None:
        # 04/11/2018: à meia-noite os relógios pularam para 01:00 (de -03:00 para -02:00).
        agenda = Agenda(
            funcionamento(dias_atendimento=TODOS_OS_DIAS, antecedencia_minima=timedelta(hours=12))
        )
        agora = em(2018, 11, 3, 22, 0)
        # 12 horas reais depois de sábado às 22:00 (-03:00) são 11:00 de domingo (-02:00).
        resultado = agenda.primeiro_livre(agora)
        assert resultado == HorarioSugerido(em(2018, 11, 4, 11, 0), MotivoSugestao.PRIMEIRO_LIVRE)
        assert isinstance(resultado, HorarioSugerido)
        assert resultado.inicio.utcoffset() == timedelta(hours=-2)
        assert agenda.motivo_indisponibilidade(em(2018, 11, 4, 10, 30), agora) is (
            MotivoIndisponibilidade.ANTECEDENCIA_MINIMA
        )

    def test_horas_que_nao_existem_ficam_fora_da_grade(self) -> None:
        agenda = Agenda(
            funcionamento(
                dias_atendimento=TODOS_OS_DIAS,
                abertura=time(0, 0),
                fechamento=time(2, 0),
                almoco_inicio=None,
                almoco_fim=None,
                antecedencia_minima=timedelta(0),
            )
        )
        assert agenda.grade_do_dia(date(2018, 11, 4)) == (
            em(2018, 11, 4, 1, 0),
            em(2018, 11, 4, 1, 30),
        )
        assert len(agenda.grade_do_dia(date(2018, 11, 5))) == 4
        assert agenda.proximo_livre(em(2018, 11, 3, 23, 45), em(2018, 11, 3, 23, 45)) == em(
            2018, 11, 4, 1, 0
        )

    def test_fim_do_horario_de_verao(self) -> None:
        # 17/02/2019: à meia-noite os relógios voltaram para 23:00 do dia 16 (-02:00 → -03:00).
        agenda = Agenda(
            funcionamento(dias_atendimento=TODOS_OS_DIAS, antecedencia_minima=timedelta(hours=12))
        )
        agora = em(2019, 2, 16, 22, 0)
        resultado = agenda.primeiro_livre(agora)
        assert resultado == HorarioSugerido(em(2019, 2, 17, 9, 0), MotivoSugestao.PRIMEIRO_LIVRE)
        assert isinstance(resultado, HorarioSugerido)
        assert resultado.inicio.utcoffset() == timedelta(hours=-3)
        horario = agenda.validar(resultado.inicio, agora)
        assert horario.duracao == MEIA_HORA
