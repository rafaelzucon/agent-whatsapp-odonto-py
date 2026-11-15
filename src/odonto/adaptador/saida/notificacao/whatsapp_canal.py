"""Aviso ao consultório por template do WhatsApp, para o celular da recepção."""

from odonto.aplicacao.portas.saida.notificacao import AlertaConsultorio, AvisoNovoAgendamento
from odonto.aplicacao.portas.saida.whatsapp import EnviadorWhatsApp
from odonto.dominio.modelo.valores import WaId


class WhatsAppNotificacaoConsultorio:
    """Implementa ``CanalNotificacaoConsultorio`` com os templates aprovados na Meta.

    Avisos ao consultório saem fora da janela de 24h, por isso exigem template (``novo_agendamento``
    com 4 parâmetros e ``alerta_consultorio`` com 3). O destino é um número diferente do número
    do consultório: a Meta não entrega mensagens de um número para ele mesmo.
    """

    nome = "whatsapp"

    def __init__(
        self,
        enviador: EnviadorWhatsApp,
        *,
        destino: WaId,
        template_novo_agendamento: str,
        template_alerta: str,
        idioma: str = "pt_BR",
    ) -> None:
        self._enviador = enviador
        self._destino = destino
        self._template_novo_agendamento = template_novo_agendamento
        self._template_alerta = template_alerta
        self._idioma = idioma

    async def novo_agendamento(self, aviso: AvisoNovoAgendamento) -> None:
        await self._enviador.enviar_template(
            self._destino,
            self._template_novo_agendamento,
            aviso.parametros_template(),
            idioma=self._idioma,
        )

    async def alerta(self, alerta: AlertaConsultorio) -> None:
        await self._enviador.enviar_template(
            self._destino, self._template_alerta, alerta.parametros_template(), idioma=self._idioma
        )
