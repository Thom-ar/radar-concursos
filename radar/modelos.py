from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Concurso:
    id: str                      # URL da notícia no PCI (estável)
    orgao: str
    uf: str                      # "PA", "AM", ... ou "Nacional"
    vagas_salario: str = ""
    cargos: str = ""
    escolaridade: str = ""
    inicio_inscricao: date | None = None
    fim_inscricao: date | None = None
    palavras_encontradas: list[str] = field(default_factory=list)

    @property
    def cargos_genericos(self) -> bool:
        c = self.cargos.lower()
        return not c or "vários" in c or "varios" in c or "diversos" in c


@dataclass
class Noticia:
    id: str          # link
    titulo: str
    fonte: str
    publicada: date | None
    consulta: str
