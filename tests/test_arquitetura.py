"""Testes de arquitetura: os contratos do import-linter (``pyproject.toml``) precisam passar.

Quebrar a regra de dependência da Clean Architecture (ex.: o domínio importar SQLAlchemy, um
router importar um caso de uso concreto) faz este teste, e portanto a build, falhar.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.arquitetura
def test_contratos_do_import_linter() -> None:
    executavel = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    resultado = subprocess.run(  # noqa: S603 - executável do próprio ambiente virtual
        [executavel, "--no-cache"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "0 broken" in resultado.stdout
