"""Paciente do consultório."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final
from uuid import UUID, uuid7

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.agregado import Entidade
from odonto.dominio.modelo.tempo import exigir_fuso
from odonto.dominio.modelo.valores import (
    IDADE_MAIORIDADE,
    IDADE_MAXIMA,
    DocumentoRg,
    WaId,
    idade_em,
)

TAMANHO_MAXIMO_NOME: Final = 120


def validar_nome_completo(nome: str, campo: str) -> str:
    """Invariante de nome: pelo menos duas palavras com letras e até 120 caracteres."""
    limpo = " ".join(nome.split())
    palavras = [palavra for palavra in limpo.split(" ") if any(c.isalpha() for c in palavra)]
    if len(palavras) < 2 or len(limpo) > TAMANHO_MAXIMO_NOME:
        raise DadoInvalidoError(campo, "Informe o nome completo (nome e sobrenome).")
    return limpo


@dataclass(slots=True, kw_only=True, eq=False)
class Paciente(Entidade):
    """Paciente identificado pelo RG + UF, com consentimento LGPD registrado no cadastro."""

    id: UUID
    documento: DocumentoRg
    nome: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    responsavel: str | None = field(default=None, repr=False)
    telefones: list[WaId] = field(default_factory=list)
    consentimento_lgpd: bool = True
    consentimento_em: datetime
    cadastrado_em: datetime

    @classmethod
    def cadastrar(
        cls,
        *,
        documento: DocumentoRg,
        nome: str,
        data_nascimento: date,
        responsavel: str | None,
        wa_id: WaId,
        momento: datetime,
        id: UUID | None = None,
    ) -> Paciente:
        """Cria o paciente com o consentimento dado em ``momento``.

        Levanta ``DadoInvalidoError`` se o nome for incompleto, a data de nascimento for
        futura ou implausível, ou se faltar o responsável legal de um menor de idade.
        """
        exigir_fuso(momento, "momento")
        hoje = momento.date()
        if data_nascimento > hoje:
            raise DadoInvalidoError(
                "data_nascimento", "A data de nascimento não pode estar no futuro."
            )
        idade = idade_em(data_nascimento, hoje)
        if idade > IDADE_MAXIMA:
            raise DadoInvalidoError("data_nascimento", "Data de nascimento implausível.")
        responsavel_valido = (
            validar_nome_completo(responsavel, "responsavel") if responsavel else None
        )
        if idade < IDADE_MAIORIDADE and responsavel_valido is None:
            raise DadoInvalidoError(
                "responsavel", "Paciente menor de idade precisa de um responsável legal."
            )
        return cls(
            id=id or uuid7(),
            documento=documento,
            nome=validar_nome_completo(nome, "nome"),
            data_nascimento=data_nascimento,
            responsavel=responsavel_valido,
            telefones=[wa_id],
            consentimento_lgpd=True,
            consentimento_em=momento,
            cadastrado_em=momento,
        )

    @property
    def primeiro_nome(self) -> str:
        return self.nome.split(" ", 1)[0]

    def idade(self, hoje: date) -> int:
        return idade_em(self.data_nascimento, hoje)

    def e_menor_de_idade(self, hoje: date) -> bool:
        return self.idade(hoje) < IDADE_MAIORIDADE

    def vincular_telefone(self, wa_id: WaId) -> bool:
        """Vincula o número ao paciente. Devolve ``False`` se já estava vinculado."""
        if wa_id in self.telefones:
            return False
        self.telefones.append(wa_id)
        return True
