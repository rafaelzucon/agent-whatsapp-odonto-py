"""Condução da conversa: máquina de estados do domínio + execução dos comandos + respostas."""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from odonto.aplicacao.casos_de_uso.montador_agenda import janela_de_busca, montar_agenda
from odonto.aplicacao.configuracao import ConfiguracaoAgenda, ConfiguracaoConversa
from odonto.aplicacao.excecoes import ErroAplicacao, FalhaIntegracaoError
from odonto.aplicacao.mensagens import RenderizadorMensagens
from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaCommand, AgendarConsultaUseCase
from odonto.aplicacao.portas.entrada.conversa import (
    ProcessarMensagemCommand,
    ResultadoConducao,
    TranscreverAudioUseCase,
)
from odonto.aplicacao.portas.entrada.pacientes import (
    CadastrarPacienteCommand,
    CadastrarPacienteUseCase,
    IdentificarPacienteCommand,
    IdentificarPacienteUseCase,
)
from odonto.aplicacao.portas.entrada.prontuario import (
    RegistrarQueixaCommand,
    RegistrarQueixaUseCase,
)
from odonto.aplicacao.portas.saida.ia import InterpretadorDataHoraIA
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.aplicacao.portas.saida.whatsapp import EnviadorWhatsApp
from odonto.dominio.excecoes import ErroDominio, HorarioIndisponivelError
from odonto.dominio.modelo.conversa import (
    AcaoConversa,
    AgendarHorario,
    BuscarPaciente,
    CadastrarPaciente,
    ClassificarQueixa,
    ComandoConversa,
    Conversa,
    InterpretarDataHora,
    MensagemAoPaciente,
    OferecerPrimeiroHorario,
)
from odonto.dominio.modelo.enums import OrigemAgendamento, TipoMensagem
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.valores import PreferenciaHorario, WaId
from odonto.dominio.servico.agenda import (
    Agenda,
    HorarioDisponivel,
    HorarioSugerido,
    ResultadoBusca,
    SemHorarioLivre,
)
from odonto.dominio.servico.interpretador_data_hora import InterpretadorDataHoraDeterministico

logger = logging.getLogger(__name__)

MAXIMO_COMANDOS_POR_MENSAGEM: Final = 10
_TIPOS_COM_TEXTO: Final = frozenset({TipoMensagem.TEXTO, TipoMensagem.AUDIO})


class ConduzirConversaService:
    """Processa uma mensagem recebida, do começo ao fim.

    1. Áudio sem texto é transcrito antes (fora da transação, é uma chamada externa).
    2. Numa transação: a ``Conversa`` do número reage à mensagem e pede comandos (buscar,
       cadastrar, classificar, interpretar data, agendar); cada comando chama um caso de uso
       (que participa da mesma transação) e devolve o resultado à conversa, até não haver mais
       comandos. A mensagem é marcada como processada e tudo é gravado de uma vez.
    3. Depois do commit, as respostas são enviadas (dentro da janela de 24h) e gravadas.

    Qualquer erro de negócio inesperado num comando encaminha a conversa para a equipe, em
    vez de deixar o paciente sem resposta.
    """

    def __init__(
        self,
        *,
        uow: UnidadeDeTrabalho,
        relogio: Relogio,
        enviador: EnviadorWhatsApp,
        renderizador: RenderizadorMensagens,
        configuracao: ConfiguracaoConversa,
        configuracao_agenda: ConfiguracaoAgenda,
        transcrever_audio: TranscreverAudioUseCase,
        identificar_paciente: IdentificarPacienteUseCase,
        cadastrar_paciente: CadastrarPacienteUseCase,
        registrar_queixa: RegistrarQueixaUseCase,
        agendar_consulta: AgendarConsultaUseCase,
        interpretador_ia: InterpretadorDataHoraIA | None,
    ) -> None:
        self._uow = uow
        self._relogio = relogio
        self._enviador = enviador
        self._renderizador = renderizador
        self._regras = configuracao.regras
        self._configuracao_agenda = configuracao_agenda
        self._transcrever_audio = transcrever_audio
        self._identificar_paciente = identificar_paciente
        self._cadastrar_paciente = cadastrar_paciente
        self._registrar_queixa = registrar_queixa
        self._agendar_consulta = agendar_consulta
        self._interpretador_ia = interpretador_ia
        self._interpretador = InterpretadorDataHoraDeterministico()

    async def executar(self, comando: ProcessarMensagemCommand) -> ResultadoConducao:
        async with self._uow as uow:
            mensagem = await uow.mensagens.buscar_por_id(comando.mensagem_id)
        if mensagem is None or not mensagem.pendente:
            return ResultadoConducao(processada=False)

        transcricao = None
        if mensagem.tipo is TipoMensagem.AUDIO and not mensagem.texto and mensagem.midia_id:
            transcricao = await self._transcrever_audio.executar(mensagem.midia_id)

        async with self._uow as uow:
            mensagem = await uow.mensagens.buscar_por_id(comando.mensagem_id)
            if mensagem is None or not mensagem.pendente:
                return ResultadoConducao(processada=False)
            if transcricao:
                mensagem.registrar_transcricao(transcricao)
            agora = self._relogio.agora()
            conversa = await uow.conversas.buscar_por_wa_id(mensagem.wa_id)
            if conversa is None:
                conversa, acao = Conversa.iniciar(mensagem.wa_id, mensagem.momento)
            else:
                texto = mensagem.texto if mensagem.tipo in _TIPOS_COM_TEXTO else None
                acao = conversa.registrar_resposta(
                    texto, recebida_em=mensagem.momento, agora=agora, regras=self._regras
                )
            respostas = await self._executar_comandos(conversa, acao, agora)
            mensagem.marcar_processada(agora)
            await uow.mensagens.salvar(mensagem)
            await uow.conversas.salvar(conversa)
            await uow.commit()

        enviadas = await self._responder(conversa, respostas)
        logger.info(
            "mensagem processada",
            extra={
                "wa_final": conversa.wa_id.final,
                "etapa": conversa.etapa.value,
                "respostas": len(respostas),
                "enviadas": enviadas,
            },
        )
        return ResultadoConducao(processada=True, etapa=conversa.etapa, mensagens_enviadas=enviadas)

    # --- Comandos --------------------------------------------------------------------------

    async def _executar_comandos(
        self, conversa: Conversa, acao: AcaoConversa, agora: datetime
    ) -> list[MensagemAoPaciente]:
        respostas = list(acao.mensagens)
        comando = acao.comando
        passos = 0
        while comando is not None:
            passos += 1
            if passos > MAXIMO_COMANDOS_POR_MENSAGEM:
                logger.error("limite de comandos por mensagem atingido")
                acao = conversa.encaminhar_para_equipe(
                    "O atendimento automático não conseguiu concluir o agendamento.", agora
                )
            else:
                try:
                    acao = await self._executar(conversa, comando, agora)
                except (ErroDominio, ErroAplicacao) as erro:
                    logger.exception(
                        "falha ao executar comando da conversa",
                        extra={"comando": type(comando).__name__, "erro": type(erro).__name__},
                    )
                    acao = conversa.encaminhar_para_equipe(
                        "Falha no atendimento automático; verifique a conversa.", agora
                    )
            respostas.extend(acao.mensagens)
            comando = acao.comando
        return respostas

    async def _executar(
        self, conversa: Conversa, comando: ComandoConversa, agora: datetime
    ) -> AcaoConversa:
        match comando:
            case BuscarPaciente(documento=documento):
                identificado = await self._identificar_paciente.executar(
                    IdentificarPacienteCommand(documento=documento, wa_id=conversa.wa_id)
                )
                if identificado is None:
                    return conversa.paciente_nao_encontrado()
                return conversa.paciente_encontrado(
                    paciente_id=identificado.paciente_id,
                    nome_paciente=identificado.primeiro_nome,
                    consulta_futura=identificado.consulta_futura,
                )
            case CadastrarPaciente():
                cadastrado = await self._cadastrar_paciente.executar(
                    CadastrarPacienteCommand(
                        documento=comando.documento,
                        nome=comando.nome,
                        data_nascimento=comando.data_nascimento,
                        responsavel=comando.responsavel,
                        wa_id=conversa.wa_id,
                    )
                )
                return conversa.cadastro_concluido(
                    paciente_id=cadastrado.paciente_id,
                    nome_paciente=cadastrado.primeiro_nome,
                    numero_prontuario=cadastrado.numero_prontuario,
                )
            case ClassificarQueixa(paciente_id=paciente_id, texto=texto):
                queixa = await self._registrar_queixa.executar(
                    RegistrarQueixaCommand(paciente_id=paciente_id, texto=texto)
                )
                return conversa.queixa_registrada(queixa_id=queixa.id, prioridade=queixa.prioridade)
            case InterpretarDataHora(texto=texto):
                preferencia = await self._interpretar(texto, agora)
                if preferencia is None:
                    return conversa.data_hora_nao_entendida(agora, self._regras)
                agenda = await self._agenda(agora, preferencia)
                return self._aplicar(conversa, agenda.resolver(preferencia, agora), agora)
            case OferecerPrimeiroHorario():
                agenda = await self._agenda(agora)
                return self._aplicar(conversa, agenda.primeiro_livre(agora), agora)
            case AgendarHorario():
                return await self._agendar(conversa, comando, agora)

    async def _agendar(
        self, conversa: Conversa, comando: AgendarHorario, agora: datetime
    ) -> AcaoConversa:
        try:
            consulta = await self._agendar_consulta.executar(
                AgendarConsultaCommand(
                    paciente_id=comando.paciente_id,
                    inicio=comando.inicio,
                    origem=OrigemAgendamento.WHATSAPP,
                    queixa_id=comando.queixa_id,
                    prioridade=comando.prioridade,
                )
            )
        except HorarioIndisponivelError as erro:
            # Alguém ocupou o horário no meio-tempo (ou a antecedência venceu): sugerir outro.
            logger.info("horário ficou indisponível", extra={"motivo": erro.motivo.value})
            agenda = await self._agenda(agora)
            return self._aplicar(conversa, agenda.alternativa_para(comando.inicio, agora), agora)
        return conversa.consulta_agendada(
            consulta_id=consulta.id, inicio=consulta.inicio, momento=agora
        )

    async def _interpretar(self, texto: str, agora: datetime) -> PreferenciaHorario | None:
        preferencia = self._interpretador.interpretar(texto, agora)
        if preferencia is not None or self._interpretador_ia is None:
            return preferencia
        try:
            return await self._interpretador_ia.interpretar(texto, agora)
        except FalhaIntegracaoError:
            logger.warning("falha na interpretação de data por IA")
            return None

    async def _agenda(
        self, agora: datetime, preferencia: PreferenciaHorario | None = None
    ) -> Agenda:
        referencia = agora
        if preferencia is not None and preferencia.data is not None:
            dia_pedido = datetime.combine(
                preferencia.data, agora.timetz(), tzinfo=self._configuracao_agenda.fuso
            )
            referencia = max(agora, dia_pedido)
        return await montar_agenda(
            self._uow,
            self._configuracao_agenda,
            agora - timedelta(days=1),
            janela_de_busca(self._configuracao_agenda, referencia),
        )

    def _aplicar(
        self, conversa: Conversa, resultado: ResultadoBusca, agora: datetime
    ) -> AcaoConversa:
        match resultado:
            case HorarioDisponivel(inicio=inicio):
                return conversa.horario_disponivel(inicio)
            case HorarioSugerido(inicio=inicio, motivo=motivo):
                return conversa.horario_sugerido(inicio, motivo=motivo, regras=self._regras)
            case SemHorarioLivre():
                return conversa.sem_horario_disponivel(agora)

    # --- Respostas -------------------------------------------------------------------------

    async def _responder(self, conversa: Conversa, respostas: Sequence[MensagemAoPaciente]) -> int:
        if not respostas:
            return 0
        if not conversa.janela_atendimento().aberta_em(self._relogio.agora()):
            logger.warning(
                "janela de 24h fechada; respostas não enviadas",
                extra={"wa_final": conversa.wa_id.final},
            )
            return 0
        enviadas: list[Mensagem] = []
        for resposta in respostas:
            texto = self._renderizador.renderizar(resposta)
            wa_message_id = await self._enviar(conversa.wa_id, texto, resposta)
            if wa_message_id is not None:
                enviadas.append(
                    Mensagem.enviada(
                        wa_id=conversa.wa_id,
                        texto=texto,
                        wa_message_id=wa_message_id,
                        momento=self._relogio.agora(),
                    )
                )
        if enviadas:
            async with self._uow as uow:
                for mensagem in enviadas:
                    await uow.mensagens.adicionar(mensagem)
                await uow.commit()
        return len(enviadas)

    async def _enviar(self, wa_id: WaId, texto: str, resposta: MensagemAoPaciente) -> str | None:
        try:
            return await self._enviador.enviar_texto(wa_id, texto)
        except FalhaIntegracaoError:
            logger.exception(
                "falha ao enviar resposta ao paciente",
                extra={"wa_final": wa_id.final, "chave": resposta.chave.value},
            )
            return None
