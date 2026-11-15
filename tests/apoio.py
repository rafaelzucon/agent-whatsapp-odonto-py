"""Apoio aos testes: fuso, momento de referência e fábricas de objetos do domínio."""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from odonto.dominio.modelo.enums import DiaSemana, Prioridade
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.valores import DocumentoRg, WaId
from odonto.dominio.servico.agenda import HorarioFuncionamento

FUSO = ZoneInfo("America/Sao_Paulo")


def em(ano: int, mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    """Momento no fuso do consultório."""
    return datetime(ano, mes, dia, hora, minuto, tzinfo=FUSO)


# Quarta-feira, 18/11/2026, 09:00 (horário de Brasília): o "agora" padrão dos testes.
AGORA = em(2026, 11, 18, 9, 0)
HOJE = AGORA.date()
WA_ID = WaId("5511987654321")
RG = DocumentoRg.criar("12.345.678-9", "SP")
NASCIMENTO_ADULTO = date(1990, 3, 15)
NASCIMENTO_MENOR = date(2015, 6, 1)


def problema(
    codigo: str = "CARIE",
    *,
    nome: str | None = None,
    prioridade: Prioridade = Prioridade.ROTINA,
    cid10: str = "K02.9",
    palavras_chave: tuple[str, ...] = (),
    ativo: bool = True,
) -> ProblemaOdontologico:
    return ProblemaOdontologico(
        codigo=codigo,
        nome=nome or codigo.replace("_", " ").capitalize(),
        descricao=f"Descrição de {codigo}.",
        especialidade="Clínica geral",
        prioridade=prioridade,
        cid10=cid10,
        palavras_chave=palavras_chave,
        ativo=ativo,
    )


CATALOGO_TESTE = (
    problema(
        "CARIE",
        nome="Cárie dentária",
        palavras_chave=("carie", "dente furado", "buraco no dente", "dente escuro"),
    ),
    problema(
        "DOR_DE_DENTE",
        nome="Dor de dente",
        prioridade=Prioridade.URGENCIA,
        cid10="K08.8",
        palavras_chave=("dor de dente", "dor no dente", "dente doendo", "dente doi"),
    ),
    problema(
        "GENGIVITE",
        nome="Gengivite",
        cid10="K05.1",
        palavras_chave=("gengiva sangrando", "sangramento na gengiva", "gengiva inflamada"),
    ),
    problema(
        "AVULSAO_TRAUMA",
        nome="Dente arrancado por trauma",
        prioridade=Prioridade.EMERGENCIA,
        cid10="S03.2",
        palavras_chave=("dente caiu", "dente arrancado", "bati o dente"),
    ),
    problema(
        "LIMPEZA_PROFILAXIA",
        nome="Limpeza",
        cid10="Z01.2",
        palavras_chave=("limpeza", "tartaro"),
    ),
    problema(
        "ITEM_INATIVO",
        nome="Item desativado",
        cid10="Z01.2",
        palavras_chave=("limpeza",),
        ativo=False,
    ),
    problema("AVALIACAO_GERAL_OUTRO", nome="Avaliação geral", cid10="Z01.2"),
)


def buscar_no_catalogo(codigo: str) -> ProblemaOdontologico:
    return next(item for item in CATALOGO_TESTE if item.codigo == codigo)


def funcionamento(**alteracoes: Any) -> HorarioFuncionamento:
    """Expediente padrão do ``config/odonto.yaml``: SEG a SEX, 8h às 18h, almoço 12h às 13h,
    consultas de 30 minutos e 2 horas de antecedência mínima."""
    campos: dict[str, Any] = {
        "dias_atendimento": frozenset(
            {DiaSemana.SEG, DiaSemana.TER, DiaSemana.QUA, DiaSemana.QUI, DiaSemana.SEX}
        ),
        "abertura": time(8, 0),
        "fechamento": time(18, 0),
        "almoco_inicio": time(12, 0),
        "almoco_fim": time(13, 0),
        "duracao_consulta": timedelta(minutes=30),
        "antecedencia_minima": timedelta(hours=2),
        "fuso": FUSO,
    }
    campos.update(alteracoes)
    return HorarioFuncionamento(**campos)
