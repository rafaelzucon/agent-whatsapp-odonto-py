"""Reclassificação manual da queixa e consulta ao catálogo."""

from collections.abc import Sequence

from odonto.aplicacao.excecoes import RecursoNaoEncontradoError
from odonto.aplicacao.portas.entrada.prontuario import QueixaResumo, ReclassificarQueixaCommand
from odonto.aplicacao.portas.saida.relogio import Relogio
from odonto.aplicacao.portas.saida.unidade_de_trabalho import UnidadeDeTrabalho
from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.problema import ProblemaOdontologico


class ReclassificarQueixaService:
    def __init__(self, *, uow: UnidadeDeTrabalho, relogio: Relogio) -> None:
        self._uow = uow
        self._relogio = relogio

    async def executar(self, comando: ReclassificarQueixaCommand) -> QueixaResumo:
        async with self._uow as uow:
            prontuario = await uow.prontuarios.buscar_por_queixa(comando.queixa_id)
            if prontuario is None:
                raise RecursoNaoEncontradoError("Queixa", comando.queixa_id)
            problema = await uow.catalogo.buscar_por_codigo(comando.codigo_problema)
            if problema is None:
                raise DadoInvalidoError(
                    "codigo_problema", f"Código fora do catálogo: {comando.codigo_problema!r}."
                )
            queixa = prontuario.reclassificar_queixa(
                comando.queixa_id,
                problema=problema,
                prioridade=comando.prioridade,
                momento=self._relogio.agora(),
            )
            await uow.prontuarios.salvar(prontuario)
            await uow.commit()
        return QueixaResumo.de(queixa)


class ConsultarCatalogoService:
    def __init__(self, *, uow: UnidadeDeTrabalho) -> None:
        self._uow = uow

    async def listar(self, *, somente_ativos: bool = True) -> Sequence[ProblemaOdontologico]:
        async with self._uow as uow:
            return tuple(await uow.catalogo.listar(somente_ativos=somente_ativos))
