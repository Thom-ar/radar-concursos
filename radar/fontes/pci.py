"""Parser das listagens de concursos abertos do PCI Concursos.

O parser não depende de nomes de classes CSS: ele localiza cada link de notícia
(/noticias/...) e lê as linhas de texto do bloco que o contém. Isso o torna
resistente a pequenas mudanças de layout do site.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..http import baixar
from ..modelos import Concurso
from ..texto import RE_DATA, extrair_datas, normalizar

RE_UF = re.compile(r"^[A-Z]{2}$")
RE_ESCOLARIDADE = re.compile(
    r"fundamental|medio|tecnico|superior|alfabetizado|graduacao|pos-graduacao|mestrado|doutorado"
)
RE_LINK_NOTICIA = re.compile(r"/noticias/")
LINHAS_IGNORADAS = re.compile(r"^(inscri[cç][aã]o at[eé]:?|apostila.*|a|até|ate)$", re.I)


def _eh_linha_de_data(linha: str) -> bool:
    """'27/11/2026', '30/11/2026 a', 'Prorrogado até 10/12/2026'..."""
    if not RE_DATA.search(linha):
        return False
    resto = normalizar(RE_DATA.sub(" ", linha))
    resto = re.sub(r"\b(a|ate|de|prorrogad[oa]|reabert[oa]|inscric(ao|oes))\b", " ", resto)
    return not resto.strip(" :-")


def _bloco_do_link(a: Tag) -> Tag | None:
    """Sobe na árvore até achar o bloco do concurso (contém data e só 1 notícia)."""
    atual = a.parent
    for _ in range(4):
        if atual is None or not isinstance(atual, Tag):
            return None
        links = atual.find_all("a", href=RE_LINK_NOTICIA)
        if len(links) > 1:
            return None
        if RE_DATA.search(atual.get_text(" ")):
            return atual
        atual = atual.parent
    return None


def _parse_bloco(bloco: Tag, a: Tag, base_url: str, secao: str) -> Concurso | None:
    orgao = a.get_text(" ", strip=True)
    if not orgao:
        return None
    url = urljoin(base_url, a["href"])

    linhas = [l.strip() for l in bloco.get_text("\n").split("\n")]
    linhas = [l for l in linhas if l and l != orgao and not LINHAS_IGNORADAS.match(l)]

    uf = secao
    vagas = cargos = escolaridade = ""
    restantes = []
    linhas_data = []
    for linha in linhas:
        if RE_UF.match(linha) and uf == secao:
            uf = linha
        elif _eh_linha_de_data(linha):
            linhas_data.append(linha)
        elif not vagas and ("vaga" in linha.lower() or "R$" in linha):
            vagas = linha
        elif not escolaridade and RE_ESCOLARIDADE.search(normalizar(linha)) and len(linha) < 80:
            escolaridade = linha
        else:
            restantes.append(linha)

    if restantes:
        cargos = restantes[0]

    datas = extrair_datas("\n".join(linhas_data))
    inicio = fim = None
    if datas:
        fim = max(datas)
        if len(datas) > 1:
            inicio = min(datas)

    return Concurso(
        id=url,
        orgao=orgao,
        uf=uf,
        vagas_salario=vagas,
        cargos=cargos,
        escolaridade=escolaridade,
        inicio_inscricao=inicio,
        fim_inscricao=fim,
    )


def parse_listagem(html: str, base_url: str, secao: str) -> list[Concurso]:
    soup = BeautifulSoup(html, "html.parser")
    concursos: dict[str, Concurso] = {}
    for a in soup.find_all("a", href=RE_LINK_NOTICIA):
        bloco = _bloco_do_link(a)
        if bloco is None:
            continue
        c = _parse_bloco(bloco, a, base_url, secao)
        if c and c.id not in concursos:
            concursos[c.id] = c
    return list(concursos.values())


def buscar(paginas: list[dict]) -> list[Concurso]:
    todos: list[Concurso] = []
    for p in paginas:
        html = baixar(p["url"])
        achados = parse_listagem(html, p["url"], p.get("secao", ""))
        if not achados:
            print(f"[aviso] Nenhum concurso reconhecido em {p['url']} — o layout pode ter mudado.")
        todos.extend(achados)
    return todos


def texto_da_noticia(url: str) -> str:
    soup = BeautifulSoup(baixar(url), "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
    principal = soup.find("article") or soup.find(id="noticia") or soup.body or soup
    return principal.get_text(" ", strip=True)
