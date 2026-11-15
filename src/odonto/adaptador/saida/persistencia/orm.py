"""Modelos ORM (tabelas), separados das entidades de domínio. Conversão em ``mappers.py``.

Colunas ``TextoCifrado`` guardam dados pessoais e de saúde cifrados (AES-256-GCM).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from odonto.adaptador.saida.persistencia.tipos import TextoCifrado

CONVENCAO_NOMES = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
INDICE_CONSULTA_AGENDADA = "ux_consulta_inicio_agendada"
SEQUENCIA_PRONTUARIO = Sequence("prontuario_numero_seq", start=1)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO_NOMES)
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class PacienteOrm(Base):
    __tablename__ = "paciente"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    rg_hash: Mapped[str] = mapped_column(String(64), unique=True)
    rg_cifrado: Mapped[str] = mapped_column(TextoCifrado())
    nome_cifrado: Mapped[str] = mapped_column(TextoCifrado())
    data_nascimento_cifrada: Mapped[str] = mapped_column(TextoCifrado())
    responsavel_cifrado: Mapped[str | None] = mapped_column(TextoCifrado())
    consentimento_lgpd: Mapped[bool] = mapped_column(Boolean)
    consentimento_em: Mapped[datetime]
    cadastrado_em: Mapped[datetime]

    telefones: Mapped[list[PacienteTelefoneOrm]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="PacienteTelefoneOrm.vinculado_em",
    )


class PacienteTelefoneOrm(Base):
    """Um número pode ser de mais de um paciente (ex.: mãe e filho) e vice-versa."""

    __tablename__ = "paciente_telefone"
    __table_args__ = (UniqueConstraint("paciente_id", "wa_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paciente_id: Mapped[UUID] = mapped_column(
        ForeignKey("paciente.id", ondelete="CASCADE"), index=True
    )
    wa_id: Mapped[str] = mapped_column(String(15), index=True)
    vinculado_em: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ProblemaOdontologicoOrm(Base):
    __tablename__ = "problema_odontologico"

    codigo: Mapped[str] = mapped_column(String(64), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text)
    especialidade: Mapped[str] = mapped_column(String(100))
    prioridade: Mapped[str] = mapped_column(String(20))
    cid10: Mapped[str] = mapped_column(String(10))
    palavras_chave: Mapped[list[str]] = mapped_column(JSON)
    ativo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    ordem: Mapped[int] = mapped_column(Integer)


class ProntuarioOrm(Base):
    __tablename__ = "prontuario"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    paciente_id: Mapped[UUID] = mapped_column(ForeignKey("paciente.id"), unique=True)
    numero: Mapped[int] = mapped_column(Integer, SEQUENCIA_PRONTUARIO, unique=True)
    aberto_em: Mapped[datetime]

    queixas: Mapped[list[QueixaRelatadaOrm]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QueixaRelatadaOrm.registrada_em",
    )


class QueixaRelatadaOrm(Base):
    __tablename__ = "queixa_relatada"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    prontuario_id: Mapped[UUID] = mapped_column(ForeignKey("prontuario.id"), index=True)
    texto_cifrado: Mapped[str] = mapped_column(TextoCifrado())
    problema_codigo: Mapped[str] = mapped_column(ForeignKey("problema_odontologico.codigo"))
    prioridade: Mapped[str] = mapped_column(String(20))
    confianca: Mapped[float] = mapped_column(Float)
    origem: Mapped[str] = mapped_column(String(20))
    sintomas_cifrados: Mapped[str | None] = mapped_column(TextoCifrado())
    registrada_em: Mapped[datetime]
    reclassificada_em: Mapped[datetime | None]
    consulta_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consulta.id", use_alter=True, name="fk_queixa_relatada_consulta_id_consulta")
    )

    problema: Mapped[ProblemaOdontologicoOrm] = relationship(lazy="selectin")


class ConsultaOrm(Base):
    __tablename__ = "consulta"
    __table_args__ = (
        # Dois pacientes não podem agendar o mesmo início (concorrência entre conversas).
        Index(
            INDICE_CONSULTA_AGENDADA,
            "inicio",
            unique=True,
            postgresql_where=text("status = 'AGENDADA'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    paciente_id: Mapped[UUID] = mapped_column(ForeignKey("paciente.id"), index=True)
    queixa_id: Mapped[UUID | None] = mapped_column(ForeignKey("queixa_relatada.id"))
    inicio: Mapped[datetime] = mapped_column(index=True)
    fim: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20))
    prioridade: Mapped[str] = mapped_column(String(20))
    origem: Mapped[str] = mapped_column(String(20))
    agendada_em: Mapped[datetime]
    atualizada_em: Mapped[datetime]


class BloqueioAgendaOrm(Base):
    __tablename__ = "bloqueio_agenda"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    inicio: Mapped[datetime] = mapped_column(index=True)
    fim: Mapped[datetime]
    motivo: Mapped[str] = mapped_column(String(200))
    criado_em: Mapped[datetime]


class ConversaOrm(Base):
    __tablename__ = "conversa"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(15), unique=True)
    etapa: Mapped[str] = mapped_column(String(40))
    dados_cifrados: Mapped[str] = mapped_column(TextoCifrado())
    tentativas_invalidas: Mapped[int] = mapped_column(Integer)
    ultima_interacao: Mapped[datetime] = mapped_column(index=True)
    iniciada_em: Mapped[datetime]
    encerrada_em: Mapped[datetime | None]


class MensagemOrm(Base):
    __tablename__ = "mensagem"
    __table_args__ = (
        Index(
            "ix_mensagem_pendente",
            "momento",
            postgresql_where=text("direcao = 'RECEBIDA' AND processada_em IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(15), index=True)
    direcao: Mapped[str] = mapped_column(String(10))
    tipo: Mapped[str] = mapped_column(String(10))
    texto_cifrado: Mapped[str | None] = mapped_column(TextoCifrado())
    wa_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    midia_id: Mapped[str | None] = mapped_column(String(200))
    automatica: Mapped[bool] = mapped_column(Boolean)
    momento: Mapped[datetime] = mapped_column(index=True)
    criada_em: Mapped[datetime]
    processada_em: Mapped[datetime | None]
