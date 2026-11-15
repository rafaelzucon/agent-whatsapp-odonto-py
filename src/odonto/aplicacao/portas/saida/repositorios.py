"""Repositórios: um por agregado, todos assíncronos e usados dentro de uma ``UnidadeDeTrabalho``.

Contrato comum (vale para os adaptadores reais e para os fakes dos testes):

- Cada busca devolve objetos de domínio novos; alterações só são gravadas com ``adicionar`` ou
  ``salvar`` seguido do ``commit`` da unidade de trabalho.
- Buscas devolvem ``None`` (ou sequência vazia) quando não encontram; nunca levantam por isso.
- Os dados pessoais são cifrados e decifrados pelo adaptador, de forma transparente.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import Conversa
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.prontuario import Prontuario
from odonto.dominio.modelo.valores import NumeroProntuario, WaId


class PacienteRepositorio(Protocol):
    async def buscar_por_id(self, paciente_id: UUID) -> Paciente | None: ...

    async def buscar_por_hash_documento(self, hash_documento: str) -> Paciente | None:
        """Busca pelo HMAC do RG + UF (ver ``CifradorDocumento``)."""
        ...

    async def buscar_por_telefone(self, wa_id: WaId) -> Paciente | None: ...

    async def buscar_por_ids(self, ids: Collection[UUID]) -> Sequence[Paciente]:
        """Pacientes com os ids informados (os inexistentes são omitidos)."""
        ...

    async def listar(self) -> Sequence[Paciente]:
        """Todos os pacientes (os nomes são cifrados no banco; a busca por nome é feita em
        memória pelo caso de uso)."""
        ...

    async def adicionar(self, paciente: Paciente, *, hash_documento: str) -> None:
        """Grava um paciente novo com o hash de busca do RG (índice único)."""
        ...

    async def salvar(self, paciente: Paciente) -> None:
        """Grava as alterações de um paciente existente (ex.: telefone vinculado)."""
        ...


class ProntuarioRepositorio(Protocol):
    async def buscar_por_paciente(self, paciente_id: UUID) -> Prontuario | None: ...

    async def buscar_por_queixa(self, queixa_id: UUID) -> Prontuario | None: ...

    async def proximo_numero(self) -> NumeroProntuario:
        """Próximo número sequencial (sequência do banco; números nunca se repetem)."""
        ...

    async def adicionar(self, prontuario: Prontuario) -> None: ...

    async def salvar(self, prontuario: Prontuario) -> None:
        """Grava as alterações, inclusive queixas novas ou reclassificadas."""
        ...


class CatalogoProblemasRepositorio(Protocol):
    async def listar(self, *, somente_ativos: bool = True) -> Sequence[ProblemaOdontologico]:
        """Itens do catálogo na ordem de cadastro."""
        ...

    async def buscar_por_codigo(self, codigo: str) -> ProblemaOdontologico | None: ...


class ConsultaRepositorio(Protocol):
    async def buscar_por_id(self, consulta_id: UUID) -> Consulta | None: ...

    async def listar_entre(
        self, inicio: datetime, fim: datetime, *, somente_agendadas: bool = False
    ) -> Sequence[Consulta]:
        """Consultas que começam em ``[inicio, fim)``, em ordem de início."""
        ...

    async def proxima_agendada(self, paciente_id: UUID, a_partir: datetime) -> Consulta | None:
        """Próxima consulta AGENDADA do paciente que começa a partir de ``a_partir``."""
        ...

    async def listar_do_paciente(self, paciente_id: UUID) -> Sequence[Consulta]: ...

    async def adicionar(self, consulta: Consulta) -> None:
        """Grava a consulta nova.

        Levanta ``HorarioIndisponivelError(OCUPADO)`` se outra consulta AGENDADA já começa no
        mesmo instante (índice único: dois pacientes agendando ao mesmo tempo). A transação
        continua utilizável depois do erro.
        """
        ...

    async def salvar(self, consulta: Consulta) -> None: ...


class BloqueioAgendaRepositorio(Protocol):
    async def buscar_por_id(self, bloqueio_id: UUID) -> BloqueioAgenda | None: ...

    async def listar_entre(self, inicio: datetime, fim: datetime) -> Sequence[BloqueioAgenda]:
        """Bloqueios que se sobrepõem a ``[inicio, fim)``, em ordem de início."""
        ...

    async def adicionar(self, bloqueio: BloqueioAgenda) -> None: ...

    async def remover(self, bloqueio_id: UUID) -> bool:
        """Remove o bloqueio. Devolve ``False`` se ele não existia."""
        ...


class ConversaRepositorio(Protocol):
    async def buscar_por_wa_id(self, wa_id: WaId) -> Conversa | None: ...

    async def salvar(self, conversa: Conversa) -> None:
        """Grava a conversa (nova ou existente). Há no máximo uma conversa por número."""
        ...

    async def listar_inativas(self, ultima_interacao_antes_de: datetime) -> Sequence[Conversa]:
        """Conversas ainda não encerradas sem interação desde ``ultima_interacao_antes_de``."""
        ...

    async def remover_encerradas_antes(self, limite: datetime) -> int:
        """Apaga conversas encerradas antes de ``limite``. Devolve quantas apagou."""
        ...


class MensagemRepositorio(Protocol):
    async def adicionar_se_nova(self, mensagem: Mensagem) -> bool:
        """Grava a mensagem recebida, a menos que o ``wa_message_id`` já exista (idempotência:
        a Meta reenvia o mesmo webhook). Devolve ``True`` se gravou."""
        ...

    async def adicionar(self, mensagem: Mensagem) -> None:
        """Grava uma mensagem enviada pelo agente."""
        ...

    async def buscar_por_id(self, mensagem_id: UUID) -> Mensagem | None: ...

    async def salvar(self, mensagem: Mensagem) -> None:
        """Grava a transcrição e o ``processada_em``."""
        ...

    async def listar_pendentes(self) -> Sequence[Mensagem]:
        """Mensagens recebidas ainda não processadas, da mais antiga para a mais nova."""
        ...

    async def remover_anteriores_a(self, limite: datetime) -> int:
        """Apaga mensagens (recebidas e enviadas) anteriores a ``limite``. Devolve quantas."""
        ...
