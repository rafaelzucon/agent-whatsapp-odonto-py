"""Repositórios SQLAlchemy (assíncronos). Cada método opera na sessão da transação corrente.

Os ``adicionar``/``salvar`` fazem ``flush`` imediato: a ordem das gravações fica igual à
ordem das chamadas do caso de uso (as chaves estrangeiras são respeitadas sem depender da
ordenação interna do SQLAlchemy) e erros de integridade aparecem no ponto certo.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from odonto.adaptador.saida.persistencia import mappers
from odonto.adaptador.saida.persistencia.orm import (
    INDICE_CONSULTA_AGENDADA,
    SEQUENCIA_PRONTUARIO,
    BloqueioAgendaOrm,
    ConsultaOrm,
    ConversaOrm,
    MensagemOrm,
    PacienteOrm,
    PacienteTelefoneOrm,
    ProblemaOdontologicoOrm,
    ProntuarioOrm,
    QueixaRelatadaOrm,
)
from odonto.dominio.excecoes import HorarioIndisponivelError, MotivoIndisponibilidade
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import Conversa
from odonto.dominio.modelo.enums import DirecaoMensagem, StatusConsulta
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.prontuario import Prontuario
from odonto.dominio.modelo.valores import NumeroProntuario, WaId

if TYPE_CHECKING:
    from odonto.adaptador.saida.persistencia.unidade_de_trabalho import (
        SqlAlchemyUnidadeDeTrabalho,
    )


class _Repositorio:
    __slots__ = ("_uow",)

    def __init__(self, uow: SqlAlchemyUnidadeDeTrabalho) -> None:
        self._uow = uow

    @property
    def _sessao(self) -> AsyncSession:
        return self._uow.sessao_atual()


class SqlAlchemyPacienteRepositorio(_Repositorio):
    __slots__ = ()

    async def buscar_por_id(self, paciente_id: UUID) -> Paciente | None:
        orm = await self._sessao.get(PacienteOrm, paciente_id)
        return None if orm is None else mappers.paciente_do_orm(orm)

    async def buscar_por_hash_documento(self, hash_documento: str) -> Paciente | None:
        orm = await self._sessao.scalar(
            select(PacienteOrm).where(PacienteOrm.rg_hash == hash_documento)
        )
        return None if orm is None else mappers.paciente_do_orm(orm)

    async def buscar_por_telefone(self, wa_id: WaId) -> Paciente | None:
        """Se o número é de mais de um paciente, devolve o vinculado mais recentemente."""
        orm = await self._sessao.scalar(
            select(PacienteOrm)
            .join(PacienteTelefoneOrm)
            .where(PacienteTelefoneOrm.wa_id == wa_id.valor)
            .order_by(PacienteTelefoneOrm.vinculado_em.desc(), PacienteTelefoneOrm.id.desc())
            .limit(1)
        )
        return None if orm is None else mappers.paciente_do_orm(orm)

    async def buscar_por_ids(self, ids: Collection[UUID]) -> Sequence[Paciente]:
        if not ids:
            return []
        resultado = await self._sessao.scalars(
            select(PacienteOrm).where(PacienteOrm.id.in_(list(ids)))
        )
        return [mappers.paciente_do_orm(orm) for orm in resultado]

    async def listar(self) -> Sequence[Paciente]:
        resultado = await self._sessao.scalars(
            select(PacienteOrm).order_by(PacienteOrm.cadastrado_em)
        )
        return [mappers.paciente_do_orm(orm) for orm in resultado]

    async def adicionar(self, paciente: Paciente, *, hash_documento: str) -> None:
        self._sessao.add(mappers.paciente_para_orm(paciente, rg_hash=hash_documento))
        await self._sessao.flush()

    async def salvar(self, paciente: Paciente) -> None:
        orm = await self._sessao.get(PacienteOrm, paciente.id)
        if orm is None:
            raise LookupError(f"Paciente {paciente.id} não existe; use adicionar().")
        mappers.atualizar_paciente_orm(orm, paciente)
        await self._sessao.flush()


class SqlAlchemyProntuarioRepositorio(_Repositorio):
    __slots__ = ()

    async def _buscar(self, *condicoes: object) -> Prontuario | None:
        # populate_existing: recarrega o problema das queixas reclassificadas nesta sessão.
        orm = await self._sessao.scalar(
            select(ProntuarioOrm)
            .where(*condicoes)  # type: ignore[arg-type]
            .execution_options(populate_existing=True)
        )
        return None if orm is None else mappers.prontuario_do_orm(orm)

    async def buscar_por_paciente(self, paciente_id: UUID) -> Prontuario | None:
        return await self._buscar(ProntuarioOrm.paciente_id == paciente_id)

    async def buscar_por_queixa(self, queixa_id: UUID) -> Prontuario | None:
        subconsulta = select(QueixaRelatadaOrm.prontuario_id).where(
            QueixaRelatadaOrm.id == queixa_id
        )
        return await self._buscar(ProntuarioOrm.id.in_(subconsulta.scalar_subquery()))

    async def proximo_numero(self) -> NumeroProntuario:
        sequencial = await self._sessao.scalar(select(SEQUENCIA_PRONTUARIO.next_value()))
        return NumeroProntuario(int(sequencial or 0))

    async def adicionar(self, prontuario: Prontuario) -> None:
        self._sessao.add(mappers.prontuario_para_orm(prontuario))
        await self._sessao.flush()
        self._uow.rastrear(prontuario)

    async def salvar(self, prontuario: Prontuario) -> None:
        orm = await self._sessao.get(ProntuarioOrm, prontuario.id)
        if orm is None:
            raise LookupError(f"Prontuário {prontuario.id} não existe; use adicionar().")
        mappers.atualizar_prontuario_orm(orm, prontuario)
        await self._sessao.flush()
        self._uow.rastrear(prontuario)


class SqlAlchemyCatalogoRepositorio(_Repositorio):
    __slots__ = ()

    async def listar(self, *, somente_ativos: bool = True) -> Sequence[ProblemaOdontologico]:
        consulta = select(ProblemaOdontologicoOrm).order_by(ProblemaOdontologicoOrm.ordem)
        if somente_ativos:
            consulta = consulta.where(ProblemaOdontologicoOrm.ativo.is_(True))
        return [mappers.problema_do_orm(orm) for orm in await self._sessao.scalars(consulta)]

    async def buscar_por_codigo(self, codigo: str) -> ProblemaOdontologico | None:
        orm = await self._sessao.get(ProblemaOdontologicoOrm, codigo)
        return None if orm is None else mappers.problema_do_orm(orm)


class SqlAlchemyConsultaRepositorio(_Repositorio):
    __slots__ = ()

    async def buscar_por_id(self, consulta_id: UUID) -> Consulta | None:
        orm = await self._sessao.get(ConsultaOrm, consulta_id)
        return None if orm is None else mappers.consulta_do_orm(orm)

    async def listar_entre(
        self, inicio: datetime, fim: datetime, *, somente_agendadas: bool = False
    ) -> Sequence[Consulta]:
        consulta = select(ConsultaOrm).where(ConsultaOrm.inicio >= inicio, ConsultaOrm.inicio < fim)
        if somente_agendadas:
            consulta = consulta.where(ConsultaOrm.status == StatusConsulta.AGENDADA.value)
        resultado = await self._sessao.scalars(consulta.order_by(ConsultaOrm.inicio))
        return [mappers.consulta_do_orm(orm) for orm in resultado]

    async def proxima_agendada(self, paciente_id: UUID, a_partir: datetime) -> Consulta | None:
        orm = await self._sessao.scalar(
            select(ConsultaOrm)
            .where(
                ConsultaOrm.paciente_id == paciente_id,
                ConsultaOrm.status == StatusConsulta.AGENDADA.value,
                ConsultaOrm.inicio >= a_partir,
            )
            .order_by(ConsultaOrm.inicio)
            .limit(1)
        )
        return None if orm is None else mappers.consulta_do_orm(orm)

    async def listar_do_paciente(self, paciente_id: UUID) -> Sequence[Consulta]:
        resultado = await self._sessao.scalars(
            select(ConsultaOrm)
            .where(ConsultaOrm.paciente_id == paciente_id)
            .order_by(ConsultaOrm.inicio)
        )
        return [mappers.consulta_do_orm(orm) for orm in resultado]

    async def adicionar(self, consulta: Consulta) -> None:
        # Savepoint: se o índice único recusar o horário, só esta gravação é desfeita e a
        # transação da conversa continua utilizável para oferecer o próximo horário livre.
        try:
            async with self._sessao.begin_nested():
                self._sessao.add(mappers.consulta_para_orm(consulta))
        except IntegrityError as erro:
            if _restricao_violada(erro) == INDICE_CONSULTA_AGENDADA:
                raise HorarioIndisponivelError(
                    MotivoIndisponibilidade.OCUPADO, consulta.inicio
                ) from erro
            raise
        self._uow.rastrear(consulta)

    async def salvar(self, consulta: Consulta) -> None:
        orm = await self._sessao.get(ConsultaOrm, consulta.id)
        if orm is None:
            raise LookupError(f"Consulta {consulta.id} não existe; use adicionar().")
        mappers.atualizar_consulta_orm(orm, consulta)
        await self._sessao.flush()
        self._uow.rastrear(consulta)


def _restricao_violada(erro: IntegrityError) -> str | None:
    diagnostico = getattr(erro.orig, "diag", None)
    nome = getattr(diagnostico, "constraint_name", None)
    if nome is None and INDICE_CONSULTA_AGENDADA in str(erro.orig):
        return INDICE_CONSULTA_AGENDADA
    return nome if isinstance(nome, str) else None


class SqlAlchemyBloqueioRepositorio(_Repositorio):
    __slots__ = ()

    async def buscar_por_id(self, bloqueio_id: UUID) -> BloqueioAgenda | None:
        orm = await self._sessao.get(BloqueioAgendaOrm, bloqueio_id)
        return None if orm is None else mappers.bloqueio_do_orm(orm)

    async def listar_entre(self, inicio: datetime, fim: datetime) -> Sequence[BloqueioAgenda]:
        resultado = await self._sessao.scalars(
            select(BloqueioAgendaOrm)
            .where(BloqueioAgendaOrm.inicio < fim, BloqueioAgendaOrm.fim > inicio)
            .order_by(BloqueioAgendaOrm.inicio)
        )
        return [mappers.bloqueio_do_orm(orm) for orm in resultado]

    async def adicionar(self, bloqueio: BloqueioAgenda) -> None:
        self._sessao.add(mappers.bloqueio_para_orm(bloqueio))
        await self._sessao.flush()

    async def remover(self, bloqueio_id: UUID) -> bool:
        orm = await self._sessao.get(BloqueioAgendaOrm, bloqueio_id)
        if orm is None:
            return False
        await self._sessao.delete(orm)
        await self._sessao.flush()
        return True


class SqlAlchemyConversaRepositorio(_Repositorio):
    __slots__ = ()

    async def buscar_por_wa_id(self, wa_id: WaId) -> Conversa | None:
        orm = await self._sessao.scalar(select(ConversaOrm).where(ConversaOrm.wa_id == wa_id.valor))
        return None if orm is None else mappers.conversa_do_orm(orm)

    async def salvar(self, conversa: Conversa) -> None:
        orm = await self._sessao.scalar(
            select(ConversaOrm).where(ConversaOrm.wa_id == conversa.wa_id.valor)
        )
        if orm is None:
            orm = ConversaOrm()
            self._sessao.add(orm)
        mappers.atualizar_conversa_orm(orm, conversa)
        await self._sessao.flush()
        self._uow.rastrear(conversa)

    async def listar_inativas(self, ultima_interacao_antes_de: datetime) -> Sequence[Conversa]:
        resultado = await self._sessao.scalars(
            select(ConversaOrm)
            .where(
                ConversaOrm.encerrada_em.is_(None),
                ConversaOrm.ultima_interacao < ultima_interacao_antes_de,
            )
            .order_by(ConversaOrm.ultima_interacao)
        )
        return [mappers.conversa_do_orm(orm) for orm in resultado]

    async def remover_encerradas_antes(self, limite: datetime) -> int:
        resultado = await self._sessao.execute(
            delete(ConversaOrm)
            .where(ConversaOrm.encerrada_em.is_not(None), ConversaOrm.encerrada_em < limite)
            .returning(ConversaOrm.id)
        )
        return len(resultado.all())


class SqlAlchemyMensagemRepositorio(_Repositorio):
    __slots__ = ()

    async def adicionar_se_nova(self, mensagem: Mensagem) -> bool:
        comando = (
            insert(MensagemOrm)
            .values(**mappers.mensagem_para_valores(mensagem))
            .on_conflict_do_nothing(index_elements=[MensagemOrm.wa_message_id])
            .returning(MensagemOrm.id)
        )
        return (await self._sessao.scalar(comando)) is not None

    async def adicionar(self, mensagem: Mensagem) -> None:
        self._sessao.add(mappers.mensagem_para_orm(mensagem))
        await self._sessao.flush()

    async def buscar_por_id(self, mensagem_id: UUID) -> Mensagem | None:
        orm = await self._sessao.get(MensagemOrm, mensagem_id)
        return None if orm is None else mappers.mensagem_do_orm(orm)

    async def salvar(self, mensagem: Mensagem) -> None:
        orm = await self._sessao.get(MensagemOrm, mensagem.id)
        if orm is None:
            raise LookupError(f"Mensagem {mensagem.id} não existe; use adicionar().")
        for coluna, valor in mappers.mensagem_para_valores(mensagem).items():
            setattr(orm, coluna, valor)
        await self._sessao.flush()

    async def listar_pendentes(self) -> Sequence[Mensagem]:
        resultado = await self._sessao.scalars(
            select(MensagemOrm)
            .where(
                MensagemOrm.direcao == DirecaoMensagem.RECEBIDA.value,
                MensagemOrm.processada_em.is_(None),
            )
            .order_by(MensagemOrm.momento, MensagemOrm.criada_em)
        )
        return [mappers.mensagem_do_orm(orm) for orm in resultado]

    async def remover_anteriores_a(self, limite: datetime) -> int:
        resultado = await self._sessao.execute(
            delete(MensagemOrm).where(MensagemOrm.momento < limite).returning(MensagemOrm.id)
        )
        return len(resultado.all())
