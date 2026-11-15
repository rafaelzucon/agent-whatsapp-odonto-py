"""Mensagem de WhatsApp recebida do paciente ou enviada pelo agente."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid7

from odonto.dominio.excecoes import TransicaoInvalidaError
from odonto.dominio.modelo.agregado import Entidade
from odonto.dominio.modelo.enums import DirecaoMensagem, TipoMensagem
from odonto.dominio.modelo.tempo import exigir_fuso
from odonto.dominio.modelo.valores import WaId


@dataclass(slots=True, kw_only=True, eq=False)
class Mensagem(Entidade):
    id: UUID
    wa_id: WaId
    direcao: DirecaoMensagem
    tipo: TipoMensagem
    texto: str | None = field(default=None, repr=False)
    wa_message_id: str | None = None
    midia_id: str | None = None
    automatica: bool = False
    momento: datetime
    criada_em: datetime
    processada_em: datetime | None = None

    @classmethod
    def recebida(
        cls,
        *,
        wa_id: WaId,
        wa_message_id: str,
        tipo: TipoMensagem,
        texto: str | None,
        midia_id: str | None,
        momento: datetime,
        criada_em: datetime,
        id: UUID | None = None,
    ) -> Mensagem:
        """Mensagem do paciente, ainda pendente de processamento."""
        return cls(
            id=id or uuid7(),
            wa_id=wa_id,
            direcao=DirecaoMensagem.RECEBIDA,
            tipo=tipo,
            texto=texto,
            wa_message_id=wa_message_id,
            midia_id=midia_id,
            momento=exigir_fuso(momento, "momento"),
            criada_em=exigir_fuso(criada_em, "criada_em"),
        )

    @classmethod
    def enviada(
        cls,
        *,
        wa_id: WaId,
        texto: str,
        wa_message_id: str | None,
        momento: datetime,
        tipo: TipoMensagem = TipoMensagem.TEXTO,
        id: UUID | None = None,
    ) -> Mensagem:
        """Mensagem enviada automaticamente pelo agente (``automatica=True``)."""
        exigir_fuso(momento, "momento")
        return cls(
            id=id or uuid7(),
            wa_id=wa_id,
            direcao=DirecaoMensagem.ENVIADA,
            tipo=tipo,
            texto=texto,
            wa_message_id=wa_message_id,
            automatica=True,
            momento=momento,
            criada_em=momento,
            processada_em=momento,
        )

    @property
    def pendente(self) -> bool:
        return self.direcao is DirecaoMensagem.RECEBIDA and self.processada_em is None

    def registrar_transcricao(self, texto: str) -> None:
        if self.tipo is not TipoMensagem.AUDIO:
            raise TransicaoInvalidaError("Só mensagens de áudio recebem transcrição.")
        self.texto = texto

    def marcar_processada(self, momento: datetime) -> None:
        if self.direcao is not DirecaoMensagem.RECEBIDA:
            raise TransicaoInvalidaError("Só mensagens recebidas são processadas.")
        self.processada_em = exigir_fuso(momento, "momento")
