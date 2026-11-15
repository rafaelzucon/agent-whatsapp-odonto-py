"""Identificação do paciente pelo RG + UF."""

from odonto.aplicacao.portas.entrada.pacientes import (
    IdentificarPacienteCommand,
    PacienteIdentificado,
)
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.seguranca import CifradorDocumento
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho


class IdentificarPacienteService:
    def __init__(
        self, *, uow: UnidadeDeTrabalho, cifrador: CifradorDocumento, relogio: Relogio
    ) -> None:
        self._uow = uow
        self._cifrador = cifrador
        self._relogio = relogio

    async def executar(self, comando: IdentificarPacienteCommand) -> PacienteIdentificado | None:
        agora = self._relogio.agora()
        hash_documento = self._cifrador.hash_busca(comando.documento)
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_hash_documento(hash_documento)
            if paciente is None:
                return None
            if paciente.vincular_telefone(comando.wa_id):
                await uow.pacientes.salvar(paciente)
            proxima = await uow.consultas.proxima_agendada(paciente.id, agora)
            await uow.commit()
        return PacienteIdentificado(
            paciente_id=paciente.id,
            primeiro_nome=paciente.primeiro_nome,
            consulta_futura=proxima.inicio if proxima else None,
        )
