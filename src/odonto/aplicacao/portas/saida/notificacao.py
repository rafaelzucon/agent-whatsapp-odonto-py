"""Porta dos canais de aviso ao consultório (WhatsApp, e-mail, log...) e o conteúdo dos avisos."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from odonto.dominio.modelo.enums import Prioridade


@dataclass(frozen=True, slots=True, kw_only=True)
class AvisoNovoAgendamento:
    """Consulta agendada pelo WhatsApp."""

    nome_paciente: str = field(repr=False)
    data_hora: str
    problema: str
    prioridade: Prioridade
    prontuario: str

    def parametros_template(self) -> tuple[str, str, str, str]:
        """Corpo do template ``novo_agendamento``, nesta ordem: {{1}} nome do paciente,
        {{2}} data e horário, {{3}} problema classificado, {{4}} prioridade."""
        return (self.nome_paciente, self.data_hora, self.problema, self.prioridade.rotulo)


class TipoAlerta(StrEnum):
    """Tipo do alerta (o valor é o texto que aparece no aviso)."""

    EMERGENCIA = "Emergência odontológica"
    CONSENTIMENTO_RECUSADO = "Consentimento recusado"
    ATENDIMENTO_HUMANO = "Atendimento humano necessário"


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertaConsultorio:
    """Emergência, consentimento recusado ou conversa encaminhada para a equipe."""

    tipo: TipoAlerta
    paciente: str = field(repr=False)
    resumo: str = field(repr=False)
    prioridade: Prioridade | None = None
    contato: str | None = field(default=None, repr=False)

    def parametros_template(self) -> tuple[str, str, str]:
        """Corpo do template ``alerta_consultorio``, nesta ordem: {{1}} tipo do alerta,
        {{2}} nome do paciente ou final do número, {{3}} resumo curto."""
        return (self.tipo.value, self.paciente, self.resumo)


class CanalNotificacaoConsultorio(Protocol):
    """Um canal de aviso. Novos canais entram como novas implementações (aberto/fechado)."""

    @property
    def nome(self) -> str:
        """Nome curto do canal, para os logs (ex.: "whatsapp", "email", "log")."""
        ...

    async def novo_agendamento(self, aviso: AvisoNovoAgendamento) -> None:
        """Avisa a consulta agendada. Levanta ``FalhaIntegracaoError`` se o envio falhar."""
        ...

    async def alerta(self, alerta: AlertaConsultorio) -> None:
        """Envia o alerta. Levanta ``FalhaIntegracaoError`` se o envio falhar."""
        ...
