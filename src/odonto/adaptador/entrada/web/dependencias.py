"""Dependências dos routers: casos de uso (só as portas de entrada) e autenticação admin.

A raiz de composição guarda um ``CasosDeUsoWeb`` e um ``ConfiguracaoWeb`` em ``app.state``;
os routers não conhecem as implementações.
"""

import hmac
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from odonto.aplicacao.portas.entrada.agenda import AgendarConsultaUseCase, GerenciarAgendaUseCase
from odonto.aplicacao.portas.entrada.conversa import ReceberMensagensUseCase
from odonto.aplicacao.portas.entrada.pacientes import ConsultarPacientesUseCase
from odonto.aplicacao.portas.entrada.prontuario import (
    ConsultarCatalogoUseCase,
    ReclassificarQueixaUseCase,
)

CABECALHO_ADMIN = "X-Admin-Token"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoWeb:
    verify_token: str = field(repr=False)
    app_secret: str = field(repr=False)
    admin_token: str = field(repr=False)
    phone_number_id: str | None = None
    docs_habilitada: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CasosDeUsoWeb:
    receber_mensagens: ReceberMensagensUseCase
    agendar_consulta: AgendarConsultaUseCase
    gerenciar_agenda: GerenciarAgendaUseCase
    consultar_pacientes: ConsultarPacientesUseCase
    reclassificar_queixa: ReclassificarQueixaUseCase
    consultar_catalogo: ConsultarCatalogoUseCase


def obter_casos(request: Request) -> CasosDeUsoWeb:
    casos: CasosDeUsoWeb = request.app.state.casos_de_uso
    return casos


def obter_configuracao(request: Request) -> ConfiguracaoWeb:
    configuracao: ConfiguracaoWeb = request.app.state.configuracao_web
    return configuracao


type Casos = Annotated[CasosDeUsoWeb, Depends(obter_casos)]
type ConfigWeb = Annotated[ConfiguracaoWeb, Depends(obter_configuracao)]


def token_admin_valido(recebido: str | None, esperado: str) -> bool:
    """Comparação em tempo constante; sem token configurado a API fica fechada."""
    if not recebido or not esperado:
        return False
    return hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8"))


def exigir_admin(
    configuracao: ConfigWeb,
    token: Annotated[str | None, Header(alias=CABECALHO_ADMIN)] = None,
) -> None:
    if not token_admin_valido(token, configuracao.admin_token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Informe o cabeçalho {CABECALHO_ADMIN} válido.",
        )
