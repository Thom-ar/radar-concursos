"""Estado persistido em JSON (versionado no repositório pelo GitHub Actions)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

CAMINHO_PADRAO = Path("data/estado.json")


class Estado:
    def __init__(self, caminho: Path = CAMINHO_PADRAO):
        self.caminho = caminho
        if caminho.exists():
            self.dados = json.loads(caminho.read_text(encoding="utf-8"))
        else:
            self.dados = {}
        self.dados.setdefault("concursos", {})
        self.dados.setdefault("noticias", {})
        self.dados.setdefault("detalhe_cache", {})

    @property
    def primeira_execucao(self) -> bool:
        return not self.dados.get("inicializado", False)

    @property
    def concursos(self) -> dict:
        return self.dados["concursos"]

    @property
    def noticias(self) -> dict:
        return self.dados["noticias"]

    @property
    def detalhe_cache(self) -> dict:
        """url -> lista de palavras-chave achadas na página de detalhe."""
        return self.dados["detalhe_cache"]

    def limpar(self, hoje: date) -> None:
        corte_conc = (hoje - timedelta(days=30)).isoformat()
        corte_not = (hoje - timedelta(days=60)).isoformat()
        self.dados["concursos"] = {
            k: v for k, v in self.concursos.items() if (v.get("fim") or v["visto_em"]) >= corte_conc
        }
        self.dados["noticias"] = {k: v for k, v in self.noticias.items() if v >= corte_not}
        validos = set(self.concursos)
        self.dados["detalhe_cache"] = {k: v for k, v in self.detalhe_cache.items() if k in validos}

    def salvar(self) -> None:
        self.dados["inicializado"] = True
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(
            json.dumps(self.dados, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
