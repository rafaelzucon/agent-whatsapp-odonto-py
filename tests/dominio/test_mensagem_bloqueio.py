"""Mensagens do WhatsApp e bloqueios de agenda."""

from datetime import timedelta

import pytest

from odonto.dominio.excecoes import DadoInvalidoError, TransicaoInvalidaError
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.enums import DirecaoMensagem, TipoMensagem
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.valores import Horario
from tests.apoio import AGORA, WA_ID, em


def receber(tipo: TipoMensagem = TipoMensagem.TEXTO) -> Mensagem:
    return Mensagem.recebida(
        wa_id=WA_ID,
        wa_message_id="wamid.1",
        tipo=tipo,
        texto="oi" if tipo is TipoMensagem.TEXTO else None,
        midia_id="midia-1" if tipo is TipoMensagem.AUDIO else None,
        momento=AGORA,
        criada_em=AGORA,
    )


def test_mensagem_recebida_fica_pendente_ate_ser_processada() -> None:
    mensagem = receber()
    assert mensagem.pendente
    mensagem.marcar_processada(AGORA)
    assert not mensagem.pendente


def test_transcricao_so_em_audio() -> None:
    audio = receber(TipoMensagem.AUDIO)
    audio.registrar_transcricao("quero marcar uma limpeza")
    assert audio.texto == "quero marcar uma limpeza"
    with pytest.raises(TransicaoInvalidaError):
        receber().registrar_transcricao("texto")


def test_mensagem_enviada_e_automatica() -> None:
    enviada = Mensagem.enviada(wa_id=WA_ID, texto="Olá!", wa_message_id="wamid.2", momento=AGORA)
    assert enviada.direcao is DirecaoMensagem.ENVIADA
    assert enviada.automatica
    assert not enviada.pendente
    with pytest.raises(TransicaoInvalidaError):
        enviada.marcar_processada(AGORA)
    assert "Olá" not in repr(enviada)


def test_bloqueio_de_agenda() -> None:
    bloqueio = BloqueioAgenda.criar(
        inicio=em(2026, 12, 21, 0),
        fim=em(2027, 1, 4, 0),
        motivo="  Férias   coletivas ",
        momento=AGORA,
    )
    assert bloqueio.motivo == "Férias coletivas"
    assert bloqueio.bloqueia(Horario.com_duracao(em(2026, 12, 22, 9), timedelta(minutes=30)))
    assert not bloqueio.bloqueia(Horario.com_duracao(em(2027, 1, 4, 8), timedelta(minutes=30)))


@pytest.mark.parametrize("motivo", ["", "   ", "x" * 201])
def test_bloqueio_exige_motivo(motivo: str) -> None:
    with pytest.raises(DadoInvalidoError):
        BloqueioAgenda.criar(
            inicio=em(2026, 12, 21), fim=em(2026, 12, 22), motivo=motivo, momento=AGORA
        )
