"""Conversa com o paciente: a máquina de estados do atendimento pelo WhatsApp.

A conversa é um workflow de etapas fixas (previsível e auditável), não um agente autônomo.
``registrar_resposta`` interpreta a mensagem na etapa atual e devolve uma ``AcaoConversa``: as
mensagens a enviar e, quando precisa de algo de fora (banco, IA, agenda), um *comando* para o
caso de uso executar. O caso de uso executa o comando e informa o resultado por um dos métodos
de retorno (``paciente_encontrado``, ``queixa_registrada``, ``horario_sugerido``...), que
devolvem a próxima ``AcaoConversa``. Avisos ao consultório saem como eventos de domínio.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID, uuid7

from odonto.dominio.excecoes import DadoInvalidoError, TransicaoInvalidaError
from odonto.dominio.modelo.agregado import AgregadoRaiz
from odonto.dominio.modelo.enums import ChaveMensagem, EtapaConversa, MotivoSugestao, Prioridade
from odonto.dominio.modelo.eventos import (
    AtendimentoHumanoNecessario,
    ConsentimentoRecusado,
    EventoDominio,
)
from odonto.dominio.modelo.tempo import diferenca_real, exigir_fuso
from odonto.dominio.modelo.valores import (
    IDADE_MAIORIDADE,
    DocumentoRg,
    JanelaAtendimento,
    NumeroProntuario,
    WaId,
    idade_em,
)
from odonto.dominio.servico.validador_dados import ValidadorDados

MINIMO_LETRAS_QUEIXA: Final = 3
_ETAPAS_DATA_HORA: Final = (
    EtapaConversa.AGUARDANDO_DATA_HORA,
    EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO,
)
_ETAPAS_COM_CORTESIA_SILENCIOSA: Final = frozenset(
    {EtapaConversa.CONCLUIDA, EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DadosConversa:
    """O que a conversa já coletou. Os dados do cadastro são apagados assim que deixam de servir."""

    documento: DocumentoRg | None = field(default=None, repr=False)
    nome: str | None = field(default=None, repr=False)
    data_nascimento: date | None = field(default=None, repr=False)
    responsavel: str | None = field(default=None, repr=False)
    paciente_id: UUID | None = None
    nome_paciente: str | None = field(default=None, repr=False)
    numero_prontuario: NumeroProntuario | None = None
    queixa_id: UUID | None = None
    prioridade: Prioridade | None = None
    horario_sugerido: datetime | None = None
    consulta_futura: datetime | None = None
    consulta_id: UUID | None = None

    def sem_dados_de_cadastro(self) -> DadosConversa:
        return replace(self, documento=None, nome=None, data_nascimento=None, responsavel=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class MensagemAoPaciente:
    """Mensagem fixa a enviar: a chave do texto configurável e os valores dos placeholders."""

    chave: ChaveMensagem
    nome_paciente: str | None = field(default=None, repr=False)
    data_hora: datetime | None = None
    prontuario: NumeroProntuario | None = None
    etapa: EtapaConversa | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RegrasConversa:
    """Parâmetros da conversa (vêm do ``config/odonto.yaml``)."""

    expiracao: timedelta = timedelta(minutes=120)
    max_tentativas: int = 3
    confirmar_sugestao: bool = True

    def __post_init__(self) -> None:
        if self.expiracao <= timedelta(0):
            raise DadoInvalidoError("expiracao", "A expiração da conversa deve ser positiva.")
        if self.max_tentativas < 1:
            raise DadoInvalidoError("max_tentativas", "O limite de tentativas deve ser >= 1.")


# --- Comandos: o que a conversa pede ao caso de uso -----------------------------------------


@dataclass(frozen=True, slots=True)
class BuscarPaciente:
    documento: DocumentoRg = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class CadastrarPaciente:
    documento: DocumentoRg = field(repr=False)
    nome: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    responsavel: str | None = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificarQueixa:
    paciente_id: UUID
    texto: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class InterpretarDataHora:
    texto: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OferecerPrimeiroHorario:
    """Emergência: oferecer o primeiro horário livre, sem esperar a preferência do paciente."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AgendarHorario:
    paciente_id: UUID
    queixa_id: UUID | None
    inicio: datetime
    prioridade: Prioridade


type ComandoConversa = (
    BuscarPaciente
    | CadastrarPaciente
    | ClassificarQueixa
    | InterpretarDataHora
    | OferecerPrimeiroHorario
    | AgendarHorario
)


@dataclass(frozen=True, slots=True)
class AcaoConversa:
    """Próximo passo: mensagens a enviar (em ordem) e, se houver, um comando a executar."""

    mensagens: tuple[MensagemAoPaciente, ...] = ()
    comando: ComandoConversa | None = None

    @classmethod
    def responder(cls, *mensagens: MensagemAoPaciente) -> AcaoConversa:
        return cls(mensagens=mensagens)


@dataclass(slots=True, kw_only=True, eq=False)
class Conversa(AgregadoRaiz):
    """Uma conversa por número de WhatsApp, com a etapa atual e os dados coletados."""

    id: UUID
    wa_id: WaId
    etapa: EtapaConversa = EtapaConversa.AGUARDANDO_RG
    dados: DadosConversa = field(default_factory=DadosConversa)
    tentativas_invalidas: int = 0
    ultima_interacao: datetime
    iniciada_em: datetime
    encerrada_em: datetime | None = None
    _eventos: list[EventoDominio] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def iniciar(
        cls, wa_id: WaId, momento: datetime, *, id: UUID | None = None
    ) -> tuple[Conversa, AcaoConversa]:
        """Primeiro contato do número: cria a conversa e devolve as boas-vindas."""
        exigir_fuso(momento, "momento")
        conversa = cls(id=id or uuid7(), wa_id=wa_id, ultima_interacao=momento, iniciada_em=momento)
        return conversa, AcaoConversa.responder(MensagemAoPaciente(chave=ChaveMensagem.BOAS_VINDAS))

    # --- Consultas -------------------------------------------------------------------------

    @property
    def encerrada(self) -> bool:
        return self.encerrada_em is not None

    def expirou(self, momento: datetime, regras: RegrasConversa) -> bool:
        """Passou do tempo máximo sem interação (a próxima mensagem recomeça do início)."""
        return diferenca_real(momento, self.ultima_interacao) > regras.expiracao

    def janela_atendimento(self) -> JanelaAtendimento:
        return JanelaAtendimento(self.ultima_interacao)

    # --- Mensagem do paciente --------------------------------------------------------------

    def registrar_resposta(
        self,
        texto: str | None,
        *,
        recebida_em: datetime,
        agora: datetime,
        regras: RegrasConversa,
    ) -> AcaoConversa:
        """Processa a mensagem do paciente na etapa atual.

        ``texto`` é ``None`` quando a mensagem não tem texto (ex.: áudio sem transcrição).
        ``recebida_em`` marca a interação; ``agora`` serve de referência para datas.
        """
        exigir_fuso(recebida_em, "recebida_em")
        exigir_fuso(agora, "agora")
        expirada = self.expirou(recebida_em, regras)
        if not expirada and self._deve_ficar_em_silencio(texto):
            self.ultima_interacao = recebida_em
            return AcaoConversa()
        if self.encerrada or expirada:
            return self._reiniciar(recebida_em)
        self.ultima_interacao = recebida_em
        conteudo = (texto or "").strip()
        if not conteudo:
            return AcaoConversa.responder(MensagemAoPaciente(chave=ChaveMensagem.PEDIR_TEXTO))
        match self.etapa:
            case EtapaConversa.AGUARDANDO_RG:
                return self._receber_rg(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_NOME:
                return self._receber_nome(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_DATA_NASCIMENTO:
                return self._receber_data_nascimento(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_RESPONSAVEL:
                return self._receber_responsavel(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_CONSENTIMENTO:
                return self._receber_consentimento(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_DECISAO_NOVA_CONSULTA:
                return self._receber_decisao_nova_consulta(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_PROBLEMA:
                return self._receber_problema(conteudo, agora, regras)
            case EtapaConversa.AGUARDANDO_DATA_HORA:
                return AcaoConversa(comando=InterpretarDataHora(conteudo))
            case EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO:
                return self._receber_confirmacao(conteudo)
            case (
                EtapaConversa.CONCLUIDA
                | EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO
                | EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO
            ):
                return self._reiniciar(recebida_em)

    def expirar(self, momento: datetime) -> None:
        """Encerra por inatividade e descarta os dados coletados (inclusive o cadastro parcial)."""
        if self.encerrada:
            return
        self.dados = DadosConversa()
        self.encerrada_em = exigir_fuso(momento, "momento")

    # --- Retornos dos comandos -------------------------------------------------------------

    def paciente_encontrado(
        self, *, paciente_id: UUID, nome_paciente: str, consulta_futura: datetime | None
    ) -> AcaoConversa:
        """RG encontrado. Se já houver consulta futura, pergunta se quer agendar outra."""
        self._exigir_etapa(EtapaConversa.AGUARDANDO_RG)
        self.dados = DadosConversa(
            paciente_id=paciente_id, nome_paciente=nome_paciente, consulta_futura=consulta_futura
        )
        if consulta_futura is not None:
            return self._avancar(
                EtapaConversa.AGUARDANDO_DECISAO_NOVA_CONSULTA,
                self._mensagem(ChaveMensagem.CONSULTA_FUTURA, data_hora=consulta_futura),
            )
        return self._avancar(
            EtapaConversa.AGUARDANDO_PROBLEMA, self._mensagem(ChaveMensagem.PACIENTE_ENCONTRADO)
        )

    def paciente_nao_encontrado(self) -> AcaoConversa:
        """RG sem cadastro: começa o cadastro pelo nome completo."""
        self._exigir_etapa(EtapaConversa.AGUARDANDO_RG)
        if self.dados.documento is None:
            raise TransicaoInvalidaError("A busca do paciente exige o RG informado.")
        return self._avancar(
            EtapaConversa.AGUARDANDO_NOME, self._mensagem(ChaveMensagem.PEDIR_NOME)
        )

    def cadastro_concluido(
        self, *, paciente_id: UUID, nome_paciente: str, numero_prontuario: NumeroProntuario
    ) -> AcaoConversa:
        """Paciente e prontuário criados: apaga os dados do cadastro e pede o problema."""
        self._exigir_etapa(EtapaConversa.AGUARDANDO_CONSENTIMENTO)
        self.dados = DadosConversa(
            paciente_id=paciente_id,
            nome_paciente=nome_paciente,
            numero_prontuario=numero_prontuario,
        )
        return self._avancar(
            EtapaConversa.AGUARDANDO_PROBLEMA,
            self._mensagem(ChaveMensagem.CADASTRO_CONCLUIDO, prontuario=numero_prontuario),
        )

    def queixa_registrada(self, *, queixa_id: UUID, prioridade: Prioridade) -> AcaoConversa:
        """Queixa no prontuário. Em emergência, avisa o paciente e oferece o 1º horário livre."""
        self._exigir_etapa(EtapaConversa.AGUARDANDO_PROBLEMA)
        self.dados = replace(
            self.dados, queixa_id=queixa_id, prioridade=prioridade, horario_sugerido=None
        )
        if prioridade is Prioridade.EMERGENCIA:
            acao = self._avancar(
                EtapaConversa.AGUARDANDO_DATA_HORA, self._mensagem(ChaveMensagem.EMERGENCIA)
            )
            return replace(acao, comando=OferecerPrimeiroHorario())
        return self._avancar(
            EtapaConversa.AGUARDANDO_DATA_HORA, self._mensagem(ChaveMensagem.PEDIR_DATA_HORA)
        )

    def horario_disponivel(self, inicio: datetime) -> AcaoConversa:
        """O horário pedido está livre: agendar."""
        self._exigir_etapa(*_ETAPAS_DATA_HORA)
        return AcaoConversa(comando=self._comando_agendar(inicio))

    def horario_sugerido(
        self, inicio: datetime, *, motivo: MotivoSugestao, regras: RegrasConversa
    ) -> AcaoConversa:
        """Sugere um horário e espera a confirmação, ou agenda direto se a regra permitir.

        A oferta do primeiro horário livre (emergência) sempre pede confirmação.
        """
        self._exigir_etapa(*_ETAPAS_DATA_HORA)
        if not regras.confirmar_sugestao and motivo is not MotivoSugestao.PRIMEIRO_LIVRE:
            return AcaoConversa(comando=self._comando_agendar(inicio))
        self.dados = replace(self.dados, horario_sugerido=inicio)
        chave = (
            ChaveMensagem.HORARIO_INDISPONIVEL
            if motivo is MotivoSugestao.HORARIO_INDISPONIVEL
            else ChaveMensagem.SUGESTAO_HORARIO
        )
        return self._avancar(
            EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO, self._mensagem(chave, data_hora=inicio)
        )

    def data_hora_nao_entendida(self, momento: datetime, regras: RegrasConversa) -> AcaoConversa:
        """Nem o parser nem a IA entenderam a data: conta como resposta inválida."""
        self._exigir_etapa(*_ETAPAS_DATA_HORA)
        return self._resposta_invalida(momento, regras)

    def sem_horario_disponivel(self, momento: datetime) -> AcaoConversa:
        """Agenda cheia no período de busca: encaminha para a equipe."""
        self._exigir_etapa(*_ETAPAS_DATA_HORA)
        return self._encaminhar_atendimento_humano(
            "Sem horário livre no período de busca da agenda.", ChaveMensagem.SEM_HORARIO, momento
        )

    def encaminhar_para_equipe(self, motivo: str, momento: datetime) -> AcaoConversa:
        """Falha inesperada ao executar um comando: a equipe assume o atendimento."""
        if self.encerrada:
            raise TransicaoInvalidaError("A conversa já foi encerrada.")
        return self._encaminhar_atendimento_humano(
            motivo, ChaveMensagem.ATENDIMENTO_HUMANO, momento
        )

    def consulta_agendada(
        self, *, consulta_id: UUID, inicio: datetime, momento: datetime
    ) -> AcaoConversa:
        """Consulta gravada: confirma ao paciente e encerra a conversa."""
        self._exigir_etapa(*_ETAPAS_DATA_HORA)
        self.dados = replace(self.dados, consulta_id=consulta_id, horario_sugerido=None)
        self._encerrar(EtapaConversa.CONCLUIDA, momento)
        return AcaoConversa.responder(self._mensagem(ChaveMensagem.AGENDADO, data_hora=inicio))

    # --- Etapas ----------------------------------------------------------------------------

    def _receber_rg(self, texto: str, agora: datetime, regras: RegrasConversa) -> AcaoConversa:
        try:
            documento = ValidadorDados.rg(texto)
        except DadoInvalidoError:
            return self._resposta_invalida(agora, regras)
        self.dados = replace(self.dados, documento=documento)
        return AcaoConversa(comando=BuscarPaciente(documento))

    def _receber_nome(self, texto: str, agora: datetime, regras: RegrasConversa) -> AcaoConversa:
        try:
            nome = ValidadorDados.nome_completo(texto)
        except DadoInvalidoError:
            return self._resposta_invalida(agora, regras)
        self.dados = replace(self.dados, nome=nome)
        return self._avancar(
            EtapaConversa.AGUARDANDO_DATA_NASCIMENTO,
            self._mensagem(ChaveMensagem.PEDIR_DATA_NASCIMENTO),
        )

    def _receber_data_nascimento(
        self, texto: str, agora: datetime, regras: RegrasConversa
    ) -> AcaoConversa:
        hoje = agora.date()
        try:
            nascimento = ValidadorDados.data_nascimento(texto, hoje)
        except DadoInvalidoError:
            return self._resposta_invalida(agora, regras)
        self.dados = replace(self.dados, data_nascimento=nascimento)
        if idade_em(nascimento, hoje) < IDADE_MAIORIDADE:
            return self._avancar(
                EtapaConversa.AGUARDANDO_RESPONSAVEL,
                self._mensagem(ChaveMensagem.PEDIR_RESPONSAVEL),
            )
        return self._pedir_consentimento()

    def _receber_responsavel(
        self, texto: str, agora: datetime, regras: RegrasConversa
    ) -> AcaoConversa:
        try:
            responsavel = ValidadorDados.nome_completo(texto, "responsavel")
        except DadoInvalidoError:
            return self._resposta_invalida(agora, regras)
        self.dados = replace(self.dados, responsavel=responsavel)
        return self._pedir_consentimento()

    def _pedir_consentimento(self) -> AcaoConversa:
        return self._avancar(
            EtapaConversa.AGUARDANDO_CONSENTIMENTO,
            self._mensagem(ChaveMensagem.PEDIR_CONSENTIMENTO),
        )

    def _receber_consentimento(
        self, texto: str, agora: datetime, regras: RegrasConversa
    ) -> AcaoConversa:
        match ValidadorDados.sim_nao(texto):
            case True:
                dados = self.dados
                if dados.documento is None or dados.nome is None or dados.data_nascimento is None:
                    raise TransicaoInvalidaError("Cadastro incompleto na etapa de consentimento.")
                return AcaoConversa(
                    comando=CadastrarPaciente(
                        documento=dados.documento,
                        nome=dados.nome,
                        data_nascimento=dados.data_nascimento,
                        responsavel=dados.responsavel,
                    )
                )
            case False:
                self.dados = DadosConversa()
                self.registrar_evento(ConsentimentoRecusado(wa_id=self.wa_id, ocorrido_em=agora))
                self._encerrar(EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO, agora)
                return AcaoConversa.responder(self._mensagem(ChaveMensagem.SEM_CONSENTIMENTO))
            case None:
                return self._resposta_invalida(agora, regras)

    def _receber_decisao_nova_consulta(
        self, texto: str, agora: datetime, regras: RegrasConversa
    ) -> AcaoConversa:
        match ValidadorDados.sim_nao(texto):
            case True:
                return self._avancar(
                    EtapaConversa.AGUARDANDO_PROBLEMA, self._mensagem(ChaveMensagem.PEDIR_PROBLEMA)
                )
            case False:
                consulta_futura = self.dados.consulta_futura
                self._encerrar(EtapaConversa.CONCLUIDA, agora)
                return AcaoConversa.responder(
                    self._mensagem(ChaveMensagem.NOVA_CONSULTA_RECUSADA, data_hora=consulta_futura)
                )
            case None:
                return self._resposta_invalida(agora, regras)

    def _receber_problema(
        self, texto: str, agora: datetime, regras: RegrasConversa
    ) -> AcaoConversa:
        if sum(caractere.isalpha() for caractere in texto) < MINIMO_LETRAS_QUEIXA:
            return self._resposta_invalida(agora, regras)
        return AcaoConversa(
            comando=ClassificarQueixa(paciente_id=self._exigir_paciente(), texto=texto)
        )

    def _receber_confirmacao(self, texto: str) -> AcaoConversa:
        match ValidadorDados.sim_nao(texto):
            case True if self.dados.horario_sugerido is not None:
                return AcaoConversa(comando=self._comando_agendar(self.dados.horario_sugerido))
            case True | False:
                self.dados = replace(self.dados, horario_sugerido=None)
                return self._avancar(
                    EtapaConversa.AGUARDANDO_DATA_HORA,
                    self._mensagem(ChaveMensagem.PEDIR_DATA_HORA),
                )
            case None:
                return AcaoConversa(comando=InterpretarDataHora(texto))

    # --- Apoio -----------------------------------------------------------------------------

    def _deve_ficar_em_silencio(self, texto: str | None) -> bool:
        """Não interrompe o atendimento humano nem responde a um "obrigado" depois do fim."""
        if self.etapa is EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO:
            return True
        return (
            self.etapa in _ETAPAS_COM_CORTESIA_SILENCIOSA
            and texto is not None
            and ValidadorDados.e_cortesia(texto)
        )

    def _resposta_invalida(self, momento: datetime, regras: RegrasConversa) -> AcaoConversa:
        self.tentativas_invalidas += 1
        if self.tentativas_invalidas >= regras.max_tentativas:
            return self._encaminhar_atendimento_humano(
                f"{self.tentativas_invalidas} respostas inválidas na etapa {self.etapa.value}.",
                ChaveMensagem.ATENDIMENTO_HUMANO,
                momento,
            )
        return AcaoConversa.responder(self._mensagem(ChaveMensagem.NAO_ENTENDI, etapa=self.etapa))

    def _encaminhar_atendimento_humano(
        self, motivo: str, chave: ChaveMensagem, momento: datetime
    ) -> AcaoConversa:
        self.registrar_evento(
            AtendimentoHumanoNecessario(
                wa_id=self.wa_id,
                paciente_id=self.dados.paciente_id,
                motivo=motivo,
                etapa=self.etapa,
                prioridade=self.dados.prioridade,
                ocorrido_em=momento,
            )
        )
        self.dados = self.dados.sem_dados_de_cadastro()
        self._encerrar(EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO, momento)
        return AcaoConversa.responder(self._mensagem(chave))

    def _mensagem(
        self,
        chave: ChaveMensagem,
        *,
        data_hora: datetime | None = None,
        prontuario: NumeroProntuario | None = None,
        etapa: EtapaConversa | None = None,
    ) -> MensagemAoPaciente:
        return MensagemAoPaciente(
            chave=chave,
            nome_paciente=self.dados.nome_paciente,
            data_hora=data_hora,
            prontuario=prontuario,
            etapa=etapa,
        )

    def _avancar(self, etapa: EtapaConversa, *mensagens: MensagemAoPaciente) -> AcaoConversa:
        if etapa is not self.etapa:
            self.tentativas_invalidas = 0
        self.etapa = etapa
        return AcaoConversa(mensagens=mensagens)

    def _encerrar(self, etapa: EtapaConversa, momento: datetime) -> None:
        self._avancar(etapa)
        self.encerrada_em = exigir_fuso(momento, "momento")

    def _reiniciar(self, momento: datetime) -> AcaoConversa:
        self.etapa = EtapaConversa.AGUARDANDO_RG
        self.dados = DadosConversa()
        self.tentativas_invalidas = 0
        self.iniciada_em = momento
        self.ultima_interacao = momento
        self.encerrada_em = None
        return AcaoConversa.responder(MensagemAoPaciente(chave=ChaveMensagem.BOAS_VINDAS))

    def _exigir_etapa(self, *etapas: EtapaConversa) -> None:
        if self.etapa not in etapas:
            esperadas = ", ".join(etapa.value for etapa in etapas)
            raise TransicaoInvalidaError(
                f"Conversa na etapa {self.etapa.value}; esperado: {esperadas}."
            )

    def _exigir_paciente(self) -> UUID:
        if self.dados.paciente_id is None:
            raise TransicaoInvalidaError("A conversa ainda não identificou o paciente.")
        return self.dados.paciente_id

    def _comando_agendar(self, inicio: datetime) -> AgendarHorario:
        return AgendarHorario(
            paciente_id=self._exigir_paciente(),
            queixa_id=self.dados.queixa_id,
            inicio=exigir_fuso(inicio, "inicio"),
            prioridade=self.dados.prioridade or Prioridade.ROTINA,
        )
