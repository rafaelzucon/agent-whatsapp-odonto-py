"""Exceções da camada de aplicação (as regras de negócio usam as de ``odonto.dominio.excecoes``)."""

from uuid import UUID


class ErroAplicacao(Exception):
    """Base das exceções da aplicação."""


class FalhaIntegracaoError(ErroAplicacao):
    """Um serviço externo falhou: rede, timeout, erro da API ou resposta em formato inválido.

    Os adaptadores de saída convertem os erros dos SDKs nesta exceção; os casos de uso decidem
    o plano B (palavra-chave, pedir texto, registrar no log).
    """


class RecursoNaoEncontradoError(ErroAplicacao):
    """O recurso pedido (paciente, consulta, queixa, bloqueio...) não existe."""

    def __init__(self, recurso: str, identificador: UUID | str) -> None:
        super().__init__(f"{recurso} não encontrado(a): {identificador}.")
        self.recurso = recurso
        self.identificador = identificador


class ConfiguracaoInvalidaError(ErroAplicacao):
    """Configuração ou dado de referência ausente (ex.: catálogo sem "Avaliação geral")."""
