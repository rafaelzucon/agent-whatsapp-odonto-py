"""Adaptadores de IA com o SDK oficial da Anthropic (saída estruturada validada com Pydantic).

A IA recebe só o texto da queixa ou da data: nunca nome, RG, telefone ou ids internos.
"""

import functools
import logging
from collections.abc import Sequence
from datetime import date, datetime, time
from enum import StrEnum
from importlib import resources
from typing import Literal

from anthropic import AnthropicError, AsyncAnthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.portas.saida.ia import ClassificacaoIA
from odonto.dominio.modelo.enums import PeriodoDia, Prioridade
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.valores import PreferenciaHorario

_log = logging.getLogger(__name__)

MODELO_PADRAO = "claude-haiku-5-5"
MAXIMO_CARACTERES_TEXTO = 2000
_DIAS_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def criar_cliente_anthropic(api_key: str, *, timeout_segundos: float) -> AsyncAnthropic:
    """Fábrica usada pela raiz de composição (a infraestrutura não importa o SDK)."""
    return AsyncAnthropic(api_key=api_key, timeout=timeout_segundos, max_retries=3)


@functools.cache
def _prompt(nome: str) -> str:
    return (resources.files(__package__) / "prompts" / nome).read_text(encoding="utf-8")


def _como_dado(texto: str) -> str:
    """Texto do paciente pronto para ir entre tags: sem ``<``/``>`` (não fecha a tag) e curto."""
    return texto.strip()[:MAXIMO_CARACTERES_TEXTO].replace("<", "‹").replace(">", "›")


# --- Classificação da queixa ------------------------------------------------------------------


class _RespostaClassificacaoBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confianca: float = Field(
        ge=0, le=1, description="De 0 a 1: o quanto a queixa corresponde ao item escolhido."
    )
    prioridade: Literal["EMERGENCIA", "URGENCIA", "ROTINA"] = Field(
        description="Prioridade de atendimento; na dúvida, a mais alta."
    )
    sintomas: list[str] = Field(
        max_length=5, description="Até 5 sintomas curtos citados pelo paciente."
    )
    sinais_alarme: bool = Field(
        description="True se houver inchaço no rosto/pescoço, febre, dificuldade para engolir "
        "ou respirar, sangramento persistente, trauma recente ou dente arrancado."
    )


@functools.lru_cache(maxsize=8)
def _modelo_resposta(codigos: tuple[str, ...]) -> type[_RespostaClassificacaoBase]:
    """Modelo com o ``codigo`` restrito aos códigos do catálogo atual (enum no JSON Schema)."""
    codigo_problema = StrEnum("CodigoProblema", {codigo: codigo for codigo in codigos})  # type: ignore[misc]
    return create_model(
        "RespostaClassificacao",
        __base__=_RespostaClassificacaoBase,
        codigo=(codigo_problema, Field(description="Exatamente um código da lista do catálogo.")),
    )


def _descrever_catalogo(catalogo: Sequence[ProblemaOdontologico]) -> str:
    return "\n".join(
        f"- {p.codigo}: {p.nome}. {p.descricao} (prioridade padrão: {p.prioridade.value})"
        for p in catalogo
    )


class AnthropicClassificadorProblema:
    """Implementa ``ClassificadorProblemaIA``."""

    def __init__(self, cliente: AsyncAnthropic, *, modelo: str = MODELO_PADRAO) -> None:
        self._cliente = cliente
        self._modelo = modelo

    async def classificar(
        self, queixa: str, catalogo: Sequence[ProblemaOdontologico]
    ) -> ClassificacaoIA:
        modelo_resposta = _modelo_resposta(tuple(p.codigo for p in catalogo))
        conteudo = (
            f"<catalogo>\n{_descrever_catalogo(catalogo)}\n</catalogo>\n\n"
            f"<queixa>\n{_como_dado(queixa)}\n</queixa>"
        )
        try:
            resposta = await self._cliente.messages.parse(
                model=self._modelo,
                max_tokens=1024,
                system=_prompt("classificacao_sistema.md"),
                messages=[{"role": "user", "content": conteudo}],
                output_format=modelo_resposta,
            )
            saida = resposta.parsed_output
        except (AnthropicError, ValidationError, ValueError) as erro:
            raise FalhaIntegracaoError(
                f"Classificação pela IA falhou: {type(erro).__name__}."
            ) from erro
        if saida is None:
            raise FalhaIntegracaoError(
                f"A IA não devolveu a classificação (stop_reason={resposta.stop_reason})."
            )
        dados = saida.model_dump(mode="json")
        return ClassificacaoIA(
            codigo=str(dados["codigo"]),
            confianca=float(dados["confianca"]),
            prioridade=Prioridade(dados["prioridade"]),
            sintomas=tuple(s.strip() for s in dados["sintomas"] if s.strip()),
            sinais_alarme=bool(dados["sinais_alarme"]),
        )


# --- Interpretação de data e hora ------------------------------------------------------------


class RespostaDataHora(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entendeu: bool = Field(
        description="False se a mensagem for ambígua ou não tiver data, hora nem período."
    )
    data: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Data desejada no formato AAAA-MM-DD, se o paciente informou o dia.",
    )
    hora: str | None = Field(
        default=None,
        pattern=r"^\d{2}:\d{2}$",
        description="Hora desejada no formato HH:MM (24 horas), se o paciente informou.",
    )
    periodo: Literal["MANHA", "TARDE", "NOITE"] | None = Field(
        default=None, description="Período do dia, se o paciente informou e não deu a hora."
    )


def preferencia_da_resposta(resposta: RespostaDataHora) -> PreferenciaHorario | None:
    """Converte a resposta da IA. ``None`` = não entendeu (ou não informou nada)."""
    if not resposta.entendeu or (resposta.data, resposta.hora, resposta.periodo) == (None,) * 3:
        return None
    try:
        return PreferenciaHorario(
            data=date.fromisoformat(resposta.data) if resposta.data else None,
            hora=time.fromisoformat(resposta.hora) if resposta.hora else None,
            periodo=PeriodoDia(resposta.periodo) if resposta.periodo else None,
        )
    except ValueError as erro:
        raise FalhaIntegracaoError("A IA devolveu data ou hora inválida.") from erro


class AnthropicInterpretadorDataHora:
    """Implementa ``InterpretadorDataHoraIA``."""

    def __init__(self, cliente: AsyncAnthropic, *, modelo: str = MODELO_PADRAO) -> None:
        self._cliente = cliente
        self._modelo = modelo

    async def interpretar(self, texto: str, agora: datetime) -> PreferenciaHorario | None:
        referencia = (
            f"<agora>{agora.strftime('%Y-%m-%d %H:%M')} ({_DIAS_SEMANA[agora.weekday()]}), "
            f"fuso {agora.tzinfo}</agora>"
        )
        try:
            resposta = await self._cliente.messages.parse(
                model=self._modelo,
                max_tokens=256,
                system=f"{_prompt('data_hora_sistema.md')}\n\n{referencia}",
                messages=[
                    {"role": "user", "content": f"<mensagem>\n{_como_dado(texto)}\n</mensagem>"}
                ],
                output_format=RespostaDataHora,
            )
            saida = resposta.parsed_output
        except (AnthropicError, ValidationError, ValueError) as erro:
            raise FalhaIntegracaoError(
                f"Interpretação de data falhou: {type(erro).__name__}."
            ) from erro
        if saida is None:
            raise FalhaIntegracaoError("A IA não devolveu a interpretação da data.")
        return preferencia_da_resposta(saida)
