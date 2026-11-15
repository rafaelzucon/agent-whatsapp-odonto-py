import json
import logging

import pytest

from odonto.infraestrutura.logs import FormatadorJson, configurar_logs, mascarar_tokens


def _registro(mensagem: str, *args: object, **extra: object) -> logging.LogRecord:
    registro = logging.LogRecord("odonto.teste", logging.INFO, __file__, 1, mensagem, args, None)
    registro.__dict__.update(extra)
    return registro


def test_uma_linha_json_com_campos_extras() -> None:
    linha = FormatadorJson().format(_registro("consulta %s", "agendada", consulta_id="abc"))

    evento = json.loads(linha)
    assert "\n" not in linha
    assert evento["mensagem"] == "consulta agendada"
    assert evento["nivel"] == "INFO"
    assert evento["consulta_id"] == "abc"


def test_excecao_vai_em_campo_proprio() -> None:
    try:
        raise ValueError("falhou")
    except ValueError:
        registro = logging.LogRecord(
            "odonto", logging.ERROR, __file__, 1, "erro", None, __import__("sys").exc_info()
        )

    evento = json.loads(FormatadorJson().format(registro))
    assert "ValueError: falhou" in evento["excecao"]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (
            "GET /webhook?hub.mode=subscribe&hub.verify_token=segredo&hub.challenge=1",
            "GET /webhook?hub.mode=subscribe&hub.verify_token=***&hub.challenge=1",
        ),
        ("/docs?token=abc123 HTTP/1.1", "/docs?token=*** HTTP/1.1"),
        ("sem segredo", "sem segredo"),
    ],
)
def test_mascara_tokens_em_urls(texto: str, esperado: str) -> None:
    assert mascarar_tokens(texto) == esperado


def test_configurar_logs_usa_um_handler_json(capsys: pytest.CaptureFixture[str]) -> None:
    raiz = logging.getLogger()
    handlers, nivel = raiz.handlers[:], raiz.level
    try:
        configurar_logs("WARNING")
        acesso = logging.getLogger("uvicorn.access")
        acesso.warning('"GET /docs?token=x HTTP/1.1" 200')
        formato = '%s - "%s %s HTTP/%s" %d'
        acesso.warning(formato, "127.0.0.1:1", "GET", "/health", "1.1", 200)
        acesso.warning(formato, "127.0.0.1:1", "GET", "/health", "1.1", 503)
        logging.getLogger("odonto").info("não aparece")
    finally:
        raiz.handlers[:], raiz.level = handlers, nivel

    linhas = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(linha)["mensagem"] for linha in linhas] == [
        '"GET /docs?token=*** HTTP/1.1" 200',
        '127.0.0.1:1 - "GET /health HTTP/1.1" 503',
    ]
