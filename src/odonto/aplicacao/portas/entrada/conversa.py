"""Portas de entrada da conversa pelo WhatsApp e das rotinas de manutenção."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from odonto.dominio.modelo.enums import EtapaConversa, TipoMensagem


@dataclass(frozen=True, slots=True, kw_only=True)
class MensagemRecebidaCommand:
    """Mensagem do paciente traduzida do webhook (``wa_id`` ainda não validado)."""

    wa_id: str = field(repr=False)
    wa_message_id: str
    tipo: TipoMensagem
    texto: str | None = field(default=None, repr=False)
    midia_id: str | None = None
    momento: datetime


@dataclass(frozen=True, slots=True)
class ResultadoRecebimento:
    novas: int = 0
    duplicadas: int = 0
    ignoradas: int = 0


class ReceberMensagensUseCase(Protocol):
    async def executar(self, comandos: Sequence[MensagemRecebidaCommand]) -> ResultadoRecebimento:
        """Grava as mensagens novas (idempotente por ``wa_message_id``) e, depois do commit,
        enfileira o processamento. Ignora números ignorados e ``wa_id`` inválidos."""
        ...


@dataclass(frozen=True, slots=True)
class ProcessarMensagemCommand:
    mensagem_id: UUID


@dataclass(frozen=True, slots=True)
class ResultadoConducao:
    processada: bool
    etapa: EtapaConversa | None = None
    mensagens_enviadas: int = 0


class ConduzirConversaUseCase(Protocol):
    async def executar(self, comando: ProcessarMensagemCommand) -> ResultadoConducao:
        """Passa a mensagem pela máquina de estados, executa os comandos resultantes (busca,
        cadastro, classificação, agendamento), grava tudo e responde ao paciente.

        Mensagem inexistente ou já processada: ``processada=False``, sem efeitos.
        """
        ...


class TranscreverAudioUseCase(Protocol):
    async def executar(self, midia_id: str) -> str | None:
        """Baixa e transcreve o áudio. ``None`` se a transcrição estiver desabilitada, falhar
        ou vier vazia (a conversa então pede a resposta por texto)."""
        ...


class ReenfileirarPendentesUseCase(Protocol):
    async def executar(self) -> int:
        """Na inicialização: enfileira as mensagens recebidas e ainda não processadas."""
        ...


class ExpirarConversasUseCase(Protocol):
    async def executar(self) -> int:
        """Encerra as conversas inativas há mais que a expiração. Devolve quantas."""
        ...


@dataclass(frozen=True, slots=True)
class ResultadoExpurgo:
    mensagens: int
    conversas: int


class ExpurgarMensagensUseCase(Protocol):
    async def executar(self) -> ResultadoExpurgo:
        """Apaga mensagens e conversas encerradas além do prazo de retenção."""
        ...
