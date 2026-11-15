"""Portas de entrada dos pacientes: identificação, cadastro e consulta pela recepção."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, Self
from uuid import UUID

from odonto.aplicacao.portas.entrada.agenda import ConsultaResumo
from odonto.aplicacao.portas.entrada.prontuario import QueixaResumo
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.valores import DocumentoRg, NumeroProntuario, WaId


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentificarPacienteCommand:
    documento: DocumentoRg = field(repr=False)
    wa_id: WaId


@dataclass(frozen=True, slots=True, kw_only=True)
class PacienteIdentificado:
    paciente_id: UUID
    primeiro_nome: str = field(repr=False)
    consulta_futura: datetime | None


class IdentificarPacienteUseCase(Protocol):
    async def executar(self, comando: IdentificarPacienteCommand) -> PacienteIdentificado | None:
        """Busca pelo hash do RG + UF; se encontrar, vincula o número de WhatsApp ao paciente
        e informa a próxima consulta agendada. ``None`` se o RG não estiver cadastrado."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CadastrarPacienteCommand:
    documento: DocumentoRg = field(repr=False)
    nome: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    responsavel: str | None = field(repr=False)
    wa_id: WaId


@dataclass(frozen=True, slots=True, kw_only=True)
class PacienteCadastrado:
    paciente_id: UUID
    primeiro_nome: str = field(repr=False)
    numero_prontuario: NumeroProntuario


class CadastrarPacienteUseCase(Protocol):
    async def executar(self, comando: CadastrarPacienteCommand) -> PacienteCadastrado:
        """Cria ``Paciente`` e ``Prontuario`` numa única transação (com consentimento LGPD).

        Idempotente: se o RG já estiver cadastrado, só vincula o número e devolve o existente.
        Levanta ``DadoInvalidoError`` se os dados forem inválidos.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumoPaciente:
    id: UUID
    nome: str = field(repr=False)
    documento: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    responsavel: str | None = field(repr=False)
    telefones: tuple[str, ...] = field(repr=False)
    numero_prontuario: str | None
    cadastrado_em: datetime
    consentimento_em: datetime

    @classmethod
    def de(cls, paciente: Paciente, numero_prontuario: NumeroProntuario | None) -> Self:
        return cls(
            id=paciente.id,
            nome=paciente.nome,
            documento=paciente.documento.formatado,
            data_nascimento=paciente.data_nascimento,
            responsavel=paciente.responsavel,
            telefones=tuple(telefone.valor for telefone in paciente.telefones),
            numero_prontuario=str(numero_prontuario) if numero_prontuario else None,
            cadastrado_em=paciente.cadastrado_em,
            consentimento_em=paciente.consentimento_em,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProntuarioDetalhado:
    paciente: ResumoPaciente
    numero: str
    aberto_em: datetime
    queixas: tuple[QueixaResumo, ...]
    consultas: tuple[ConsultaResumo, ...]


class ConsultarPacientesUseCase(Protocol):
    async def buscar_por_nome(self, nome: str) -> Sequence[ResumoPaciente]:
        """Pacientes cujo nome contém todas as palavras informadas (sem acento e sem
        diferenciar maiúsculas). Levanta ``DadoInvalidoError`` com menos de 2 letras."""
        ...

    async def buscar_por_documento(self, numero: str, uf: str) -> ResumoPaciente | None:
        """Levanta ``DadoInvalidoError`` se o RG ou a UF forem inválidos."""
        ...

    async def prontuario(self, paciente_id: UUID) -> ProntuarioDetalhado:
        """Dados do paciente, queixas classificadas e consultas.

        Levanta ``RecursoNaoEncontradoError`` se o paciente não existir.
        """
        ...
