"""Canal de log: sempre ativo, registra só metadados (nunca nome, RG ou texto da queixa)."""

import logging

from odonto.aplicacao.portas.saida.notificacao import AlertaConsultorio, AvisoNovoAgendamento

_log = logging.getLogger("odonto.notificacao")


class LogNotificacaoConsultorio:
    """Implementa ``CanalNotificacaoConsultorio`` gravando um evento no log."""

    nome = "log"

    async def novo_agendamento(self, aviso: AvisoNovoAgendamento) -> None:
        _log.info(
            "aviso ao consultório: novo agendamento",
            extra={
                "prontuario": aviso.prontuario,
                "data_hora": aviso.data_hora,
                "prioridade": aviso.prioridade.value,
            },
        )

    async def alerta(self, alerta: AlertaConsultorio) -> None:
        _log.warning(
            "aviso ao consultório: alerta",
            extra={
                "tipo": alerta.tipo.name,
                "prioridade": alerta.prioridade.value if alerta.prioridade else None,
                "final_contato": alerta.contato[-4:] if alerta.contato else None,
            },
        )
