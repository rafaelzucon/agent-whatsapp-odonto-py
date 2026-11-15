"""Leitura do catálogo de problemas em YAML (fonte única da migração ``0002``)."""

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from odonto.dominio.modelo.enums import Prioridade
from odonto.dominio.modelo.problema import ProblemaOdontologico

ARQUIVO_CATALOGO = "catalogo_problemas.yaml"


def caminho_catalogo() -> Path:
    return Path(str(resources.files(__package__) / "dados" / ARQUIVO_CATALOGO))


def ler_catalogo(caminho: Path | None = None) -> list[ProblemaOdontologico]:
    """Lê e valida o catálogo (códigos únicos e válidos, prioridade e CID-10 preenchidos)."""
    texto = (caminho or caminho_catalogo()).read_text(encoding="utf-8")
    bruto: dict[str, Any] = yaml.safe_load(texto)
    problemas = [
        ProblemaOdontologico(
            codigo=item["codigo"],
            nome=item["nome"],
            descricao=item["descricao"],
            especialidade=item["especialidade"],
            prioridade=Prioridade(item["prioridade"]),
            cid10=item["cid10"],
            palavras_chave=tuple(str(p) for p in item.get("palavras_chave") or ()),
        )
        for item in bruto["problemas"]
    ]
    codigos = [p.codigo for p in problemas]
    repetidos = sorted({c for c in codigos if codigos.count(c) > 1})
    if repetidos:
        raise ValueError(f"Códigos repetidos no catálogo: {', '.join(repetidos)}.")
    return problemas
