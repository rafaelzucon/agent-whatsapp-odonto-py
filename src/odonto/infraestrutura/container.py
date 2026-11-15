"""Raiz de composição: monta adaptadores e casos de uso à mão, sem framework de injeção.

Também converte as ``Configuracoes`` (pydantic-settings) nas dataclasses de configuração da
aplicação. É o único lugar que conhece todas as implementações concretas.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from odonto.adaptador.entrada.agendador.tarefas import criar_agendador
from odonto.adaptador.entrada.fila.consumidor import ConsumidorFila
from odonto.adaptador.entrada.web.dependencias import CasosDeUsoWeb, ConfiguracaoWeb
from odonto.adaptador.saida.fila.fila_asyncio import FilaAsyncio
from odonto.adaptador.saida.ia.anthropic_ia import (
    AnthropicClassificadorProblema,
    AnthropicInterpretadorDataHora,
    criar_cliente_anthropic,
)
from odonto.adaptador.saida.notificacao.email_canal import (
    ConfiguracaoSmtp,
    EmailNotificacaoConsultorio,
)
from odonto.adaptador.saida.notificacao.log_canal import LogNotificacaoConsultorio
from odonto.adaptador.saida.notificacao.whatsapp_canal import WhatsAppNotificacaoConsultorio
from odonto.adaptador.saida.persistencia.banco import criar_engine, criar_fabrica_sessoes
from odonto.adaptador.saida.persistencia.criptografia import (
    HmacCifradorDocumento,
    ServicoCriptografia,
)
from odonto.adaptador.saida.persistencia.unidade_de_trabalho import SqlAlchemyUnidadeDeTrabalho
from odonto.adaptador.saida.relogio.relogio_sistema import RelogioSistema
from odonto.adaptador.saida.transcricao.openai_transcritor import (
    OpenAITranscritor,
    criar_cliente_openai,
)
from odonto.adaptador.saida.whatsapp.cloud_api import WhatsAppCloudApi
from odonto.aplicacao.casos_de_uso.agendar_consulta_service import AgendarConsultaService
from odonto.aplicacao.casos_de_uso.cadastrar_paciente_service import CadastrarPacienteService
from odonto.aplicacao.casos_de_uso.conduzir_conversa_service import ConduzirConversaService
from odonto.aplicacao.casos_de_uso.consultar_pacientes_service import ConsultarPacientesService
from odonto.aplicacao.casos_de_uso.gerenciar_agenda_service import GerenciarAgendaService
from odonto.aplicacao.casos_de_uso.identificar_paciente_service import (
    IdentificarPacienteService,
)
from odonto.aplicacao.casos_de_uso.manutencao_service import (
    ExpirarConversasService,
    ExpurgarMensagensService,
)
from odonto.aplicacao.casos_de_uso.notificar_consultorio_service import (
    NotificarConsultorioService,
)
from odonto.aplicacao.casos_de_uso.receber_mensagens_service import (
    ReceberMensagensService,
    ReenfileirarPendentesService,
)
from odonto.aplicacao.casos_de_uso.reclassificar_queixa_service import (
    ConsultarCatalogoService,
    ReclassificarQueixaService,
)
from odonto.aplicacao.casos_de_uso.registrar_queixa_service import RegistrarQueixaService
from odonto.aplicacao.casos_de_uso.transcrever_audio_service import TranscreverAudioService
from odonto.aplicacao.configuracao import (
    ConfiguracaoAgenda,
    ConfiguracaoClassificacao,
    ConfiguracaoConversa,
    ConfiguracaoNotificacao,
    ConfiguracaoRecebimento,
    ConfiguracaoRetencao,
    MensagensConversa,
)
from odonto.aplicacao.excecoes import ConfiguracaoInvalidaError
from odonto.aplicacao.mensagens import RenderizadorMensagens
from odonto.aplicacao.portas.entrada.conversa import ReenfileirarPendentesUseCase
from odonto.aplicacao.portas.saida.ia import ClassificadorProblemaIA, InterpretadorDataHoraIA
from odonto.aplicacao.portas.saida.notificacao import CanalNotificacaoConsultorio
from odonto.aplicacao.portas.saida.transcricao import TranscritorAudio
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.conversa import RegrasConversa
from odonto.dominio.modelo.valores import WaId
from odonto.dominio.servico.agenda import HorarioFuncionamento
from odonto.infraestrutura.config import Configuracoes

_log = logging.getLogger(__name__)

type Fechamento = Callable[[], Awaitable[object]]

TIMEOUT_WHATSAPP = httpx.Timeout(20.0, connect=5.0)

#: Erros que as conversões abaixo levantam quando o YAML viola uma regra da aplicação/domínio.
ERROS_CONFIGURACAO = (ConfiguracaoInvalidaError, DadoInvalidoError)


# --- Conversão Configuracoes → dataclasses da aplicação ------------------------------------------


def configuracao_conversa(cfg: Configuracoes) -> ConfiguracaoConversa:
    return ConfiguracaoConversa(
        nome_consultorio=cfg.consultorio.nome,
        endereco=cfg.consultorio.endereco,
        regras=RegrasConversa(
            expiracao=timedelta(minutes=cfg.conversa.expiracao_minutos),
            max_tentativas=cfg.conversa.max_tentativas_por_etapa,
            confirmar_sugestao=cfg.agendamento.confirmar_sugestao,
        ),
    )


def mensagens_conversa(cfg: Configuracoes) -> MensagensConversa:
    return MensagensConversa.padrao().com_alteracoes(
        textos=cfg.conversa.mensagens, dicas=cfg.conversa.dicas
    )


def configuracao_agenda(cfg: Configuracoes) -> ConfiguracaoAgenda:
    agendamento = cfg.agendamento
    return ConfiguracaoAgenda(
        funcionamento=HorarioFuncionamento(
            dias_atendimento=frozenset(agendamento.dias_atendimento),
            abertura=agendamento.abertura,
            fechamento=agendamento.fechamento,
            duracao_consulta=timedelta(minutes=agendamento.duracao_minutos),
            fuso=cfg.zona,
            almoco_inicio=agendamento.almoco_inicio,
            almoco_fim=agendamento.almoco_fim,
            antecedencia_minima=timedelta(hours=agendamento.antecedencia_minima_horas),
        ),
        feriados=frozenset(agendamento.feriados),
        dias_busca_maxima=agendamento.dias_busca_maxima,
    )


def configuracao_classificacao(cfg: Configuracoes) -> ConfiguracaoClassificacao:
    palavras = cfg.classificacao.palavras_alarme
    if palavras is None:
        return ConfiguracaoClassificacao(confianca_minima=cfg.classificacao.confianca_minima)
    return ConfiguracaoClassificacao(
        confianca_minima=cfg.classificacao.confianca_minima, palavras_alarme=tuple(palavras)
    )


def configuracao_recebimento(cfg: Configuracoes) -> ConfiguracaoRecebimento:
    """O celular da recepção recebe os avisos: as mensagens dele não iniciam conversa."""
    ignorados = {cfg.consultorio_whatsapp_notificacao} - {""}
    return ConfiguracaoRecebimento(numeros_ignorados=frozenset(ignorados))


def configuracao_web(cfg: Configuracoes) -> ConfiguracaoWeb:
    return ConfiguracaoWeb(
        verify_token=cfg.whatsapp_verify_token.get_secret_value(),
        app_secret=cfg.whatsapp_app_secret.get_secret_value(),
        admin_token=cfg.admin_token.get_secret_value(),
        phone_number_id=cfg.whatsapp_phone_number_id or None,
        docs_habilitada=cfg.api.docs_habilitada,
    )


def configuracao_retencao(cfg: Configuracoes) -> ConfiguracaoRetencao:
    return ConfiguracaoRetencao(mensagens_dias=cfg.retencao.mensagens_dias)


def validar_configuracoes(cfg: Configuracoes) -> None:
    """Faz todas as conversões sem abrir conexões, para falhar antes de subir o servidor."""
    configuracao_conversa(cfg)
    mensagens_conversa(cfg)
    configuracao_agenda(cfg)
    configuracao_classificacao(cfg)
    configuracao_recebimento(cfg)
    configuracao_retencao(cfg)


# --- Container ---------------------------------------------------------------------------------


@dataclass(slots=True, kw_only=True)
class Container:
    """Objetos de vida longa do processo e o que precisa ser iniciado e encerrado."""

    configuracoes: Configuracoes
    engine: AsyncEngine
    fila: FilaAsyncio
    casos_web: CasosDeUsoWeb
    configuracao_web: ConfiguracaoWeb
    consumidor: ConsumidorFila
    agendador: AsyncIOScheduler
    reenfileirar_pendentes: ReenfileirarPendentesUseCase
    fechamentos: list[Fechamento] = field(default_factory=list)

    async def iniciar(self) -> None:
        self.consumidor.iniciar()
        try:
            await self.reenfileirar_pendentes.executar()
        except Exception:
            _log.exception("não foi possível reenfileirar as mensagens pendentes")
        self.agendador.start()

    async def encerrar(self) -> None:
        if self.agendador.running:
            self.agendador.shutdown(wait=False)
        await self.consumidor.parar()
        for fechar in reversed(self.fechamentos):
            try:
                await fechar()
            except Exception:
                _log.exception("falha ao encerrar recurso")

    async def banco_disponivel(self) -> bool:
        try:
            async with self.engine.connect() as conexao:
                await conexao.execute(text("SELECT 1"))
        except Exception:
            _log.warning("banco de dados indisponível", exc_info=True)
            return False
        return True


def _canais(cfg: Configuracoes, whatsapp: WhatsAppCloudApi) -> list[CanalNotificacaoConsultorio]:
    canais: list[CanalNotificacaoConsultorio] = [LogNotificacaoConsultorio()]
    if cfg.aviso_whatsapp_habilitado:
        canais.append(
            WhatsAppNotificacaoConsultorio(
                whatsapp,
                destino=WaId(cfg.consultorio_whatsapp_notificacao),
                template_novo_agendamento=cfg.whatsapp_template_novo_agendamento,
                template_alerta=cfg.whatsapp_template_alerta,
                idioma=cfg.whatsapp_template_idioma,
            )
        )
    if cfg.email_habilitado:
        canais.append(
            EmailNotificacaoConsultorio(
                ConfiguracaoSmtp(
                    host=cfg.smtp_host,
                    porta=cfg.smtp_port,
                    usuario=cfg.smtp_usuario or None,
                    senha=cfg.smtp_senha.get_secret_value() or None,
                    remetente=cfg.smtp_remetente or cfg.smtp_usuario or cfg.consultorio_email,
                    destinatario=cfg.consultorio_email,
                ),
                nome_consultorio=cfg.consultorio.nome,
            )
        )
    return canais


def montar_container(cfg: Configuracoes) -> Container:
    fechamentos: list[Fechamento] = []
    fuso = cfg.zona

    criptografia = ServicoCriptografia(cfg.chave_criptografia_bytes)
    cifrador_documento = HmacCifradorDocumento(cfg.chave_hmac_bytes)
    engine = criar_engine(cfg.database_url, criptografia)
    fechamentos.append(engine.dispose)

    fila = FilaAsyncio()
    uow = SqlAlchemyUnidadeDeTrabalho(criar_fabrica_sessoes(engine), publicador=fila)
    relogio = RelogioSistema(fuso)

    http = httpx.AsyncClient(timeout=TIMEOUT_WHATSAPP)
    fechamentos.append(http.aclose)
    whatsapp = WhatsAppCloudApi(
        http,
        phone_number_id=cfg.whatsapp_phone_number_id,
        access_token=cfg.whatsapp_access_token.get_secret_value(),
        versao_api=cfg.whatsapp_api_version,
    )

    classificador_ia: ClassificadorProblemaIA | None = None
    interpretador_ia: InterpretadorDataHoraIA | None = None
    if cfg.ia_habilitada:
        anthropic = criar_cliente_anthropic(
            cfg.anthropic_api_key.get_secret_value(),
            timeout_segundos=cfg.anthropic_timeout_segundos,
        )
        fechamentos.append(anthropic.close)
        classificador_ia = AnthropicClassificadorProblema(anthropic, modelo=cfg.anthropic_model)
        interpretador_ia = AnthropicInterpretadorDataHora(anthropic, modelo=cfg.anthropic_model)

    transcritor: TranscritorAudio | None = None
    if cfg.transcricao_habilitada:
        openai = criar_cliente_openai(
            cfg.openai_api_key.get_secret_value(), timeout_segundos=cfg.openai_timeout_segundos
        )
        fechamentos.append(openai.close)
        transcritor = OpenAITranscritor(openai, modelo=cfg.transcricao_modelo)

    conversa = configuracao_conversa(cfg)
    agenda = configuracao_agenda(cfg)

    identificar = IdentificarPacienteService(uow=uow, cifrador=cifrador_documento, relogio=relogio)
    cadastrar = CadastrarPacienteService(uow=uow, cifrador=cifrador_documento, relogio=relogio)
    registrar_queixa = RegistrarQueixaService(
        uow=uow,
        relogio=relogio,
        classificador_ia=classificador_ia,
        configuracao=configuracao_classificacao(cfg),
    )
    agendar = AgendarConsultaService(uow=uow, relogio=relogio, configuracao=agenda)
    conduzir = ConduzirConversaService(
        uow=uow,
        relogio=relogio,
        enviador=whatsapp,
        renderizador=RenderizadorMensagens(conversa, mensagens_conversa(cfg), fuso),
        configuracao=conversa,
        configuracao_agenda=agenda,
        transcrever_audio=TranscreverAudioService(midias=whatsapp, transcritor=transcritor),
        identificar_paciente=identificar,
        cadastrar_paciente=cadastrar,
        registrar_queixa=registrar_queixa,
        agendar_consulta=agendar,
        interpretador_ia=interpretador_ia,
    )
    notificar = NotificarConsultorioService(
        uow=uow,
        canais=_canais(cfg, whatsapp),
        configuracao=ConfiguracaoNotificacao(fuso=fuso),
    )

    casos_web = CasosDeUsoWeb(
        receber_mensagens=ReceberMensagensService(
            uow=uow, fila=fila, relogio=relogio, configuracao=configuracao_recebimento(cfg)
        ),
        agendar_consulta=agendar,
        gerenciar_agenda=GerenciarAgendaService(uow=uow, relogio=relogio, configuracao=agenda),
        consultar_pacientes=ConsultarPacientesService(uow=uow, cifrador=cifrador_documento),
        reclassificar_queixa=ReclassificarQueixaService(uow=uow, relogio=relogio),
        consultar_catalogo=ConsultarCatalogoService(uow=uow),
    )
    agendador = criar_agendador(
        expirar_conversas=ExpirarConversasService(uow=uow, relogio=relogio, regras=conversa.regras),
        expurgar_mensagens=ExpurgarMensagensService(
            uow=uow,
            relogio=relogio,
            configuracao=configuracao_retencao(cfg),
        ),
        fuso=fuso,
        horario_expurgo=cfg.retencao.horario,
    )
    return Container(
        configuracoes=cfg,
        engine=engine,
        fila=fila,
        casos_web=casos_web,
        configuracao_web=configuracao_web(cfg),
        consumidor=ConsumidorFila(fila, conduzir, notificar),
        agendador=agendador,
        reenfileirar_pendentes=ReenfileirarPendentesService(uow=uow, fila=fila),
        fechamentos=fechamentos,
    )
