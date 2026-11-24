"""Fontes oficiais de editais: Diário Oficial da União e sites de bancas.

DOU: a busca pública do in.gov.br embute os resultados em JSON numa tag
<script id="..._BuscaDouPortlet_params">. Ela devolve no máximo 20 itens por
página e a paginação depende de um cursor interno, por isso consultamos um dia
de cada vez (num dia raramente passam de 20 "editais de abertura").

Bancas: cada site tem um layout, então o parser é genérico: pega os links cujo
endereço casa com `padrao_link` (configurável) e usa o texto mais longo de cada
link como título.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..http import baixar
from ..modelos import Edital
from ..texto import normalizar

URL_DOU_BUSCA = (
    "https://www.in.gov.br/consulta/-/buscar/dou?q={q}&s={secao}&exactDate=personalizado"
    "&publishFrom={dia}&publishTo={dia}&sortType=0&delta=20"
)
URL_DOU_MATERIA = "https://www.in.gov.br/web/dou/-/{slug}"
RE_PARAMS_DOU = re.compile(r'_BuscaDouPortlet_params"[^>]*>(.*?)</script>', re.S)

# Publicações que citam "edital de abertura" mas não abrem inscrições.
RE_DOU_DESCARTAR = re.compile(
    r"\b(retifica\w*|convoca\w*|resultado\w*|homologa\w*|recurso|licitacao|pregao|extrato|"
    r"prorroga\w*|cancela\w*|suspen\w*|anula\w*|gabarito\w*|classificacao)\b"
)
RE_DOU_EXIGIR = re.compile(r"\b(concurso|processo seletivo|selecao publica)\b")
# Unidades internas que não identificam o órgão ("Ministério X/Secretaria Executiva").
RE_UNIDADE_GENERICA = re.compile(
    r"(?i)^(secretaria[- ]executiva|gabinete|diretoria|pr[óo]-reitoria|departamento|coordena|"
    r"superintend[êe]ncia|subsecretaria)"
)
# Onde a ementa termina e começa o texto: "... O DIRETOR-GERAL DO CAMPUS ...", "A REITORA ..."
RE_AUTORIDADE = re.compile(
    r"(?:^|\s)(?:O|A)\s+(?:MAGN[ÍI]FIC[OA]\s+)?(?:DIRETOR|REITOR|VICE-REITOR|PR[ÓO]-REITOR|PRESIDENTE|"
    r"SECRET[ÁA]RI|SUPERINTENDENTE|COORDENADOR|MINISTR|PROCURADOR|COMANDANTE|CHEFE|DEFENSOR)"
)
_cache_textos: dict[str, str] = {}


def _limpar(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", html_lib.unescape(s)).strip()


def _orgao_dou(item: dict) -> str:
    partes = item.get("hierarchyList") or (item.get("hierarchyStr") or "").split("/")
    partes = [p.strip() for p in partes if p and p.strip()]
    if not partes:
        return "Órgão não informado"
    # "Ministério da Educação/Universidade Federal X/Pró-Reitoria" -> "Universidade Federal X"
    # "Prefeituras/Estado de MG/Prefeitura de Y" -> "Prefeitura de Y"
    candidatos = [p for p in partes[1:] if not re.match(r"(?i)estado d[eoa]s? ", p)]
    if not candidatos or RE_UNIDADE_GENERICA.match(candidatos[0]):
        return partes[0]
    return candidatos[0]


def ementa(texto: str, titulo: str) -> str:
    """Trecho em maiúsculas logo após o título do ato, ex.:
    'EDITAL Nº 259 ... ABERTURA DE SELEÇÃO PÚBLICA PARA PROFESSOR SUBSTITUTO A Reitora...'
    -> 'ABERTURA DE SELEÇÃO PÚBLICA PARA PROFESSOR SUBSTITUTO'."""
    resto = texto
    if titulo and texto.upper().startswith(titulo.upper()):
        resto = texto[len(titulo):]
    palavras = []
    for p in resto.split():
        letras = [c for c in p if c.isalpha()]
        if letras and not all(c.isupper() for c in letras):
            break
        palavras.append(p)
    # a última palavra maiúscula costuma ser o início da frase seguinte ("A Reitora", "O Presidente")
    if palavras and len(palavras[-1]) <= 2:
        palavras.pop()
    trecho = RE_AUTORIDADE.split(" ".join(palavras), maxsplit=1)[0].strip(" ,.;:-")
    return trecho[:150] if len(trecho.split()) >= 3 else ""


def texto_dou(url: str) -> str:
    if url not in _cache_textos:
        soup = BeautifulSoup(baixar(url, tentativas=2), "html.parser")
        corpo = soup.find(class_="texto-dou") or soup.find("article") or soup.body or soup
        _cache_textos[url] = corpo.get_text(" ", strip=True)
    return _cache_textos[url]


def completar_dou(editais: list[Edital], workers: int = 6) -> None:
    """Lê o texto integral de cada edital (cargos, prazos) para filtros e destaques."""
    def ler(e: Edital) -> None:
        try:
            texto = texto_dou(e.id)
        except RuntimeError as err:
            print(f"[aviso] {err}")
            return
        e.resumo = texto
        e.descricao = ementa(texto, e.titulo)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(ler, editais))


def parse_dou(pagina_html: str) -> list[Edital]:
    m = RE_PARAMS_DOU.search(pagina_html)
    if not m:
        raise RuntimeError("Busca do DOU sem o bloco de resultados: o layout pode ter mudado.")
    itens = json.loads(m.group(1)).get("jsonArray", [])
    editais = []
    for it in itens:
        titulo = _limpar(it.get("title", ""))
        tipo = _limpar(it.get("artType", ""))
        resumo = _limpar(it.get("content", ""))
        slug = it.get("urlTitle")
        if not slug:
            continue
        cabecalho = normalizar(f"{tipo} {titulo} {resumo[:200]}")
        if RE_DOU_DESCARTAR.search(cabecalho) or not RE_DOU_EXIGIR.search(normalizar(f"{tipo} {resumo}")):
            continue
        try:
            publicado = datetime.strptime(it.get("pubDate", ""), "%d/%m/%Y").date()
        except ValueError:
            publicado = None
        editais.append(
            Edital(
                id=URL_DOU_MATERIA.format(slug=slug),
                titulo=titulo or tipo,
                orgao=_orgao_dou(it),
                fonte="DOU",
                situacao="edital de abertura",
                publicado=publicado,
                resumo=resumo,
            )
        )
    return editais


def buscar_dou(cfg: dict, hoje: date) -> list[Edital]:
    dias = int(cfg.get("dias", 7))
    secao = cfg.get("secao", "do3")
    consultas = cfg.get("consultas") or ['"edital de abertura"']
    vistos: dict[str, Edital] = {}
    falhas = 0
    tentativas = 0
    for i in range(dias):
        dia = hoje - timedelta(days=i)
        if dia.weekday() >= 5 and not cfg.get("incluir_fim_de_semana", False):
            continue  # o DOU quase nunca circula no fim de semana
        for q in consultas:
            tentativas += 1
            url = URL_DOU_BUSCA.format(q=quote_plus(q), secao=secao, dia=dia.strftime("%d-%m-%Y"))
            try:
                achados = parse_dou(baixar(url))
            except RuntimeError as e:
                print(f"[aviso] {e}")
                falhas += 1
                continue
            for e in achados:
                vistos.setdefault(e.id, e)
    if tentativas and falhas == tentativas:
        raise RuntimeError("Não foi possível consultar o Diário Oficial da União.")
    editais = list(vistos.values())
    if cfg.get("ler_texto_completo", True):
        completar_dou(editais)
        # a ementa do texto integral revela retificações que o trecho da busca escondia
        editais = [e for e in editais if not RE_DOU_DESCARTAR.search(normalizar(e.descricao))]
    return sorted(editais, key=lambda e: e.publicado or date.min, reverse=True)


def parse_pagina(pagina_html: str, base_url: str, nome: str, padrao_link: str, situacao: str) -> list[Edital]:
    rx = re.compile(padrao_link)
    soup = BeautifulSoup(pagina_html, "html.parser")
    titulos: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"].strip())
        if not rx.search(url):
            continue
        texto = a.get_text(" ", strip=True)
        if len(texto) > len(titulos.get(url, "")):
            titulos[url] = texto
        else:
            titulos.setdefault(url, "")
    ignorar = re.compile(r"(?i)^(mais informa\w*|saiba mais|inscri\w* abertas?!?|acessar|ver mais)$")
    editais = []
    for url, titulo in titulos.items():
        if not titulo or ignorar.match(titulo):
            continue
        editais.append(Edital(id=url, titulo=titulo, orgao=titulo, fonte=nome, situacao=situacao))
    return editais


def buscar_pagina(cfg: dict) -> list[Edital]:
    url = cfg["url"]
    achados = parse_pagina(
        baixar(url), url, cfg["nome"], cfg.get("padrao_link", "."), cfg.get("situacao", "")
    )
    if not achados:
        print(f"[aviso] Nenhum edital reconhecido em {url}: o layout pode ter mudado.")
    return achados
