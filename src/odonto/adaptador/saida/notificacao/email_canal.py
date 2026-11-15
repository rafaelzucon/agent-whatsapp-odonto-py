"""Aviso ao consultório por e-mail (aiosmtplib). Habilitado só quando ``SMTP_HOST`` existe."""

from dataclasses import dataclass, field
from email.message import EmailMessage

import aiosmtplib

from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.portas.saida.notificacao import AlertaConsultorio, AvisoNovoAgendamento


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoSmtp:
    host: str
    porta: int = 587
    usuario: str | None = None
    senha: str | None = field(default=None, repr=False)
    remetente: str
    destinatario: str
    timeout_segundos: float = 20.0

    @property
    def tls_implicito(self) -> bool:
        """Porta 465 usa TLS desde a conexão; as demais usam STARTTLS quando disponível."""
        return self.porta == 465


class EmailNotificacaoConsultorio:
    """Implementa ``CanalNotificacaoConsultorio`` por e-mail."""

    nome = "email"

    def __init__(self, configuracao: ConfiguracaoSmtp, *, nome_consultorio: str) -> None:
        self._config = configuracao
        self._nome_consultorio = nome_consultorio

    async def novo_agendamento(self, aviso: AvisoNovoAgendamento) -> None:
        corpo = (
            "Nova consulta agendada pelo WhatsApp.\n\n"
            f"Paciente: {aviso.nome_paciente}\n"
            f"Prontuário: {aviso.prontuario}\n"
            f"Data e horário: {aviso.data_hora}\n"
            f"Motivo informado: {aviso.problema}\n"
            f"Prioridade: {aviso.prioridade.rotulo}\n"
        )
        await self._enviar(f"[{self._nome_consultorio}] Nova consulta: {aviso.data_hora}", corpo)

    async def alerta(self, alerta: AlertaConsultorio) -> None:
        linhas = [
            f"{alerta.tipo.value}.",
            "",
            f"Paciente: {alerta.paciente}",
            f"Detalhe: {alerta.resumo}",
        ]
        if alerta.prioridade is not None:
            linhas.append(f"Prioridade: {alerta.prioridade.rotulo}")
        if alerta.contato:
            linhas.append(f"WhatsApp para contato: +{alerta.contato}")
        linhas += ["", "Por favor, entre em contato com o paciente assim que possível."]
        await self._enviar(f"[{self._nome_consultorio}] {alerta.tipo.value}", "\n".join(linhas))

    async def _enviar(self, assunto: str, corpo: str) -> None:
        mensagem = EmailMessage()
        mensagem["From"] = self._config.remetente
        mensagem["To"] = self._config.destinatario
        mensagem["Subject"] = assunto
        mensagem.set_content(corpo)
        try:
            await aiosmtplib.send(
                mensagem,
                hostname=self._config.host,
                port=self._config.porta,
                username=self._config.usuario or None,
                password=self._config.senha or None,
                use_tls=self._config.tls_implicito,
                start_tls=None,  # STARTTLS quando o servidor oferecer
                timeout=self._config.timeout_segundos,
            )
        except (aiosmtplib.SMTPException, OSError) as erro:
            raise FalhaIntegracaoError(
                f"Falha no envio de e-mail: {type(erro).__name__}."
            ) from erro
