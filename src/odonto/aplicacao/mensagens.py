"""Mensagens ao paciente: troca dos placeholders e datas escritas em português."""

import re
from datetime import datetime, tzinfo
from typing import Final

from odonto.aplicacao.configuracao import ConfiguracaoConversa, MensagensConversa
from odonto.dominio.modelo.conversa import MensagemAoPaciente
from odonto.dominio.modelo.enums import ChaveMensagem, DiaSemana

PLACEHOLDERS: Final = ("NOME_CONSULTORIO", "NOME_PACIENTE", "DATA_HORA", "ENDERECO", "PRONTUARIO")
_REGEX_PLACEHOLDER: Final = re.compile(r"\b(?:" + "|".join(PLACEHOLDERS) + r")\b")
_REGEX_VIRGULA_SOLTA: Final = re.compile(r",\s*([!?.])")
_REGEX_ESPACO_ANTES_PONTUACAO: Final = re.compile(r"[ \t]+([,.!?;:])")
_REGEX_ESPACOS: Final = re.compile(r"[ \t]{2,}")


def formatar_data_hora(momento: datetime, fuso: tzinfo) -> str:
    """Ex.: "sexta-feira, 20/11/2026 às 10:00" (no fuso do consultório)."""
    local = momento.astimezone(fuso)
    return f"{DiaSemana.de_data(local.date()).nome}, {local:%d/%m/%Y} às {local:%H:%M}"


class RenderizadorMensagens:
    """Monta o texto final de uma ``MensagemAoPaciente`` a partir dos textos configurados.

    Placeholders sem valor somem sem deixar pontuação solta ("Olá, NOME_PACIENTE!" → "Olá!").
    """

    __slots__ = ("_configuracao", "_fuso", "_mensagens")

    def __init__(
        self, configuracao: ConfiguracaoConversa, mensagens: MensagensConversa, fuso: tzinfo
    ) -> None:
        self._configuracao = configuracao
        self._mensagens = mensagens
        self._fuso = fuso

    def renderizar(self, mensagem: MensagemAoPaciente) -> str:
        texto = self._mensagens.texto(mensagem.chave)
        if mensagem.chave is ChaveMensagem.NAO_ENTENDI and mensagem.etapa is not None:
            dica = self._mensagens.dica(mensagem.etapa)
            if dica:
                texto = f"{texto} {dica}"
        valores = {
            "NOME_CONSULTORIO": self._configuracao.nome_consultorio,
            "ENDERECO": self._configuracao.endereco,
            "NOME_PACIENTE": mensagem.nome_paciente or "",
            "DATA_HORA": (
                formatar_data_hora(mensagem.data_hora, self._fuso) if mensagem.data_hora else ""
            ),
            "PRONTUARIO": str(mensagem.prontuario) if mensagem.prontuario else "",
        }
        texto = _REGEX_PLACEHOLDER.sub(lambda m: valores[m.group(0)], texto)
        texto = _REGEX_VIRGULA_SOLTA.sub(r"\1", texto)
        texto = _REGEX_ESPACO_ANTES_PONTUACAO.sub(r"\1", texto)
        return _REGEX_ESPACOS.sub(" ", texto).strip()
