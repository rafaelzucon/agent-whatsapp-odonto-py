"""Carga do catálogo de problemas odontológicos (fonte única: ``dados/catalogo_problemas.yaml``).

Para mudar o catálogo depois de implantado, edite o YAML e crie uma nova migração; esta
migração é idempotente (ignora códigos já existentes) para não apagar reclassificações.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

from odonto.adaptador.saida.persistencia.catalogo_yaml import ler_catalogo

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

problema_odontologico = sa.table(
    "problema_odontologico",
    sa.column("codigo", sa.String),
    sa.column("nome", sa.String),
    sa.column("descricao", sa.Text),
    sa.column("especialidade", sa.String),
    sa.column("prioridade", sa.String),
    sa.column("cid10", sa.String),
    sa.column("palavras_chave", sa.JSON),
    sa.column("ativo", sa.Boolean),
    sa.column("ordem", sa.Integer),
)


def upgrade() -> None:
    linhas = [
        {
            "codigo": problema.codigo,
            "nome": problema.nome,
            "descricao": problema.descricao,
            "especialidade": problema.especialidade,
            "prioridade": problema.prioridade.value,
            "cid10": problema.cid10,
            # JSON como texto + CAST: funciona também no modo offline (alembic upgrade --sql).
            "palavras_chave": sa.cast(
                sa.literal(json.dumps(list(problema.palavras_chave), ensure_ascii=False), sa.Text),
                sa.JSON,
            ),
            "ativo": True,
            "ordem": posicao,
        }
        for posicao, problema in enumerate(ler_catalogo(), start=1)
    ]
    op.execute(insert(problema_odontologico).values(linhas).on_conflict_do_nothing())


def downgrade() -> None:
    codigos = [problema.codigo for problema in ler_catalogo()]
    op.execute(problema_odontologico.delete().where(problema_odontologico.c.codigo.in_(codigos)))
