"""Consulta de pacientes e prontuários pela recepção e pelo dentista."""

from collections.abc import Sequence
from uuid import UUID

from odonto.aplicacao.casos_de_uso.gerenciar_agenda_service import resumir_consultas
from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.pacientes import ProntuarioDetalhado, ResumoPaciente
from odonto.aplicacao.portas.entrada.prontuario import QueixaResumo
from odonto.aplicacao.portas.saida.seguranca import CifradorDocumento
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.valores import DocumentoRg
from odonto.dominio.servico.texto import normalizar

MINIMO_LETRAS_BUSCA = 2


class ConsultarPacientesService:
    def __init__(self, *, uow: UnidadeDeTrabalho, cifrador: CifradorDocumento) -> None:
        self._uow = uow
        self._cifrador = cifrador

    async def buscar_por_nome(self, nome: str) -> Sequence[ResumoPaciente]:
        palavras = normalizar(nome).split()
        if sum(caractere.isalpha() for caractere in "".join(palavras)) < MINIMO_LETRAS_BUSCA:
            raise DadoInvalidoError("nome", "Informe ao menos 2 letras do nome.")
        async with self._uow as uow:
            # O nome é cifrado no banco: a busca é feita aqui, depois de decifrado.
            encontrados = [
                paciente
                for paciente in await uow.pacientes.listar()
                if all(palavra in normalizar(paciente.nome) for palavra in palavras)
            ]
            encontrados.sort(key=lambda paciente: normalizar(paciente.nome))
            return [await self._resumir(uow, paciente) for paciente in encontrados]

    async def buscar_por_documento(self, numero: str, uf: str) -> ResumoPaciente | None:
        documento = DocumentoRg.criar(numero, uf)
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_hash_documento(
                self._cifrador.hash_busca(documento)
            )
            return None if paciente is None else await self._resumir(uow, paciente)

    async def prontuario(self, paciente_id: UUID) -> ProntuarioDetalhado:
        async with self._uow as uow:
            paciente = await uow.pacientes.buscar_por_id(paciente_id)
            prontuario = await uow.prontuarios.buscar_por_paciente(paciente_id)
            if paciente is None or prontuario is None:
                raise RecursoNaoEncontradoError("Paciente", paciente_id)
            consultas = await resumir_consultas(
                uow, await uow.consultas.listar_do_paciente(paciente_id)
            )
        return ProntuarioDetalhado(
            paciente=ResumoPaciente.de(paciente, prontuario.numero),
            numero=str(prontuario.numero),
            aberto_em=prontuario.aberto_em,
            queixas=tuple(QueixaResumo.de(queixa) for queixa in prontuario.queixas),
            consultas=consultas,
        )

    @staticmethod
    async def _resumir(uow: UnidadeDeTrabalho, paciente: Paciente) -> ResumoPaciente:
        prontuario = await uow.prontuarios.buscar_por_paciente(paciente.id)
        return ResumoPaciente.de(paciente, prontuario.numero if prontuario else None)
