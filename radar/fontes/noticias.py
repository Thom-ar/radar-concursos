"""Radar de concursos previstos/autorizados via RSS de busca do Google News."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from ..http import baixar
from ..modelos import Noticia

URL_RSS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def parse_rss(xml: str, consulta: str) -> list[Noticia]:
    raiz = ET.fromstring(xml)
    itens = []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        fonte = (item.findtext("source") or "").strip()
        pub = item.findtext("pubDate")
        publicada = None
        if pub:
            try:
                publicada = parsedate_to_datetime(pub).astimezone(timezone.utc).date()
            except (TypeError, ValueError):
                pass
        # O Google News costuma anexar " - Fonte" ao título
        if fonte and titulo.endswith(f" - {fonte}"):
            titulo = titulo[: -len(fonte) - 3]
        if titulo and link:
            itens.append(Noticia(id=link, titulo=titulo, fonte=fonte, publicada=publicada, consulta=consulta))
    return itens


def buscar(consultas: list[str], max_dias: int, hoje: date | None = None) -> list[Noticia]:
    hoje = hoje or datetime.now(timezone.utc).date()
    limite = hoje - timedelta(days=max_dias)
    vistas: dict[str, Noticia] = {}
    titulos: set[str] = set()
    for q in consultas:
        try:
            xml = baixar(URL_RSS.format(q=quote_plus(f"{q} when:{max_dias}d")))
        except RuntimeError as e:
            print(f"[aviso] {e}")
            continue
        for n in parse_rss(xml, q):
            chave_titulo = n.titulo.lower()
            if n.publicada and n.publicada < limite:
                continue
            if n.id in vistas or chave_titulo in titulos:
                continue
            vistas[n.id] = n
            titulos.add(chave_titulo)
    return sorted(vistas.values(), key=lambda n: n.publicada or hoje, reverse=True)
