"""Objetos de valor: normalização e invariantes."""

from datetime import date, time, timedelta

import pytest

from odonto.dominio.excecoes import DadoInvalidoError, JanelaAtendimentoExpiradaError
from odonto.dominio.modelo.enums import PeriodoDia, Uf
from odonto.dominio.modelo.valores import (
    DocumentoRg,
    Horario,
    JanelaAtendimento,
    NumeroProntuario,
    PreferenciaHorario,
    WaId,
    idade_em,
)
from tests.apoio import AGORA, FUSO, em


class TestDocumentoRg:
    def test_normaliza_numero_e_uf(self) -> None:
        rg = DocumentoRg.criar("12.345.678-x", " sp ")
        assert rg.numero == "12345678X"
        assert rg.uf is Uf.SP
        assert rg.chave_normalizada == "12345678X:SP"
        assert rg.formatado == "12345678X SP"

    @pytest.mark.parametrize("numero", ["1234", "123456789012345", "12X45678", "abcdef", ""])
    def test_rejeita_numero_invalido(self, numero: str) -> None:
        with pytest.raises(DadoInvalidoError) as erro:
            DocumentoRg.criar(numero, "SP")
        assert erro.value.campo == "rg"

    def test_rejeita_uf_invalida(self) -> None:
        with pytest.raises(DadoInvalidoError) as erro:
            DocumentoRg.criar("123456789", "XX")
        assert erro.value.campo == "uf"

    def test_numero_nao_aparece_no_repr(self) -> None:
        assert "123456789" not in repr(DocumentoRg.criar("123456789", "SP"))


class TestWaId:
    def test_aceita_numero_com_ddi(self) -> None:
        wa_id = WaId("5511987654321")
        assert wa_id.final == "4321"
        assert "5511987654321" not in repr(wa_id)

    @pytest.mark.parametrize("valor", ["+5511987654321", "11987", "55 11 98765 4321", ""])
    def test_rejeita_formato_invalido(self, valor: str) -> None:
        with pytest.raises(DadoInvalidoError):
            WaId(valor)


class TestHorario:
    def test_fim_precisa_ser_depois_do_inicio(self) -> None:
        with pytest.raises(DadoInvalidoError):
            Horario(em(2026, 11, 20, 10), em(2026, 11, 20, 10))

    def test_exige_fuso_horario(self) -> None:
        with pytest.raises(DadoInvalidoError):
            Horario(em(2026, 11, 20, 10).replace(tzinfo=None), em(2026, 11, 20, 11))

    def test_sobreposicao_considera_intervalo_semiaberto(self) -> None:
        nove = Horario.com_duracao(em(2026, 11, 20, 9), timedelta(minutes=30))
        nove_e_meia = Horario.com_duracao(em(2026, 11, 20, 9, 30), timedelta(minutes=30))
        nove_e_quinze = Horario.com_duracao(em(2026, 11, 20, 9, 15), timedelta(minutes=30))
        assert not nove.sobrepoe(nove_e_meia)
        assert nove.sobrepoe(nove_e_quinze)
        assert nove_e_quinze.sobrepoe(nove_e_meia)

    def test_duracao_em_tempo_real_na_entrada_do_horario_de_verao(self) -> None:
        # 04/11/2018: à meia-noite os relógios de São Paulo pularam para 01:00.
        horario = Horario(em(2018, 11, 3, 23, 0), em(2018, 11, 4, 1, 30))
        assert horario.duracao == timedelta(hours=1, minutes=30)


class TestJanelaAtendimento:
    def test_aberta_por_24_horas(self) -> None:
        janela = JanelaAtendimento(AGORA)
        assert janela.aberta_em(AGORA + timedelta(hours=23, minutes=59))
        assert not janela.aberta_em(AGORA + timedelta(hours=24))

    def test_garantir_aberta_levanta_erro_depois_de_24_horas(self) -> None:
        with pytest.raises(JanelaAtendimentoExpiradaError):
            JanelaAtendimento(AGORA).garantir_aberta(AGORA + timedelta(days=1, seconds=1))


class TestNumeroProntuario:
    def test_formata_e_le_texto(self) -> None:
        numero = NumeroProntuario(123)
        assert str(numero) == "PR-000123"
        assert NumeroProntuario.de_texto(" pr-000123 ") == numero

    def test_ordenacao(self) -> None:
        assert NumeroProntuario(2) > NumeroProntuario(1)

    @pytest.mark.parametrize("texto", ["PR-12", "123", "PR-ABCDEF"])
    def test_rejeita_texto_invalido(self, texto: str) -> None:
        with pytest.raises(DadoInvalidoError):
            NumeroProntuario.de_texto(texto)

    def test_rejeita_sequencial_nao_positivo(self) -> None:
        with pytest.raises(DadoInvalidoError):
            NumeroProntuario(0)


class TestPreferenciaHorario:
    def test_exige_ao_menos_um_campo(self) -> None:
        with pytest.raises(DadoInvalidoError):
            PreferenciaHorario()

    def test_hora_e_local(self) -> None:
        with pytest.raises(DadoInvalidoError):
            PreferenciaHorario(hora=time(10, 0, tzinfo=FUSO))

    def test_aceita_so_periodo(self) -> None:
        assert PreferenciaHorario(periodo=PeriodoDia.TARDE).periodo is PeriodoDia.TARDE


@pytest.mark.parametrize(
    ("nascimento", "hoje", "idade"),
    [
        (date(2000, 11, 18), date(2026, 11, 18), 26),
        (date(2000, 11, 19), date(2026, 11, 18), 25),
        (date(2008, 2, 29), date(2026, 2, 28), 17),
        (date(2008, 2, 29), date(2026, 3, 1), 18),
    ],
)
def test_idade_completa(nascimento: date, hoje: date, idade: int) -> None:
    assert idade_em(nascimento, hoje) == idade
