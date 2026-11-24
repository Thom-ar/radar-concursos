from __future__ import annotations

import re
import unicodedata
from datetime import date

RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def normalizar(s: str) -> str:
    """Minúsculas, sem acentos, espaços colapsados."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def extrair_datas(s: str) -> list[date]:
    datas = []
    for d, m, a in RE_DATA.findall(s):
        try:
            datas.append(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    return datas


def compilar_palavras(palavras: list[str]) -> list[tuple[str, re.Pattern]]:
    """Cada palavra vira um regex com fronteira de palavra (TI não casa 'gestão')."""
    return [
        (p, re.compile(rf"(?<![a-z0-9]){re.escape(normalizar(p))}(?![a-z0-9])"))
        for p in palavras
    ]


def encontrar_palavras(texto: str, padroes: list[tuple[str, re.Pattern]]) -> list[str]:
    # Siglas curtas (ex.: "TI") são procuradas com caixa original para evitar
    # falsos positivos como "ti" em outras palavras/abreviações.
    norm = normalizar(texto)
    achadas = []
    for original, rx in padroes:
        if len(original) <= 3 and original.isupper():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(original)}(?![A-Za-z0-9])", texto):
                achadas.append(original)
        elif rx.search(norm):
            achadas.append(original)
    return achadas
