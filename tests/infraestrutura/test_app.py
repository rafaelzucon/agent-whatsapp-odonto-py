from typing import Any, cast

from fastapi.testclient import TestClient

from odonto.adaptador.entrada.web.dependencias import ConfiguracaoWeb
from odonto.adaptador.saida.fila.fila_asyncio import FilaAsyncio
from odonto.infraestrutura.app import criar_app
from odonto.infraestrutura.config import Configuracoes
from odonto.infraestrutura.container import Container
from tests.infraestrutura.conftest import FabricaConfiguracoes


class ContainerFalso:
    def __init__(self, *, banco: bool) -> None:
        self.banco = banco
        self.eventos: list[str] = []
        self.fila = FilaAsyncio()
        self.casos_web = object()
        self.configuracao_web = ConfiguracaoWeb(
            verify_token="v", app_secret="s", admin_token="a" * 16, phone_number_id=None
        )

    async def iniciar(self) -> None:
        self.eventos.append("iniciar")

    async def encerrar(self) -> None:
        self.eventos.append("encerrar")

    async def banco_disponivel(self) -> bool:
        return self.banco


def _app(cfg: Configuracoes, container: ContainerFalso) -> Any:
    return criar_app(cfg, fabrica_container=lambda _: cast("Container", container))


def test_health_e_ciclo_de_vida(configuracoes: FabricaConfiguracoes) -> None:
    container = ContainerFalso(banco=True)

    with TestClient(_app(configuracoes(None), container)) as cliente:
        resposta = cliente.get("/health")
        assert container.eventos == ["iniciar"]

    assert resposta.status_code == 200
    assert resposta.json()["banco"] == "ok"
    assert container.eventos == ["iniciar", "encerrar"]


def test_health_503_sem_banco(configuracoes: FabricaConfiguracoes) -> None:
    with TestClient(_app(configuracoes(None), ContainerFalso(banco=False))) as cliente:
        resposta = cliente.get("/health")

    assert resposta.status_code == 503
    assert resposta.json()["status"] == "erro"


def test_docs_so_quando_habilitada(configuracoes: FabricaConfiguracoes) -> None:
    fechada = configuracoes(None)
    aberta = configuracoes("api:\n  docs_habilitada: true\n")

    with TestClient(_app(fechada, ContainerFalso(banco=True))) as cliente:
        assert cliente.get("/docs").status_code == 404
    with TestClient(_app(aberta, ContainerFalso(banco=True))) as cliente:
        assert cliente.get("/docs").status_code == 401
        assert cliente.get("/docs", params={"token": "a" * 16}).status_code == 200
