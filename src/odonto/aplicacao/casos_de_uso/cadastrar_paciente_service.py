"""Cadastro do paciente novo e abertura do prontuário (uma única transação)."""

import logging

from odonto.aplicacao.portas.entrada.pacientes import CadastrarPacienteCommand, PacienteCadastrado
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.seguranca import CifradorDocumento
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.prontuario import Prontuario

logger = logging.getLogger(__name__)


class CadastrarPacienteService:
    def __init__(
        self, *, uow: UnidadeDeTrabalho, cifrador: CifradorDocumento, relogio: Relogio
    ) -> None:
        self._uow = uow
        self._cifrador = cifrador
        self._relogio = relogio

    async def executar(self, comando: CadastrarPacienteCommand) -> PacienteCadastrado:
        agora = self._relogio.agora()
        hash_documento = self._cifrador.hash_busca(comando.documento)
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_hash_documento(hash_documento)
            if paciente is not None:
                # RG cadastrado entre a busca e o consentimento: reaproveita o cadastro.
                if paciente.vincular_telefone(comando.wa_id):
                    await uow.pacientes.salvar(paciente)
            else:
                paciente = Paciente.cadastrar(
                    documento=comando.documento,
                    nome=comando.nome,
                    data_nascimento=comando.data_nascimento,
                    responsavel=comando.responsavel,
                    wa_id=comando.wa_id,
                    momento=agora,
                )
                await uow.pacientes.adicionar(paciente, hash_documento=hash_documento)
            prontuario = await uow.prontuarios.buscar_por_paciente(paciente.id)
            if prontuario is None:
                prontuario = Prontuario.abrir(
                    paciente_id=paciente.id,
                    numero=await uow.prontuarios.proximo_numero(),
                    momento=agora,
                )
                await uow.prontuarios.adicionar(prontuario)
            await uow.commit()
        logger.info(
            "paciente cadastrado",
            extra={"paciente_id": str(paciente.id), "prontuario": str(prontuario.numero)},
        )
        return PacienteCadastrado(
            paciente_id=paciente.id,
            primeiro_nome=paciente.primeiro_nome,
            numero_prontuario=prontuario.numero,
        )
