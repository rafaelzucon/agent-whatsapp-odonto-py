"""Agenda do consultório: grade de horários, disponibilidade e horário livre mais próximo.

Regra pura: recebe os horários ocupados e os bloqueios já carregados pelo caso de uso e decide.
A IA nunca decide disponibilidade; ela só interpreta o texto em uma ``PreferenciaHorario``.

Datas com fuso: a grade é de horário de parede (08:00, 08:30...) no fuso do consultório; prazos
(antecedência, "no passado") são medidos em tempo real, o que importa em dias de horário de verão.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Final

from odonto.dominio.excecoes import (
    DadoInvalidoError,
    HorarioIndisponivelError,
    MotivoIndisponibilidade,
)
from odonto.dominio.modelo.enums import DiaSemana, MotivoSugestao, PeriodoDia
from odonto.dominio.modelo.tempo import diferenca_real, exigir_fuso, somar_tempo_real
from odonto.dominio.modelo.valores import Horario, PreferenciaHorario

DIAS_BUSCA_PADRAO: Final = 60
DIAS_BUSCA_LIMITE: Final = 366
_ZERO: Final = timedelta(0)
_UM_DIA: Final = timedelta(days=1)
_MEIA_NOITE: Final = time(0, 0)


def _desde_meia_noite(hora: time) -> timedelta:
    return timedelta(
        hours=hora.hour, minutes=hora.minute, seconds=hora.second, microseconds=hora.microsecond
    )


def _hora(desde_meia_noite: timedelta) -> time:
    segundos = int(desde_meia_noite.total_seconds())
    return time(segundos // 3600, segundos % 3600 // 60, segundos % 60)


@dataclass(frozen=True, slots=True, kw_only=True)
class HorarioFuncionamento:
    """Expediente do consultório (horas locais, sem fuso, interpretadas no ``fuso``)."""

    dias_atendimento: frozenset[DiaSemana]
    abertura: time
    fechamento: time
    duracao_consulta: timedelta
    fuso: tzinfo
    almoco_inicio: time | None = None
    almoco_fim: time | None = None
    antecedencia_minima: timedelta = _ZERO

    def __post_init__(self) -> None:
        if not self.dias_atendimento:
            raise DadoInvalidoError("dias_atendimento", "Informe ao menos um dia de atendimento.")
        horas = (self.abertura, self.fechamento, self.almoco_inicio, self.almoco_fim)
        if any(hora is not None and hora.tzinfo is not None for hora in horas):
            raise DadoInvalidoError("expediente", "As horas do expediente são locais (sem fuso).")
        if any(hora is not None and (hora.second or hora.microsecond) for hora in horas):
            raise DadoInvalidoError("expediente", "Use horas e minutos exatos (ex.: 08:30).")
        if self.abertura >= self.fechamento:
            raise DadoInvalidoError("expediente", "A abertura precisa ser antes do fechamento.")
        if (self.almoco_inicio is None) != (self.almoco_fim is None):
            raise DadoInvalidoError("almoco", "Informe o início e o fim do almoço, ou nenhum.")
        if (
            self.almoco_inicio is not None
            and self.almoco_fim is not None
            and not self.abertura < self.almoco_inicio < self.almoco_fim < self.fechamento
        ):
            raise DadoInvalidoError("almoco", "O almoço precisa ficar dentro do expediente.")
        if self.duracao_consulta <= _ZERO or self.duracao_consulta % timedelta(minutes=1):
            raise DadoInvalidoError(
                "duracao_consulta", "A duração da consulta deve ser um número inteiro de minutos."
            )
        if self.antecedencia_minima < _ZERO:
            raise DadoInvalidoError("antecedencia_minima", "A antecedência não pode ser negativa.")
        if not self.grade():
            raise DadoInvalidoError(
                "duracao_consulta", "A duração da consulta não cabe em nenhum turno do expediente."
            )

    def turnos(self) -> tuple[tuple[time, time], ...]:
        """Turnos de atendimento (manhã e tarde, se houver almoço)."""
        if self.almoco_inicio is None or self.almoco_fim is None:
            return ((self.abertura, self.fechamento),)
        return ((self.abertura, self.almoco_inicio), (self.almoco_fim, self.fechamento))

    def grade(self) -> tuple[time, ...]:
        """Horários de início das consultas: de ``duracao_consulta`` em ``duracao_consulta``."""
        horarios: list[time] = []
        for inicio, fim in self.turnos():
            atual, limite = _desde_meia_noite(inicio), _desde_meia_noite(fim)
            while atual + self.duracao_consulta <= limite:
                horarios.append(_hora(atual))
                atual += self.duracao_consulta
        return tuple(horarios)


@dataclass(frozen=True, slots=True)
class HorarioDisponivel:
    """O horário pedido está livre e pode ser agendado."""

    inicio: datetime


@dataclass(frozen=True, slots=True)
class HorarioSugerido:
    """O pedido não pôde ser atendido como veio; este é o horário livre mais próximo."""

    inicio: datetime
    motivo: MotivoSugestao


@dataclass(frozen=True, slots=True)
class SemHorarioLivre:
    """Não há horário livre dentro do limite de busca."""


type ResultadoBusca = HorarioDisponivel | HorarioSugerido | SemHorarioLivre


def _indexar_por_dia(horarios: Iterable[Horario], fuso: tzinfo) -> dict[date, tuple[Horario, ...]]:
    """Agrupa os intervalos por dia local (um bloqueio de férias entra em todos os seus dias)."""
    por_dia: defaultdict[date, list[Horario]] = defaultdict(list)
    for horario in horarios:
        dia = horario.inicio.astimezone(fuso).date()
        ultimo_dia = horario.fim.astimezone(fuso).date()
        while dia <= ultimo_dia:
            por_dia[dia].append(horario)
            dia += _UM_DIA
    return {dia: tuple(lista) for dia, lista in por_dia.items()}


class Agenda:
    """Agenda única (um dentista): diz se um horário está livre e encontra o mais próximo."""

    __slots__ = (
        "_bloqueios",
        "_dias_busca_maxima",
        "_feriados",
        "_funcionamento",
        "_grade",
        "_grade_conjunto",
        "_ocupados",
    )

    def __init__(
        self,
        funcionamento: HorarioFuncionamento,
        *,
        feriados: Iterable[date] = (),
        bloqueios: Iterable[Horario] = (),
        ocupados: Iterable[Horario] = (),
        dias_busca_maxima: int = DIAS_BUSCA_PADRAO,
    ) -> None:
        if not 1 <= dias_busca_maxima <= DIAS_BUSCA_LIMITE:
            raise DadoInvalidoError(
                "dias_busca_maxima", f"Os dias de busca devem estar entre 1 e {DIAS_BUSCA_LIMITE}."
            )
        self._funcionamento = funcionamento
        self._feriados = frozenset(feriados)
        self._bloqueios = _indexar_por_dia(bloqueios, funcionamento.fuso)
        self._ocupados = _indexar_por_dia(ocupados, funcionamento.fuso)
        self._dias_busca_maxima = dias_busca_maxima
        self._grade = funcionamento.grade()
        self._grade_conjunto = frozenset(self._grade)

    @property
    def funcionamento(self) -> HorarioFuncionamento:
        return self._funcionamento

    @property
    def dias_busca_maxima(self) -> int:
        return self._dias_busca_maxima

    # ----------------------------------------------------------------------------- consultas

    def atende_no_dia(self, dia: date) -> bool:
        return (
            DiaSemana.de_data(dia) in self._funcionamento.dias_atendimento
            and dia not in self._feriados
        )

    def grade_do_dia(self, dia: date) -> tuple[datetime, ...]:
        """Horários da grade no dia (vazio se não houver atendimento), no fuso do consultório."""
        if not self.atende_no_dia(dia):
            return ()
        return tuple(
            momento
            for hora in self._grade
            if (momento := self._momento_existente(dia, hora)) is not None
        )

    def motivo_indisponibilidade(
        self, inicio: datetime, agora: datetime, *, respeitar_antecedencia: bool = True
    ) -> MotivoIndisponibilidade | None:
        """``None`` se o horário pode ser agendado; senão, o primeiro motivo que o impede.

        A recepção agenda sem a antecedência mínima (``respeitar_antecedencia=False``).
        """
        funcionamento = self._funcionamento
        local = exigir_fuso(inicio, "inicio").astimezone(funcionamento.fuso)
        falta = diferenca_real(local, exigir_fuso(agora, "agora"))
        if falta <= _ZERO:
            return MotivoIndisponibilidade.NO_PASSADO
        if respeitar_antecedencia and falta < funcionamento.antecedencia_minima:
            return MotivoIndisponibilidade.ANTECEDENCIA_MINIMA
        dia = local.date()
        if DiaSemana.de_data(dia) not in funcionamento.dias_atendimento:
            return MotivoIndisponibilidade.DIA_SEM_ATENDIMENTO
        if dia in self._feriados:
            return MotivoIndisponibilidade.FERIADO
        comeco = _desde_meia_noite(local.time())
        termino = comeco + funcionamento.duracao_consulta
        if comeco < _desde_meia_noite(funcionamento.abertura) or termino > _desde_meia_noite(
            funcionamento.fechamento
        ):
            return MotivoIndisponibilidade.FORA_DO_EXPEDIENTE
        if (
            funcionamento.almoco_inicio is not None
            and funcionamento.almoco_fim is not None
            and comeco < _desde_meia_noite(funcionamento.almoco_fim)
            and _desde_meia_noite(funcionamento.almoco_inicio) < termino
        ):
            return MotivoIndisponibilidade.INTERVALO_ALMOCO
        if local.time() not in self._grade_conjunto:
            return MotivoIndisponibilidade.FORA_DA_GRADE
        horario = self._horario_da_consulta(local)
        if any(bloqueio.sobrepoe(horario) for bloqueio in self._bloqueios.get(dia, ())):
            return MotivoIndisponibilidade.BLOQUEADO
        if any(ocupado.sobrepoe(horario) for ocupado in self._ocupados.get(dia, ())):
            return MotivoIndisponibilidade.OCUPADO
        return None

    def esta_livre(
        self, inicio: datetime, agora: datetime, *, respeitar_antecedencia: bool = True
    ) -> bool:
        motivo = self.motivo_indisponibilidade(
            inicio, agora, respeitar_antecedencia=respeitar_antecedencia
        )
        return motivo is None

    def validar(
        self, inicio: datetime, agora: datetime, *, respeitar_antecedencia: bool = True
    ) -> Horario:
        """Devolve o intervalo da consulta ou levanta ``HorarioIndisponivelError``."""
        motivo = self.motivo_indisponibilidade(
            inicio, agora, respeitar_antecedencia=respeitar_antecedencia
        )
        if motivo is not None:
            raise HorarioIndisponivelError(motivo, inicio)
        return self._horario_da_consulta(inicio.astimezone(self._funcionamento.fuso))

    # ------------------------------------------------------------------------------- buscas

    def proximo_livre(
        self, a_partir: datetime, agora: datetime, *, periodo: PeriodoDia | None = None
    ) -> datetime | None:
        """Primeiro horário livre a partir de ``a_partir`` (ou de agora, se já passou)."""
        inicio = a_partir if diferenca_real(a_partir, agora) > _ZERO else agora
        for momento in self._grade_a_partir(inicio):
            if periodo is not None and not periodo.contem(momento.time()):
                continue
            if self.esta_livre(momento, agora):
                return momento
        return None

    def anterior_livre_no_dia(self, antes_de: datetime, agora: datetime) -> datetime | None:
        """Último horário livre do mesmo dia, antes de ``antes_de``."""
        local = antes_de.astimezone(self._funcionamento.fuso)
        for momento in reversed(self.grade_do_dia(local.date())):
            if diferenca_real(momento, local) < _ZERO and self.esta_livre(momento, agora):
                return momento
        return None

    def mais_proximo_livre(self, pedido: datetime, agora: datetime) -> datetime | None:
        """Horário livre mais próximo do pedido: no mesmo dia (antes ou depois, empate fica com
        o depois); se o dia estiver cheio, o próximo livre nos dias seguintes."""
        local = pedido.astimezone(self._funcionamento.fuso)
        livres = [m for m in self.grade_do_dia(local.date()) if self.esta_livre(m, agora)]
        if livres:
            return min(
                livres,
                key=lambda m: (abs(diferenca_real(m, local)), diferenca_real(m, local) < _ZERO),
            )
        return self.proximo_livre(local, agora)

    def primeiro_livre_no_dia(
        self, dia: date, agora: datetime, *, periodo: PeriodoDia | None = None
    ) -> datetime | None:
        for momento in self.grade_do_dia(dia):
            if periodo is not None and not periodo.contem(momento.time()):
                continue
            if self.esta_livre(momento, agora):
                return momento
        return None

    def horarios_livres(
        self,
        primeiro_dia: date,
        ultimo_dia: date,
        agora: datetime,
        *,
        respeitar_antecedencia: bool = False,
    ) -> tuple[datetime, ...]:
        """Todos os horários livres entre dois dias (inclusive), para a API administrativa."""
        livres: list[datetime] = []
        dia = primeiro_dia
        while dia <= ultimo_dia:
            livres.extend(
                momento
                for momento in self.grade_do_dia(dia)
                if self.esta_livre(momento, agora, respeitar_antecedencia=respeitar_antecedencia)
            )
            dia += _UM_DIA
        return tuple(livres)

    def primeiro_livre(self, agora: datetime) -> ResultadoBusca:
        """Primeiro horário livre a partir de agora (oferecido em emergências)."""
        return self._sugerir(self.proximo_livre(agora, agora), MotivoSugestao.PRIMEIRO_LIVRE)

    def alternativa_para(self, inicio: datetime, agora: datetime) -> ResultadoBusca:
        """Quando o horário escolhido foi ocupado no meio-tempo: o próximo livre (ou, se não
        houver nos dias seguintes, o anterior no mesmo dia)."""
        alternativa = self.proximo_livre(inicio, agora) or self.anterior_livre_no_dia(inicio, agora)
        return self._sugerir(alternativa, MotivoSugestao.HORARIO_INDISPONIVEL)

    def resolver(self, preferencia: PreferenciaHorario, agora: datetime) -> ResultadoBusca:
        """Transforma a preferência do paciente em um horário livre (pedido ou sugerido).

        - Com hora: o horário pedido, se livre; senão, o mais próximo (HORARIO_INDISPONIVEL).
          Sem data, vale hoje se a hora ainda não passou; senão, amanhã.
        - Só data (e talvez período): o primeiro livre no dia/período (PREFERENCIA_INCOMPLETA);
          se não houver, o próximo nos dias seguintes, no mesmo período se possível.
        - Só período: o primeiro livre nesse período a partir de agora.
        """
        exigir_fuso(agora, "agora")
        match preferencia:
            case PreferenciaHorario(hora=time() as hora):
                return self._resolver_hora(preferencia.data, hora, agora)
            case PreferenciaHorario(data=date() as data):
                return self._resolver_data(data, preferencia.periodo, agora)
            case PreferenciaHorario(periodo=PeriodoDia() as periodo):
                return self._resolver_periodo(periodo, agora)
            case _:  # pragma: no cover - PreferenciaHorario exige ao menos um campo
                return SemHorarioLivre()

    # ------------------------------------------------------------------------------ apoio

    def _resolver_hora(self, data: date | None, hora: time, agora: datetime) -> ResultadoBusca:
        if data is None:
            hoje = agora.astimezone(self._funcionamento.fuso).date()
            ainda_hoje = diferenca_real(self._momento(hoje, hora), agora) > _ZERO
            data = hoje if ainda_hoje else hoje + _UM_DIA
        pedido = self._momento(data, hora)
        if self.esta_livre(pedido, agora):
            return HorarioDisponivel(pedido)
        return self._sugerir(
            self.mais_proximo_livre(pedido, agora), MotivoSugestao.HORARIO_INDISPONIVEL
        )

    def _resolver_data(
        self, data: date, periodo: PeriodoDia | None, agora: datetime
    ) -> ResultadoBusca:
        hoje = agora.astimezone(self._funcionamento.fuso).date()
        if data < hoje:
            return self._resolver_periodo(
                periodo, agora, motivo=MotivoSugestao.HORARIO_INDISPONIVEL
            )
        no_dia = self.primeiro_livre_no_dia(data, agora, periodo=periodo)
        if no_dia is not None:
            return HorarioSugerido(no_dia, MotivoSugestao.PREFERENCIA_INCOMPLETA)
        inicio_do_dia = self._momento(data, _MEIA_NOITE)
        alternativa = None
        if periodo is not None:
            alternativa = self.proximo_livre(inicio_do_dia, agora, periodo=periodo)
        if alternativa is None:
            alternativa = self.proximo_livre(inicio_do_dia, agora)
        return self._sugerir(alternativa, MotivoSugestao.HORARIO_INDISPONIVEL)

    def _resolver_periodo(
        self,
        periodo: PeriodoDia | None,
        agora: datetime,
        *,
        motivo: MotivoSugestao = MotivoSugestao.PREFERENCIA_INCOMPLETA,
    ) -> ResultadoBusca:
        if periodo is not None:
            no_periodo = self.proximo_livre(agora, agora, periodo=periodo)
            if no_periodo is not None:
                return HorarioSugerido(no_periodo, motivo)
        return self._sugerir(self.proximo_livre(agora, agora), MotivoSugestao.HORARIO_INDISPONIVEL)

    @staticmethod
    def _sugerir(inicio: datetime | None, motivo: MotivoSugestao) -> ResultadoBusca:
        return SemHorarioLivre() if inicio is None else HorarioSugerido(inicio, motivo)

    def _grade_a_partir(self, inicio: datetime) -> Iterator[datetime]:
        """Horários da grade a partir de ``inicio`` (inclusive), até o limite de dias de busca."""
        primeiro_dia = inicio.astimezone(self._funcionamento.fuso).date()
        for deslocamento in range(self._dias_busca_maxima + 1):
            for momento in self.grade_do_dia(primeiro_dia + timedelta(days=deslocamento)):
                if diferenca_real(momento, inicio) >= _ZERO:
                    yield momento

    def _horario_da_consulta(self, inicio_local: datetime) -> Horario:
        fim = somar_tempo_real(inicio_local, self._funcionamento.duracao_consulta)
        return Horario(inicio_local, fim)

    def _momento(self, dia: date, hora: time) -> datetime:
        """Data e hora locais no fuso; uma hora que não existe (início do horário de verão)
        vira a hora equivalente logo depois do salto."""
        ingenuo = datetime.combine(dia, hora, tzinfo=self._funcionamento.fuso)
        return ingenuo.astimezone(UTC).astimezone(self._funcionamento.fuso)

    def _momento_existente(self, dia: date, hora: time) -> datetime | None:
        momento = self._momento(dia, hora)
        if momento.replace(tzinfo=None) != datetime.combine(dia, hora):
            return None
        return momento
