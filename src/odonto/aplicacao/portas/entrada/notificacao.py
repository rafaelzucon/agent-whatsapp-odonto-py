"""Porta de entrada do aviso ao consultório."""

from typing import Protocol

from odonto.dominio.modelo.eventos import EventoDominio


class NotificarConsultorioUseCase(Protocol):
    async def notificar(self, evento: EventoDominio) -> None:
        """Avisa o consultório por todos os canais habilitados.

        ``ConsultaAgendada`` (só as do WhatsApp) → aviso de novo agendamento; emergência,
        consentimento recusado e atendimento humano → alerta. A falha de um canal não impede
        os outros e não levanta exceção.
        """
        ...
