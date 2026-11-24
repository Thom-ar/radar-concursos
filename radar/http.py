from __future__ import annotations

import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 RadarConcursos/1.0"
)

_sessao = requests.Session()
_sessao.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})


def baixar(url: str, tentativas: int = 3, timeout: int = 30) -> str:
    """GET com retry exponencial simples. Retorna o texto decodificado."""
    ultimo_erro: Exception | None = None
    for i in range(tentativas):
        try:
            r = _sessao.get(url, timeout=timeout)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding
            return r.text
        except requests.RequestException as e:
            ultimo_erro = e
            time.sleep(2 ** i)
    raise RuntimeError(f"Falha ao baixar {url}: {ultimo_erro}")
