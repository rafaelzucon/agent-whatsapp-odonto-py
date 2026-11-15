"""Permite ``python -m odonto``: sobe o Uvicorn com 1 worker."""

from odonto.infraestrutura.servidor import executar

if __name__ == "__main__":
    executar()
