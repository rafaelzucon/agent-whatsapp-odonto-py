"""Configurações: segredos nas variáveis de ambiente (ou ``.env``) e o resto no YAML.

O arquivo YAML é ``config/odonto.yaml`` (ou o caminho em ``ODONTO_CONFIG``). As variáveis de
ambiente têm precedência sobre o YAML. ``Configuracoes`` só existe aqui na infraestrutura: o
``container.py`` converte tudo nas dataclasses de configuração da aplicação.
"""

import os
from datetime import date, time
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from odonto.adaptador.saida.ia.anthropic_ia import MODELO_PADRAO as MODELO_ANTHROPIC_PADRAO
from odonto.adaptador.saida.persistencia.criptografia import ChaveInvalidaError, decodificar_chave
from odonto.adaptador.saida.transcricao.openai_transcritor import (
    MODELO_PADRAO as MODELO_TRANSCRICAO_PADRAO,
)
from odonto.adaptador.saida.whatsapp.cloud_api import VERSAO_PADRAO as VERSAO_GRAPH_PADRAO
from odonto.dominio.modelo.enums import DiaSemana

ARQUIVO_PADRAO = Path("config/odonto.yaml")
VARIAVEL_ARQUIVO = "ODONTO_CONFIG"
FUSO_PADRAO = "America/Sao_Paulo"
TAMANHO_MINIMO_TOKEN_ADMIN = 16


def caminho_configuracao() -> Path:
    return Path(os.environ.get(VARIAVEL_ARQUIVO) or ARQUIVO_PADRAO)


def normalizar_url_banco(url: str) -> str:
    """Aceita ``postgresql://`` (formato comum) e usa o driver assíncrono do psycopg 3."""
    for prefixo in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url.removeprefix(prefixo)
    raise ValueError("DATABASE_URL deve começar com postgresql://")


def _hora(valor: Any) -> Any:
    """Aceita "08:00" e também o número que o YAML 1.1 gera para 12:00 sem aspas (720)."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return time(*divmod(valor, 60))
    return valor


type HoraLocal = Annotated[time, BeforeValidator(_hora)]


class _Secao(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SecaoConsultorio(_Secao):
    nome: str = Field(default="Consultório Odontológico", min_length=1, max_length=120)
    endereco: str = Field(default="", max_length=300)


class SecaoConversa(_Secao):
    expiracao_minutos: int = Field(default=120, ge=5, le=7 * 24 * 60)
    max_tentativas_por_etapa: int = Field(default=3, ge=1, le=10)
    mensagens: dict[str, str] = Field(default_factory=dict)
    dicas: dict[str, str] = Field(default_factory=dict)


class SecaoClassificacao(_Secao):
    confianca_minima: float = Field(default=0.6, ge=0, le=1)
    palavras_alarme: list[str] | None = None


class SecaoAgendamento(_Secao):
    duracao_minutos: int = Field(default=30, ge=5, le=240)
    dias_atendimento: list[DiaSemana] = Field(
        default_factory=lambda: [
            DiaSemana.SEG,
            DiaSemana.TER,
            DiaSemana.QUA,
            DiaSemana.QUI,
            DiaSemana.SEX,
        ],
        min_length=1,
    )
    abertura: HoraLocal = time(8)
    fechamento: HoraLocal = time(18)
    almoco_inicio: HoraLocal | None = time(12)
    almoco_fim: HoraLocal | None = time(13)
    antecedencia_minima_horas: float = Field(default=2, ge=0, le=24 * 30)
    dias_busca_maxima: int = Field(default=60, ge=1, le=365)
    confirmar_sugestao: bool = True
    feriados: list[date] = Field(default_factory=list)


class SecaoRetencao(_Secao):
    mensagens_dias: int = Field(default=90, ge=1, le=3650)
    horario: HoraLocal = time(3, 30)


class SecaoApi(_Secao):
    docs_habilitada: bool = False


class Configuracoes(BaseSettings):
    """Tudo o que a aplicação precisa saber do ambiente, já validado."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    # --- YAML (config/odonto.yaml) ---
    fuso: str | None = None
    consultorio: SecaoConsultorio = Field(default_factory=SecaoConsultorio)
    conversa: SecaoConversa = Field(default_factory=SecaoConversa)
    classificacao: SecaoClassificacao = Field(default_factory=SecaoClassificacao)
    agendamento: SecaoAgendamento = Field(default_factory=SecaoAgendamento)
    retencao: SecaoRetencao = Field(default_factory=SecaoRetencao)
    api: SecaoApi = Field(default_factory=SecaoApi)

    # --- Variáveis de ambiente ---
    database_url: str = Field(min_length=1)
    chave_criptografia: SecretStr
    chave_hmac_documento: SecretStr
    admin_token: SecretStr = SecretStr("")

    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_api_version: str = Field(default=VERSAO_GRAPH_PADRAO, pattern=r"^v\d+\.\d+$")
    whatsapp_template_novo_agendamento: str = "novo_agendamento"
    whatsapp_template_alerta: str = "alerta_consultorio"
    whatsapp_template_idioma: str = "pt_BR"
    consultorio_whatsapp_notificacao: str = ""

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = MODELO_ANTHROPIC_PADRAO
    anthropic_timeout_segundos: float = Field(default=30, gt=0, le=300)

    transcricao_provedor: Literal["openai", "none"] = "openai"
    transcricao_modelo: str = MODELO_TRANSCRICAO_PADRAO
    openai_api_key: SecretStr = SecretStr("")
    openai_timeout_segundos: float = Field(default=60, gt=0, le=300)

    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_usuario: str = ""
    smtp_senha: SecretStr = SecretStr("")
    smtp_remetente: str = ""
    consultorio_email: str = ""

    tz: str | None = None
    log_nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    host: str = "0.0.0.0"  # noqa: S104 - dentro do container; a porta publicada decide a exposição
    porta: int = Field(default=8080, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml = YamlConfigSettingsSource(settings_cls, yaml_file=caminho_configuracao())
        return init_settings, env_settings, dotenv_settings, yaml, file_secret_settings

    @field_validator("database_url")
    @classmethod
    def _driver_psycopg(cls, valor: str) -> str:
        return normalizar_url_banco(valor)

    @field_validator("chave_criptografia", "chave_hmac_documento")
    @classmethod
    def _chave_de_32_bytes(cls, valor: SecretStr) -> SecretStr:
        try:
            decodificar_chave(valor.get_secret_value(), "chave")
        except ChaveInvalidaError as erro:
            raise ValueError(
                f'{erro} Gere com: python -c "import base64,os; '
                'print(base64.b64encode(os.urandom(32)).decode())"'
            ) from None
        return valor

    @field_validator("admin_token")
    @classmethod
    def _token_forte(cls, valor: SecretStr) -> SecretStr:
        if 0 < len(valor.get_secret_value()) < TAMANHO_MINIMO_TOKEN_ADMIN:
            raise ValueError(f"ADMIN_TOKEN precisa de {TAMANHO_MINIMO_TOKEN_ADMIN}+ caracteres.")
        return valor

    @model_validator(mode="after")
    def _coerencia(self) -> Self:
        if (
            self.chave_criptografia.get_secret_value()
            == self.chave_hmac_documento.get_secret_value()
        ):
            raise ValueError("CHAVE_CRIPTOGRAFIA e CHAVE_HMAC_DOCUMENTO devem ser diferentes.")
        try:
            ZoneInfo(self.nome_fuso)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError(f"Fuso horário desconhecido: {self.nome_fuso!r}.") from None
        return self

    # --- Derivados ---

    @property
    def nome_fuso(self) -> str:
        return self.fuso or self.tz or FUSO_PADRAO

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.nome_fuso)

    @property
    def chave_criptografia_bytes(self) -> bytes:
        return decodificar_chave(self.chave_criptografia.get_secret_value(), "CHAVE_CRIPTOGRAFIA")

    @property
    def chave_hmac_bytes(self) -> bytes:
        return decodificar_chave(
            self.chave_hmac_documento.get_secret_value(), "CHAVE_HMAC_DOCUMENTO"
        )

    @property
    def whatsapp_configurado(self) -> bool:
        return bool(self.whatsapp_phone_number_id and self.whatsapp_access_token.get_secret_value())

    @property
    def aviso_whatsapp_habilitado(self) -> bool:
        return bool(
            self.whatsapp_configurado
            and self.consultorio_whatsapp_notificacao
            and self.whatsapp_template_novo_agendamento
            and self.whatsapp_template_alerta
        )

    @property
    def email_habilitado(self) -> bool:
        return bool(self.smtp_host and self.consultorio_email)

    @property
    def ia_habilitada(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value())

    @property
    def transcricao_habilitada(self) -> bool:
        return self.transcricao_provedor == "openai" and bool(
            self.openai_api_key.get_secret_value()
        )

    def pendencias(self) -> list[str]:
        """O que falta configurar (o app sobe mesmo assim; os avisos vão para o log)."""
        faltando = []
        if not self.whatsapp_configurado:
            faltando.append(
                "WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN: respostas não serão enviadas"
            )
        if not self.whatsapp_app_secret.get_secret_value():
            faltando.append("WHATSAPP_APP_SECRET: o webhook recusará todas as mensagens (401)")
        if not self.whatsapp_verify_token.get_secret_value():
            faltando.append("WHATSAPP_VERIFY_TOKEN: o cadastro do webhook na Meta falhará")
        if not self.admin_token.get_secret_value():
            faltando.append("ADMIN_TOKEN: a API da recepção ficará fechada")
        if not self.ia_habilitada:
            faltando.append("ANTHROPIC_API_KEY: classificação só por palavras-chave")
        if self.transcricao_provedor == "openai" and not self.transcricao_habilitada:
            faltando.append("OPENAI_API_KEY: áudios não serão transcritos")
        if not self.aviso_whatsapp_habilitado:
            faltando.append(
                "CONSULTORIO_WHATSAPP_NOTIFICACAO: aviso ao consultório só por e-mail/log"
            )
        return faltando


def carregar_configuracoes(**valores: Any) -> Configuracoes:
    """Lê ambiente + YAML. ``valores`` sobrepõem tudo (útil em testes)."""
    caminho = caminho_configuracao()
    if os.environ.get(VARIAVEL_ARQUIVO) and not caminho.is_file():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {caminho}")
    return Configuracoes(**valores)
