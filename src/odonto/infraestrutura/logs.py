"""Logs em JSON (uma linha por evento) com o ``logging`` da biblioteca padrão.

Campos extras passados em ``extra={...}`` entram no JSON. Tokens na query string (``token=``,
``hub.verify_token=``) são mascarados, inclusive nos logs de acesso do Uvicorn.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final

_ATRIBUTOS_PADRAO: Final = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "taskName", "color_message"}
)
_TOKEN_NA_URL: Final = re.compile(r"((?:^|[?&\s])[\w.]*token=)[^&\s\"']+", re.IGNORECASE)


def mascarar_tokens(texto: str) -> str:
    return _TOKEN_NA_URL.sub(r"\1***", texto)


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "momento": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "nivel": record.levelname,
            "logger": record.name,
            "mensagem": mascarar_tokens(record.getMessage()),
        }
        evento |= {
            chave: valor
            for chave, valor in record.__dict__.items()
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_")
        }
        if record.exc_info:
            evento["excecao"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = "INFO") -> None:
    """Um único handler em stdout no logger raiz; Uvicorn e bibliotecas propagam para ele."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatadorJson())
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler]
    raiz.setLevel(nivel)
    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True
    # Bibliotecas verbosas (e que podem registrar URLs e corpos) ficam em WARNING.
    for nome in ("httpx", "httpcore", "httpx2", "anthropic", "openai", "apscheduler"):
        logging.getLogger(nome).setLevel(logging.WARNING)
