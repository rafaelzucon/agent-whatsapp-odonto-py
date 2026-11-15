"""Schema inicial: pacientes, prontuários, queixas, catálogo, agenda, conversas e mensagens.

Colunas ``*_cifrado(s)`` são ``text`` com AES-256-GCM em Base64 (cifradas pela aplicação).

Revision ID: 0001
Revises:
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCIA_PRONTUARIO = sa.Sequence("prontuario_numero_seq", start=1)


def upgrade() -> None:
    op.create_table(
        "bloqueio_agenda",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.String(length=200), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bloqueio_agenda")),
    )
    op.create_index(op.f("ix_bloqueio_agenda_inicio"), "bloqueio_agenda", ["inicio"], unique=False)
    op.create_table(
        "conversa",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wa_id", sa.String(length=15), nullable=False),
        sa.Column("etapa", sa.String(length=40), nullable=False),
        sa.Column("dados_cifrados", sa.Text(), nullable=False),
        sa.Column("tentativas_invalidas", sa.Integer(), nullable=False),
        sa.Column("ultima_interacao", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iniciada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encerrada_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversa")),
        sa.UniqueConstraint("wa_id", name=op.f("uq_conversa_wa_id")),
    )
    op.create_index(
        op.f("ix_conversa_ultima_interacao"), "conversa", ["ultima_interacao"], unique=False
    )
    op.create_table(
        "mensagem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("wa_id", sa.String(length=15), nullable=False),
        sa.Column("direcao", sa.String(length=10), nullable=False),
        sa.Column("tipo", sa.String(length=10), nullable=False),
        sa.Column("texto_cifrado", sa.Text(), nullable=True),
        sa.Column("wa_message_id", sa.String(length=200), nullable=True),
        sa.Column("midia_id", sa.String(length=200), nullable=True),
        sa.Column("automatica", sa.Boolean(), nullable=False),
        sa.Column("momento", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processada_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mensagem")),
        sa.UniqueConstraint("wa_message_id", name=op.f("uq_mensagem_wa_message_id")),
    )
    op.create_index(op.f("ix_mensagem_momento"), "mensagem", ["momento"], unique=False)
    op.create_index(
        "ix_mensagem_pendente",
        "mensagem",
        ["momento"],
        unique=False,
        postgresql_where=sa.text("direcao = 'RECEBIDA' AND processada_em IS NULL"),
    )
    op.create_index(op.f("ix_mensagem_wa_id"), "mensagem", ["wa_id"], unique=False)
    op.create_table(
        "paciente",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rg_hash", sa.String(length=64), nullable=False),
        sa.Column("rg_cifrado", sa.Text(), nullable=False),
        sa.Column("nome_cifrado", sa.Text(), nullable=False),
        sa.Column("data_nascimento_cifrada", sa.Text(), nullable=False),
        sa.Column("responsavel_cifrado", sa.Text(), nullable=True),
        sa.Column("consentimento_lgpd", sa.Boolean(), nullable=False),
        sa.Column("consentimento_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cadastrado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paciente")),
        sa.UniqueConstraint("rg_hash", name=op.f("uq_paciente_rg_hash")),
    )
    op.create_table(
        "problema_odontologico",
        sa.Column("codigo", sa.String(length=64), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("especialidade", sa.String(length=100), nullable=False),
        sa.Column("prioridade", sa.String(length=20), nullable=False),
        sa.Column("cid10", sa.String(length=10), nullable=False),
        sa.Column("palavras_chave", sa.JSON(), nullable=False),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("codigo", name=op.f("pk_problema_odontologico")),
    )
    op.create_table(
        "paciente_telefone",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("paciente_id", sa.Uuid(), nullable=False),
        sa.Column("wa_id", sa.String(length=15), nullable=False),
        sa.Column(
            "vinculado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["paciente_id"],
            ["paciente.id"],
            name=op.f("fk_paciente_telefone_paciente_id_paciente"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paciente_telefone")),
        sa.UniqueConstraint(
            "paciente_id", "wa_id", name=op.f("uq_paciente_telefone_paciente_id_wa_id")
        ),
    )
    op.create_index(
        op.f("ix_paciente_telefone_paciente_id"), "paciente_telefone", ["paciente_id"], unique=False
    )
    op.create_index(
        op.f("ix_paciente_telefone_wa_id"), "paciente_telefone", ["wa_id"], unique=False
    )
    op.execute(sa.schema.CreateSequence(SEQUENCIA_PRONTUARIO))
    op.create_table(
        "prontuario",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paciente_id", sa.Uuid(), nullable=False),
        sa.Column(
            "numero",
            sa.Integer(),
            server_default=sa.text("nextval('prontuario_numero_seq')"),
            nullable=False,
        ),
        sa.Column("aberto_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["paciente_id"], ["paciente.id"], name=op.f("fk_prontuario_paciente_id_paciente")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prontuario")),
        sa.UniqueConstraint("numero", name=op.f("uq_prontuario_numero")),
        sa.UniqueConstraint("paciente_id", name=op.f("uq_prontuario_paciente_id")),
    )
    op.create_table(
        "queixa_relatada",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prontuario_id", sa.Uuid(), nullable=False),
        sa.Column("texto_cifrado", sa.Text(), nullable=False),
        sa.Column("problema_codigo", sa.String(length=64), nullable=False),
        sa.Column("prioridade", sa.String(length=20), nullable=False),
        sa.Column("confianca", sa.Float(), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("sintomas_cifrados", sa.Text(), nullable=True),
        sa.Column("registrada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reclassificada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consulta_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["problema_codigo"],
            ["problema_odontologico.codigo"],
            name=op.f("fk_queixa_relatada_problema_codigo_problema_odontologico"),
        ),
        sa.ForeignKeyConstraint(
            ["prontuario_id"],
            ["prontuario.id"],
            name=op.f("fk_queixa_relatada_prontuario_id_prontuario"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queixa_relatada")),
    )
    op.create_index(
        op.f("ix_queixa_relatada_prontuario_id"), "queixa_relatada", ["prontuario_id"], unique=False
    )
    op.create_table(
        "consulta",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paciente_id", sa.Uuid(), nullable=False),
        sa.Column("queixa_id", sa.Uuid(), nullable=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prioridade", sa.String(length=20), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("agendada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizada_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["paciente_id"], ["paciente.id"], name=op.f("fk_consulta_paciente_id_paciente")
        ),
        sa.ForeignKeyConstraint(
            ["queixa_id"],
            ["queixa_relatada.id"],
            name=op.f("fk_consulta_queixa_id_queixa_relatada"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consulta")),
    )
    op.create_index(op.f("ix_consulta_inicio"), "consulta", ["inicio"], unique=False)
    op.create_index(op.f("ix_consulta_paciente_id"), "consulta", ["paciente_id"], unique=False)
    op.create_index(
        "ux_consulta_inicio_agendada",
        "consulta",
        ["inicio"],
        unique=True,
        postgresql_where=sa.text("status = 'AGENDADA'"),
    )
    # Referência circular queixa ↔ consulta: a FK entra depois das duas tabelas.
    op.create_foreign_key(
        "fk_queixa_relatada_consulta_id_consulta",
        "queixa_relatada",
        "consulta",
        ["consulta_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_queixa_relatada_consulta_id_consulta", "queixa_relatada", type_="foreignkey"
    )
    op.drop_index(
        "ux_consulta_inicio_agendada",
        table_name="consulta",
        postgresql_where=sa.text("status = 'AGENDADA'"),
    )
    op.drop_index(op.f("ix_consulta_paciente_id"), table_name="consulta")
    op.drop_index(op.f("ix_consulta_inicio"), table_name="consulta")
    op.drop_table("consulta")
    op.drop_index(op.f("ix_queixa_relatada_prontuario_id"), table_name="queixa_relatada")
    op.drop_table("queixa_relatada")
    op.drop_table("prontuario")
    op.execute(sa.schema.DropSequence(SEQUENCIA_PRONTUARIO))
    op.drop_index(op.f("ix_paciente_telefone_wa_id"), table_name="paciente_telefone")
    op.drop_index(op.f("ix_paciente_telefone_paciente_id"), table_name="paciente_telefone")
    op.drop_table("paciente_telefone")
    op.drop_table("problema_odontologico")
    op.drop_table("paciente")
    op.drop_index(op.f("ix_mensagem_wa_id"), table_name="mensagem")
    op.drop_index(
        "ix_mensagem_pendente",
        table_name="mensagem",
        postgresql_where=sa.text("direcao = 'RECEBIDA' AND processada_em IS NULL"),
    )
    op.drop_index(op.f("ix_mensagem_momento"), table_name="mensagem")
    op.drop_table("mensagem")
    op.drop_index(op.f("ix_conversa_ultima_interacao"), table_name="conversa")
    op.drop_table("conversa")
    op.drop_index(op.f("ix_bloqueio_agenda_inicio"), table_name="bloqueio_agenda")
    op.drop_table("bloqueio_agenda")
