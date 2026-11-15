import asyncio
from uuid import uuid4

from odonto.adaptador.entrada.fila.consumidor import ConsumidorFila
from odonto.adaptador.saida.fila.fila_asyncio import FilaAsyncio
from odonto.aplicacao.portas.entrada.conversa import ProcessarMensagemCommand, ResultadoConducao
from odonto.aplicacao.portas.saida.fila import ItemProcessarMensagem
from odonto.dominio.modelo.enums import OrigemAgendamento, Prioridade
from odonto.dominio.modelo.eventos import ConsultaAgendada, EventoDominio
from odonto.dominio.modelo.valores import WaId
from tests.apoio import AGORA


class ConduzirLento:
    """Registra início/fim de cada mensagem para verificar ordem e paralelismo."""

    def __init__(self, falhar_em: set[object] | None = None) -> None:
        self.registro: list[tuple[str, object]] = []
        self.em_andamento = 0
        self.pico = 0
        self._falhar_em = falhar_em or set()

    async def executar(self, comando: ProcessarMensagemCommand) -> ResultadoConducao:
        self.em_andamento += 1
        self.pico = max(self.pico, self.em_andamento)
        self.registro.append(("inicio", comando.mensagem_id))
        await asyncio.sleep(0.01)
        self.registro.append(("fim", comando.mensagem_id))
        self.em_andamento -= 1
        if comando.mensagem_id in self._falhar_em:
            raise RuntimeError("falha simulada")
        return ResultadoConducao(processada=True)


class NotificarRegistrador:
    def __init__(self) -> None:
        self.eventos: list[EventoDominio] = []

    async def notificar(self, evento: EventoDominio) -> None:
        self.eventos.append(evento)


def item(numero: str) -> ItemProcessarMensagem:
    return ItemProcessarMensagem(mensagem_id=uuid4(), wa_id=WaId(numero))


async def processar(
    itens: list[object], conduzir: ConduzirLento, notificar: NotificarRegistrador, **kw: int
) -> ConsumidorFila:
    fila = FilaAsyncio()
    consumidor = ConsumidorFila(fila, conduzir, notificar, **kw)  # type: ignore[arg-type]
    consumidor.iniciar()
    for i in itens:
        if isinstance(i, ItemProcessarMensagem):
            await fila.enfileirar(i)
        else:
            await fila.publicar([i])  # type: ignore[list-item]
    await asyncio.wait_for(fila.aguardar_vazia(), timeout=5)
    await consumidor.parar()
    return consumidor


async def test_mensagens_do_mesmo_numero_sao_processadas_em_ordem_e_uma_por_vez() -> None:
    conduzir = ConduzirLento()
    itens = [item("5511900000001") for _ in range(4)]

    consumidor = await processar(itens, conduzir, NotificarRegistrador())

    esperado = [(etapa, i.mensagem_id) for i in itens for etapa in ("inicio", "fim")]
    assert conduzir.registro == esperado
    assert consumidor.numeros_em_uso == 0


async def test_numeros_diferentes_sao_processados_em_paralelo_ate_o_limite() -> None:
    conduzir = ConduzirLento()
    itens = [item(f"55119000000{n:02d}") for n in range(10)]

    await processar(itens, conduzir, NotificarRegistrador(), maximo_paralelo=3)

    assert conduzir.pico == 3
    assert len(conduzir.registro) == 20


async def test_falha_em_uma_mensagem_nao_para_o_consumidor() -> None:
    primeira, segunda = item("5511900000001"), item("5511900000001")
    conduzir = ConduzirLento(falhar_em={primeira.mensagem_id})

    await processar([primeira, segunda], conduzir, NotificarRegistrador())

    assert ("fim", segunda.mensagem_id) in conduzir.registro


async def test_eventos_de_dominio_viram_notificacao() -> None:
    notificar = NotificarRegistrador()
    evento = ConsultaAgendada(
        consulta_id=uuid4(),
        paciente_id=uuid4(),
        queixa_id=None,
        inicio=AGORA,
        prioridade=Prioridade.ROTINA,
        origem=OrigemAgendamento.WHATSAPP,
        ocorrido_em=AGORA,
    )

    await processar([evento], ConduzirLento(), notificar)

    assert notificar.eventos == [evento]
