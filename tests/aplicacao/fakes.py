"""Fakes em memória das portas de saída e um "mini-container" para os testes da aplicação.

Os repositórios guardam cópias profundas (como um banco faria) e a unidade de trabalho
trabalha sobre uma cópia do estado: sem ``commit``, nada é gravado.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from odonto.aplicacao.casos_de_uso.agendar_consulta_service import AgendarConsultaService
from odonto.aplicacao.casos_de_uso.cadastrar_paciente_service import CadastrarPacienteService
from odonto.aplicacao.casos_de_uso.conduzir_conversa_service import ConduzirConversaService
from odonto.aplicacao.casos_de_uso.identificar_paciente_service import IdentificarPacienteService
from odonto.aplicacao.casos_de_uso.notificar_consultorio_service import (
    NotificarConsultorioService,
)
from odonto.aplicacao.casos_de_uso.receber_mensagens_service import ReceberMensagensService
from odonto.aplicacao.casos_de_uso.registrar_queixa_service import RegistrarQueixaService
from odonto.aplicacao.casos_de_uso.transcrever_audio_service import TranscreverAudioService
from odonto.aplicacao.configuracao import (
    ConfiguracaoAgenda,
    ConfiguracaoClassificacao,
    ConfiguracaoConversa,
    ConfiguracaoNotificacao,
    ConfiguracaoRecebimento,
    MensagensConversa,
)
from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.mensagens import RenderizadorMensagens
from odonto.aplicacao.portas.entrada.conversa import (
    MensagemRecebidaCommand,
    ProcessarMensagemCommand,
    ResultadoConducao,
)
from odonto.aplicacao.portas.entrada.pacientes import CadastrarPacienteCommand
from odonto.aplicacao.portas.saida.fila import ItemProcessarMensagem
from odonto.aplicacao.portas.saida.ia import ClassificacaoIA
from odonto.aplicacao.portas.saida.notificacao import AlertaConsultorio, AvisoNovoAgendamento
from odonto.aplicacao.portas.saida.whatsapp import MidiaBaixada
from odonto.dominio.excecoes import HorarioIndisponivelError, MotivoIndisponibilidade
from odonto.dominio.modelo.agregado import AgregadoRaiz
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import Conversa
from odonto.dominio.modelo.enums import (
    DirecaoMensagem,
    OrigemAgendamento,
    Prioridade,
    TipoMensagem,
)
from odonto.dominio.modelo.eventos import EventoDominio
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.prontuario import Prontuario
from odonto.dominio.modelo.valores import (
    DocumentoRg,
    Horario,
    NumeroProntuario,
    PreferenciaHorario,
    WaId,
)
from tests.apoio import AGORA, CATALOGO_TESTE, FUSO, NASCIMENTO_ADULTO, RG, WA_ID, funcionamento


def _copia[T](objeto: T) -> T:
    copia = copy.deepcopy(objeto)
    if isinstance(copia, AgregadoRaiz):
        copia.coletar_eventos()
    return copia


@dataclass
class EstadoBanco:
    pacientes: dict[UUID, Paciente] = field(default_factory=dict)
    hashes: dict[str, UUID] = field(default_factory=dict)
    prontuarios: dict[UUID, Prontuario] = field(default_factory=dict)
    catalogo: list[ProblemaOdontologico] = field(default_factory=lambda: list(CATALOGO_TESTE))
    consultas: dict[UUID, Consulta] = field(default_factory=dict)
    bloqueios: dict[UUID, BloqueioAgenda] = field(default_factory=dict)
    conversas: dict[str, Conversa] = field(default_factory=dict)
    mensagens: dict[UUID, Mensagem] = field(default_factory=dict)
    sequencia_prontuario: int = 0


class _Repositorio:
    def __init__(self, uow: UnidadeDeTrabalhoEmMemoria) -> None:
        self._uow = uow

    @property
    def _estado(self) -> EstadoBanco:
        return self._uow.estado_de_trabalho()


class PacienteRepositorioEmMemoria(_Repositorio):
    async def buscar_por_id(self, paciente_id: UUID) -> Paciente | None:
        paciente = self._estado.pacientes.get(paciente_id)
        return _copia(paciente) if paciente else None

    async def buscar_por_hash_documento(self, hash_documento: str) -> Paciente | None:
        paciente_id = self._estado.hashes.get(hash_documento)
        return await self.buscar_por_id(paciente_id) if paciente_id else None

    async def buscar_por_telefone(self, wa_id: WaId) -> Paciente | None:
        for paciente in self._estado.pacientes.values():
            if wa_id in paciente.telefones:
                return _copia(paciente)
        return None

    async def buscar_por_ids(self, ids: Collection[UUID]) -> Sequence[Paciente]:
        return [_copia(p) for i, p in self._estado.pacientes.items() if i in ids]

    async def listar(self) -> Sequence[Paciente]:
        return [_copia(p) for p in self._estado.pacientes.values()]

    async def adicionar(self, paciente: Paciente, *, hash_documento: str) -> None:
        assert hash_documento not in self._estado.hashes, "hash de documento duplicado"
        self._estado.hashes[hash_documento] = paciente.id
        self._estado.pacientes[paciente.id] = _copia(paciente)
        self._uow.rastrear(paciente)

    async def salvar(self, paciente: Paciente) -> None:
        assert paciente.id in self._estado.pacientes
        self._estado.pacientes[paciente.id] = _copia(paciente)
        self._uow.rastrear(paciente)


class ProntuarioRepositorioEmMemoria(_Repositorio):
    async def buscar_por_paciente(self, paciente_id: UUID) -> Prontuario | None:
        for prontuario in self._estado.prontuarios.values():
            if prontuario.paciente_id == paciente_id:
                return _copia(prontuario)
        return None

    async def buscar_por_queixa(self, queixa_id: UUID) -> Prontuario | None:
        for prontuario in self._estado.prontuarios.values():
            if any(queixa.id == queixa_id for queixa in prontuario.queixas):
                return _copia(prontuario)
        return None

    async def proximo_numero(self) -> NumeroProntuario:
        # Como uma sequência do banco: não volta atrás no rollback.
        self._uow.banco.sequencia_prontuario += 1
        return NumeroProntuario(self._uow.banco.sequencia_prontuario)

    async def adicionar(self, prontuario: Prontuario) -> None:
        self._estado.prontuarios[prontuario.id] = _copia(prontuario)
        self._uow.rastrear(prontuario)

    async def salvar(self, prontuario: Prontuario) -> None:
        assert prontuario.id in self._estado.prontuarios
        self._estado.prontuarios[prontuario.id] = _copia(prontuario)
        self._uow.rastrear(prontuario)


class CatalogoEmMemoria(_Repositorio):
    async def listar(self, *, somente_ativos: bool = True) -> Sequence[ProblemaOdontologico]:
        return [p for p in self._estado.catalogo if p.ativo or not somente_ativos]

    async def buscar_por_codigo(self, codigo: str) -> ProblemaOdontologico | None:
        return next((p for p in self._estado.catalogo if p.codigo == codigo), None)


class ConsultaRepositorioEmMemoria(_Repositorio):
    async def buscar_por_id(self, consulta_id: UUID) -> Consulta | None:
        consulta = self._estado.consultas.get(consulta_id)
        return _copia(consulta) if consulta else None

    async def listar_entre(
        self, inicio: datetime, fim: datetime, *, somente_agendadas: bool = False
    ) -> Sequence[Consulta]:
        return sorted(
            (
                _copia(c)
                for c in self._estado.consultas.values()
                if inicio <= c.inicio < fim and (c.ativa or not somente_agendadas)
            ),
            key=lambda c: c.inicio,
        )

    async def proxima_agendada(self, paciente_id: UUID, a_partir: datetime) -> Consulta | None:
        futuras = [
            c
            for c in self._estado.consultas.values()
            if c.paciente_id == paciente_id and c.ativa and c.inicio >= a_partir
        ]
        return _copia(min(futuras, key=lambda c: c.inicio)) if futuras else None

    async def listar_do_paciente(self, paciente_id: UUID) -> Sequence[Consulta]:
        return sorted(
            (_copia(c) for c in self._estado.consultas.values() if c.paciente_id == paciente_id),
            key=lambda c: c.inicio,
        )

    async def adicionar(self, consulta: Consulta) -> None:
        if consulta.inicio in self._uow.banco_fake.concorrentes:
            # Simula outro paciente que agendou o mesmo horário um instante antes.
            self._uow.banco_fake.concorrentes.discard(consulta.inicio)
            outra = consulta_de_outro_paciente(consulta.horario)
            self._estado.consultas[outra.id] = outra
        if any(c.ativa and c.inicio == consulta.inicio for c in self._estado.consultas.values()):
            raise HorarioIndisponivelError(MotivoIndisponibilidade.OCUPADO, consulta.inicio)
        self._estado.consultas[consulta.id] = _copia(consulta)
        self._uow.rastrear(consulta)

    async def salvar(self, consulta: Consulta) -> None:
        self._estado.consultas[consulta.id] = _copia(consulta)
        self._uow.rastrear(consulta)


class BloqueioRepositorioEmMemoria(_Repositorio):
    async def buscar_por_id(self, bloqueio_id: UUID) -> BloqueioAgenda | None:
        bloqueio = self._estado.bloqueios.get(bloqueio_id)
        return _copia(bloqueio) if bloqueio else None

    async def listar_entre(self, inicio: datetime, fim: datetime) -> Sequence[BloqueioAgenda]:
        return sorted(
            (
                _copia(b)
                for b in self._estado.bloqueios.values()
                if b.periodo.inicio < fim and b.periodo.fim > inicio
            ),
            key=lambda b: b.periodo.inicio,
        )

    async def adicionar(self, bloqueio: BloqueioAgenda) -> None:
        self._estado.bloqueios[bloqueio.id] = _copia(bloqueio)

    async def remover(self, bloqueio_id: UUID) -> bool:
        return self._estado.bloqueios.pop(bloqueio_id, None) is not None


class ConversaRepositorioEmMemoria(_Repositorio):
    async def buscar_por_wa_id(self, wa_id: WaId) -> Conversa | None:
        conversa = self._estado.conversas.get(wa_id.valor)
        return _copia(conversa) if conversa else None

    async def salvar(self, conversa: Conversa) -> None:
        self._estado.conversas[conversa.wa_id.valor] = _copia(conversa)
        self._uow.rastrear(conversa)

    async def listar_inativas(self, ultima_interacao_antes_de: datetime) -> Sequence[Conversa]:
        return [
            _copia(c)
            for c in self._estado.conversas.values()
            if not c.encerrada and c.ultima_interacao < ultima_interacao_antes_de
        ]

    async def remover_encerradas_antes(self, limite: datetime) -> int:
        remover = [
            chave
            for chave, c in self._estado.conversas.items()
            if c.encerrada_em is not None and c.encerrada_em < limite
        ]
        for chave in remover:
            del self._estado.conversas[chave]
        return len(remover)


class MensagemRepositorioEmMemoria(_Repositorio):
    async def adicionar_se_nova(self, mensagem: Mensagem) -> bool:
        if any(m.wa_message_id == mensagem.wa_message_id for m in self._estado.mensagens.values()):
            return False
        self._estado.mensagens[mensagem.id] = _copia(mensagem)
        return True

    async def adicionar(self, mensagem: Mensagem) -> None:
        self._estado.mensagens[mensagem.id] = _copia(mensagem)

    async def buscar_por_id(self, mensagem_id: UUID) -> Mensagem | None:
        mensagem = self._estado.mensagens.get(mensagem_id)
        return _copia(mensagem) if mensagem else None

    async def salvar(self, mensagem: Mensagem) -> None:
        self._estado.mensagens[mensagem.id] = _copia(mensagem)

    async def listar_pendentes(self) -> Sequence[Mensagem]:
        return sorted(
            (_copia(m) for m in self._estado.mensagens.values() if m.pendente),
            key=lambda m: m.momento,
        )

    async def remover_anteriores_a(self, limite: datetime) -> int:
        remover = [i for i, m in self._estado.mensagens.items() if m.momento < limite]
        for i in remover:
            del self._estado.mensagens[i]
        return len(remover)


@dataclass
class BancoFake:
    estado: EstadoBanco = field(default_factory=EstadoBanco)
    concorrentes: set[datetime] = field(default_factory=set)


class PublicadorRegistrador:
    def __init__(self) -> None:
        self.eventos: list[EventoDominio] = []

    async def publicar(self, eventos: Sequence[EventoDominio]) -> None:
        self.eventos.extend(eventos)


class UnidadeDeTrabalhoEmMemoria:
    """Reentrante (o bloco aninhado participa da transação externa) e com rollback."""

    def __init__(self, banco: BancoFake, publicador: PublicadorRegistrador) -> None:
        self.banco_fake = banco
        self._publicador = publicador
        self._profundidade = 0
        self._trabalho: EstadoBanco | None = None
        self._rastreados: list[AgregadoRaiz] = []
        self.commits = 0
        self.pacientes = PacienteRepositorioEmMemoria(self)
        self.prontuarios = ProntuarioRepositorioEmMemoria(self)
        self.catalogo = CatalogoEmMemoria(self)
        self.consultas = ConsultaRepositorioEmMemoria(self)
        self.bloqueios = BloqueioRepositorioEmMemoria(self)
        self.conversas = ConversaRepositorioEmMemoria(self)
        self.mensagens = MensagemRepositorioEmMemoria(self)

    @property
    def banco(self) -> EstadoBanco:
        return self.banco_fake.estado

    def estado_de_trabalho(self) -> EstadoBanco:
        assert self._trabalho is not None, "repositório usado fora do 'async with uow'"
        return self._trabalho

    def rastrear(self, objeto: object) -> None:
        if isinstance(objeto, AgregadoRaiz) and all(o is not objeto for o in self._rastreados):
            self._rastreados.append(objeto)

    async def __aenter__(self) -> Self:
        if self._profundidade == 0:
            self._trabalho = copy.deepcopy(self.banco_fake.estado)
            self._rastreados = []
        self._profundidade += 1
        return self

    async def __aexit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastreio: TracebackType | None,
    ) -> None:
        self._profundidade -= 1
        if self._profundidade == 0:
            self._trabalho = None
            self._rastreados = []

    async def commit(self) -> None:
        if self._profundidade != 1:
            return
        sequencia = self.banco_fake.estado.sequencia_prontuario
        self.banco_fake.estado = copy.deepcopy(self.estado_de_trabalho())
        self.banco_fake.estado.sequencia_prontuario = sequencia
        self.commits += 1
        eventos = [e for agregado in self._rastreados for e in agregado.coletar_eventos()]
        self._rastreados = []
        if eventos:
            await self._publicador.publicar(eventos)

    async def rollback(self) -> None:
        if self._profundidade == 1:
            self._trabalho = copy.deepcopy(self.banco_fake.estado)
            self._rastreados = []


def consulta_de_outro_paciente(horario: Horario) -> Consulta:
    consulta = Consulta.agendar(
        paciente_id=uuid4(),
        queixa_id=None,
        horario=horario,
        prioridade=Prioridade.ROTINA,
        origem=OrigemAgendamento.RECEPCAO,
        momento=AGORA - timedelta(days=30),
    )
    consulta.coletar_eventos()
    return consulta


# --- Demais portas ----------------------------------------------------------------------------


class RelogioFixo:
    def __init__(self, momento: datetime = AGORA) -> None:
        self.momento = momento

    def agora(self) -> datetime:
        return self.momento

    def avancar(self, delta: timedelta) -> None:
        self.momento += delta


class EnviadorFalso:
    def __init__(self) -> None:
        self.textos: list[tuple[WaId, str]] = []
        self.templates: list[tuple[WaId, str, tuple[str, ...]]] = []
        self.falhar = False
        self._ids = itertools.count(1)

    async def enviar_texto(self, destino: WaId, texto: str) -> str:
        if self.falhar:
            raise FalhaIntegracaoError("WhatsApp fora do ar")
        self.textos.append((destino, texto))
        return f"wamid.enviada.{next(self._ids)}"

    async def enviar_template(
        self, destino: WaId, template: str, parametros: Sequence[str], *, idioma: str = "pt_BR"
    ) -> str:
        if self.falhar:
            raise FalhaIntegracaoError("WhatsApp fora do ar")
        self.templates.append((destino, template, tuple(parametros)))
        return f"wamid.template.{next(self._ids)}"

    @property
    def ultimo(self) -> str:
        return self.textos[-1][1]


class ClassificadorIAFalso:
    def __init__(self, resposta: ClassificacaoIA | Exception | None = None) -> None:
        self.resposta = resposta
        self.chamadas: list[str] = []

    async def classificar(
        self, texto: str, catalogo: Sequence[ProblemaOdontologico]
    ) -> ClassificacaoIA:
        self.chamadas.append(texto)
        if isinstance(self.resposta, Exception):
            raise self.resposta
        if self.resposta is None:
            raise FalhaIntegracaoError("sem resposta configurada")
        return self.resposta


class InterpretadorIAFalso:
    def __init__(self, resposta: PreferenciaHorario | None = None) -> None:
        self.resposta = resposta
        self.chamadas: list[str] = []

    async def interpretar(self, texto: str, agora: datetime) -> PreferenciaHorario | None:
        self.chamadas.append(texto)
        return self.resposta


class ProvedorMidiaFalso:
    async def baixar(self, midia_id: str) -> MidiaBaixada:
        return MidiaBaixada(conteudo=b"OggS-audio", mime_type="audio/ogg")


class TranscritorFalso:
    def __init__(self, texto: str = "") -> None:
        self.texto = texto

    async def transcrever(self, audio: bytes, mime_type: str) -> str:
        return self.texto


class CanalFalso:
    def __init__(self, nome: str = "falso", *, falhar: bool = False) -> None:
        self.nome = nome
        self.falhar = falhar
        self.avisos: list[AvisoNovoAgendamento] = []
        self.alertas: list[AlertaConsultorio] = []

    async def novo_agendamento(self, aviso: AvisoNovoAgendamento) -> None:
        if self.falhar:
            raise FalhaIntegracaoError(f"canal {self.nome} fora do ar")
        self.avisos.append(aviso)

    async def alerta(self, alerta: AlertaConsultorio) -> None:
        if self.falhar:
            raise FalhaIntegracaoError(f"canal {self.nome} fora do ar")
        self.alertas.append(alerta)


class CifradorFalso:
    def hash_busca(self, documento: DocumentoRg) -> str:
        return f"hash:{documento.chave_normalizada}"


class FilaFalsa:
    def __init__(self) -> None:
        self.itens: list[ItemProcessarMensagem] = []

    async def enfileirar(self, item: ItemProcessarMensagem) -> None:
        self.itens.append(item)


# --- Mini-container ---------------------------------------------------------------------------

CONFIG_CONVERSA = ConfiguracaoConversa(
    nome_consultorio="Consultório Sorriso", endereco="Rua das Flores, 100"
)
CONFIG_AGENDA = ConfiguracaoAgenda(funcionamento=funcionamento())


class Ambiente:
    """Monta os casos de uso com os fakes, como o container faria, e simula o paciente."""

    def __init__(
        self,
        *,
        classificacao_ia: ClassificacaoIA | Exception | None = None,
        transcricao: str | None = None,
        canais: Iterable[CanalFalso] | None = None,
        configuracao_conversa: ConfiguracaoConversa = CONFIG_CONVERSA,
        numeros_ignorados: Iterable[str] = (),
    ) -> None:
        self.banco = BancoFake()
        self.publicador = PublicadorRegistrador()
        self.uow = UnidadeDeTrabalhoEmMemoria(self.banco, self.publicador)
        self.relogio = RelogioFixo()
        self.enviador = EnviadorFalso()
        self.fila = FilaFalsa()
        self.cifrador = CifradorFalso()
        self.ia = ClassificadorIAFalso(classificacao_ia)
        self.interpretador_ia = InterpretadorIAFalso()
        self.canais = list(canais) if canais is not None else [CanalFalso()]
        self.wa_id = WA_ID
        self._ids_mensagem = itertools.count(1)

        self.receber = ReceberMensagensService(
            uow=self.uow,
            fila=self.fila,
            relogio=self.relogio,
            configuracao=ConfiguracaoRecebimento(numeros_ignorados=frozenset(numeros_ignorados)),
        )
        self.identificar = IdentificarPacienteService(
            uow=self.uow, cifrador=self.cifrador, relogio=self.relogio
        )
        self.cadastrar = CadastrarPacienteService(
            uow=self.uow, cifrador=self.cifrador, relogio=self.relogio
        )
        self.registrar_queixa = RegistrarQueixaService(
            uow=self.uow,
            relogio=self.relogio,
            classificador_ia=self.ia,
            configuracao=ConfiguracaoClassificacao(),
        )
        self.agendar = AgendarConsultaService(
            uow=self.uow, relogio=self.relogio, configuracao=CONFIG_AGENDA
        )
        self.notificar = NotificarConsultorioService(
            uow=self.uow, canais=self.canais, configuracao=ConfiguracaoNotificacao(fuso=FUSO)
        )
        self.conduzir = ConduzirConversaService(
            uow=self.uow,
            relogio=self.relogio,
            enviador=self.enviador,
            renderizador=RenderizadorMensagens(
                configuracao_conversa, MensagensConversa.padrao(), FUSO
            ),
            configuracao=configuracao_conversa,
            configuracao_agenda=CONFIG_AGENDA,
            transcrever_audio=TranscreverAudioService(
                midias=ProvedorMidiaFalso(),
                transcritor=TranscritorFalso(transcricao) if transcricao is not None else None,
            ),
            identificar_paciente=self.identificar,
            cadastrar_paciente=self.cadastrar,
            registrar_queixa=self.registrar_queixa,
            agendar_consulta=self.agendar,
            interpretador_ia=self.interpretador_ia,
        )

    async def paciente_diz(
        self,
        texto: str | None,
        *,
        tipo: TipoMensagem = TipoMensagem.TEXTO,
        midia_id: str | None = None,
        depois: timedelta = timedelta(minutes=1),
    ) -> list[ResultadoConducao]:
        """O paciente envia uma mensagem: webhook → fila → condução → eventos → consultório."""
        self.relogio.avancar(depois)
        await self.receber.executar(
            [
                MensagemRecebidaCommand(
                    wa_id=self.wa_id.valor,
                    wa_message_id=f"wamid.recebida.{next(self._ids_mensagem)}",
                    tipo=tipo,
                    texto=texto,
                    midia_id=midia_id,
                    momento=self.relogio.agora(),
                )
            ]
        )
        resultados = []
        while self.fila.itens:
            item = self.fila.itens.pop(0)
            resultados.append(
                await self.conduzir.executar(ProcessarMensagemCommand(item.mensagem_id))
            )
        await self.entregar_eventos()
        return resultados

    async def entregar_eventos(self) -> None:
        eventos, self.publicador.eventos = self.publicador.eventos, []
        for evento in eventos:
            await self.notificar.notificar(evento)

    # Consultas ao "banco" para as verificações dos testes.

    @property
    def conversa(self) -> Conversa:
        return self.banco.estado.conversas[self.wa_id.valor]

    @property
    def consultas(self) -> list[Consulta]:
        return sorted(self.banco.estado.consultas.values(), key=lambda c: c.inicio)

    def consultas_do(self, paciente_id: UUID) -> list[Consulta]:
        return [c for c in self.consultas if c.paciente_id == paciente_id]

    @property
    def pacientes(self) -> list[Paciente]:
        return list(self.banco.estado.pacientes.values())

    def prontuario_de(self, paciente_id: UUID) -> Prontuario:
        return next(
            p for p in self.banco.estado.prontuarios.values() if p.paciente_id == paciente_id
        )

    def mensagens(self, direcao: DirecaoMensagem) -> list[Mensagem]:
        return [m for m in self.banco.estado.mensagens.values() if m.direcao is direcao]

    def ocupar(self, inicio: datetime) -> None:
        """Agenda uma consulta de outro paciente diretamente no "banco"."""
        horario = Horario.com_duracao(inicio, CONFIG_AGENDA.funcionamento.duracao_consulta)
        consulta = consulta_de_outro_paciente(horario)
        self.banco.estado.consultas[consulta.id] = consulta

    def bloquear(self, inicio: datetime, fim: datetime) -> None:
        bloqueio = BloqueioAgenda.criar(inicio=inicio, fim=fim, motivo="Curso", momento=AGORA)
        self.banco.estado.bloqueios[bloqueio.id] = bloqueio

    async def cadastrar_paciente_existente(
        self, *, nome: str = "Maria da Silva", wa_id: WaId | None = None
    ) -> Paciente:
        """Cadastra (pelo caso de uso) um paciente que já existia antes da conversa."""
        cadastrado = await self.cadastrar.executar(
            CadastrarPacienteCommand(
                documento=RG,
                nome=nome,
                data_nascimento=NASCIMENTO_ADULTO,
                responsavel=None,
                wa_id=wa_id or WaId("5511900001111"),
            )
        )
        return self.banco.estado.pacientes[cadastrado.paciente_id]
