"""Ponto de entrada: ``odonto`` ou ``python -m odonto`` sobe o Uvicorn com 1 worker.

Um único processo é obrigatório: a fila, as travas por número e o agendador vivem em memória.
"""

import logging
import sys

import uvicorn
from pydantic import ValidationError

from odonto.infraestrutura.app import criar_app
from odonto.infraestrutura.config import carregar_configuracoes
from odonto.infraestrutura.container import ERROS_CONFIGURACAO, validar_configuracoes
from odonto.infraestrutura.logs import configurar_logs

_log = logging.getLogger(__name__)


def executar() -> None:
    configurar_logs()
    try:
        configuracoes = carregar_configuracoes()
        validar_configuracoes(configuracoes)
    except (ValidationError, FileNotFoundError, *ERROS_CONFIGURACAO) as erro:
        detalhes = (
            [f"{'.'.join(map(str, e['loc'])) or 'geral'}: {e['msg']}" for e in erro.errors()]
            if isinstance(erro, ValidationError)
            else [str(erro)]
        )
        _log.critical("configuração inválida", extra={"erros": detalhes})
        sys.exit(2)
    configurar_logs(configuracoes.log_nivel)
    uvicorn.run(
        criar_app(configuracoes),
        host=configuracoes.host,
        port=configuracoes.porta,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=configuracoes.forwarded_allow_ips,
        log_config=None,
        server_header=False,
        timeout_graceful_shutdown=25,
    )
