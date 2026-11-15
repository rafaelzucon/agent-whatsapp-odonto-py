"""Bloqueio de agenda (férias, cursos, manutenção)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid7

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.agregado import Entidade
from odonto.dominio.modelo.tempo import exigir_fuso
from odonto.dominio.modelo.valores import Horario

TAMANHO_MAXIMO_MOTIVO: Final = 200


@dataclass(slots=True, kw_only=True, eq=False)
class BloqueioAgenda(Entidade):
    id: UUID
    periodo: Horario
    motivo: str
    criado_em: datetime

    @classmethod
    def criar(
        cls,
        *,
        inicio: datetime,
        fim: datetime,
        motivo: str,
        momento: datetime,
        id: UUID | None = None,
    ) -> BloqueioAgenda:
        motivo_limpo = " ".join(motivo.split())
        if not motivo_limpo or len(motivo_limpo) > TAMANHO_MAXIMO_MOTIVO:
            raise DadoInvalidoError("motivo", "Informe o motivo do bloqueio (até 200 caracteres).")
        return cls(
            id=id or uuid7(),
            periodo=Horario(inicio, fim),
            motivo=motivo_limpo,
            criado_em=exigir_fuso(momento, "momento"),
        )

    def bloqueia(self, horario: Horario) -> bool:
        return self.periodo.sobrepoe(horario)
