from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .estado import Estado
from .fontes import noticias as fonte_noticias
from .fontes import pci
from .modelos import Concurso, Noticia
from .telegram import Telegram, esc
from .texto import compilar_palavras, encontrar_palavras

FUSO = ZoneInfo("America/Belem")
MAX_INDIVIDUAIS = 8  # acima disso, novos concursos vão num resumo único


def hoje_local() -> date:
    return datetime.now(FUSO).date()


@dataclass
class Resultado:
    novos: list[Concurso] = field(default_factory=list)
    lembretes: list[Concurso] = field(default_factory=list)
    prorrogados: list[tuple[Concurso, str]] = field(default_factory=list)
    noticias: list[Noticia] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    total_relevantes: list[Concurso] = field(default_factory=list)


# ───────────────────────── classificação ─────────────────────────

def classificar_area(concursos: list[Concurso], cfg_area: dict, estado: Estado, sem_limite: bool) -> None:
    padroes = compilar_palavras(cfg_area.get("palavras_chave", []))
    limite = None if sem_limite else cfg_area.get("max_paginas_detalhe_por_execucao", 40)
    buscas = 0
    for c in concursos:
        c.palavras_encontradas = encontrar_palavras(f"{c.orgao}\n{c.cargos}", padroes)
        if c.palavras_encontradas or not cfg_area.get("verificar_pagina_detalhe", True):
            continue
        if c.id in estado.detalhe_cache:
            c.palavras_encontradas = estado.detalhe_cache[c.id]
            continue
        if limite is not None and buscas >= limite:
            continue
        try:
            texto = pci.texto_da_noticia(c.id)
            buscas += 1
            time.sleep(0.7)  # educado com o servidor
        except RuntimeError as e:
            print(f"[aviso] {e}")
            continue
        c.palavras_encontradas = encontrar_palavras(texto, padroes)
        estado.detalhe_cache[c.id] = c.palavras_encontradas


def pendente_de_detalhe(c: Concurso, cfg_area: dict, estado: Estado) -> bool:
    return (
        cfg_area.get("verificar_pagina_detalhe", True)
        and not c.palavras_encontradas
        and c.id not in estado.detalhe_cache
    )


# ───────────────────────── execução ─────────────────────────

def executar(cfg: dict, estado: Estado, hoje: date) -> Resultado:
    res = Resultado()
    cfg_area = cfg.get("area", {})
    exigir = cfg_area.get("exigir_palavra_chave", True)
    dias_lembrete = cfg.get("lembretes", {}).get("dias_antes_do_fim", 3)
    ufs = set(cfg.get("pci", {}).get("ufs", []))

    # 1) Concursos abertos (PCI)
    try:
        concursos = pci.buscar(cfg["pci"]["paginas"])
    except RuntimeError as e:
        res.erros.append(str(e))
        concursos = []
    if not concursos and not res.erros:
        res.erros.append("Nenhum concurso reconhecido no PCI: o layout do site pode ter mudado.")
    concursos = [c for c in concursos if not ufs or c.uf in ufs]
    classificar_area(concursos, cfg_area, estado, sem_limite=estado.primeira_execucao)

    for c in concursos:
        if pendente_de_detalhe(c, cfg_area, estado):
            continue  # ainda não sabemos se é relevante; avalia na próxima execução
        relevante = bool(c.palavras_encontradas) or not exigir
        fim = c.fim_inscricao.isoformat() if c.fim_inscricao else None
        antigo = estado.concursos.get(c.id)

        if relevante:
            res.total_relevantes.append(c)
            if antigo is None:
                res.novos.append(c)
            else:
                if fim and antigo.get("fim") and fim > antigo["fim"]:
                    res.prorrogados.append((c, antigo["fim"]))
                    antigo["lembrete"] = False
                if (
                    c.fim_inscricao
                    and 0 <= (c.fim_inscricao - hoje).days <= dias_lembrete
                    and not antigo.get("lembrete")
                ):
                    res.lembretes.append(c)

        registro = estado.concursos.setdefault(c.id, {"visto_em": hoje.isoformat()})
        registro.update(orgao=c.orgao, uf=c.uf, fim=fim, relevante=relevante)
        perto_do_fim = c.fim_inscricao and (c.fim_inscricao - hoje).days <= dias_lembrete
        if c in res.lembretes or (antigo is None and perto_do_fim):
            # concurso novo já perto do fim: o próprio aviso de "novo" mostra o prazo
            registro["lembrete"] = True

    # 2) Notícias de concursos previstos/autorizados
    cfg_not = cfg.get("noticias", {})
    if cfg_not.get("ativo", True):
        noticias = fonte_noticias.buscar(cfg_not.get("consultas", []), cfg_not.get("max_dias", 3), hoje)
        novas = [n for n in noticias if n.id not in estado.noticias]
        res.noticias = novas[: cfg_not.get("max_por_execucao", 10)]
        for n in novas:
            estado.noticias[n.id] = (n.publicada or hoje).isoformat()

    estado.limpar(hoje)
    return res


# ───────────────────────── formatação ─────────────────────────

def _fmt_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "?"


def _prazo(c: Concurso, hoje: date) -> str:
    if not c.fim_inscricao:
        return "Inscrições: data não informada"
    dias = (c.fim_inscricao - hoje).days
    if c.inicio_inscricao and c.inicio_inscricao > hoje:
        faixa = f"{_fmt_data(c.inicio_inscricao)} a {_fmt_data(c.fim_inscricao)} (ainda vai abrir)"
    elif c.inicio_inscricao:
        faixa = f"{_fmt_data(c.inicio_inscricao)} a {_fmt_data(c.fim_inscricao)}"
    else:
        faixa = f"até {_fmt_data(c.fim_inscricao)}"
    if dias == 0:
        sufixo = " — <b>último dia!</b>"
    elif dias > 0:
        sufixo = f" — faltam {dias} dia{'s' if dias != 1 else ''}"
    else:
        sufixo = " — encerrado"
    return f"Inscrições: {faixa}{sufixo}"


def fmt_concurso(c: Concurso, hoje: date, prefixo: str = "🆕") -> str:
    linhas = [f'{prefixo} <b><a href="{esc(c.id)}">{esc(c.orgao)}</a></b>']
    local = "🇧🇷 Nacional" if c.uf == "Nacional" else f"📍 {esc(c.uf)}"
    if c.escolaridade:
        local += f" · 🎓 {esc(c.escolaridade)}"
    linhas.append(local)
    if c.cargos:
        linhas.append(f"💼 {esc(c.cargos)}")
    if c.vagas_salario:
        linhas.append(f"💰 {esc(c.vagas_salario)}")
    linhas.append(f"🗓 {_prazo(c, hoje)}")
    if c.palavras_encontradas:
        linhas.append(f"🔎 {esc(', '.join(c.palavras_encontradas[:6]))}")
    return "\n".join(linhas)


def fmt_compacto(c: Concurso) -> str:
    uf = "BR" if c.uf == "Nacional" else c.uf
    return f'• <a href="{esc(c.id)}">{esc(c.orgao)}</a> ({esc(uf)}) — até {_fmt_data(c.fim_inscricao)}'


def mensagens(res: Resultado, hoje: date, primeira: bool) -> list[str]:
    msgs: list[str] = []
    ordenar = lambda cs: sorted(cs, key=lambda c: c.fim_inscricao or date.max)

    if primeira:
        rel = ordenar(res.total_relevantes)
        cab = f"✅ <b>Radar de concursos ativado</b>\n{len(rel)} concurso(s) aberto(s) batem com seus filtros hoje:"
        msgs.append(cab + "\n\n" + "\n".join(fmt_compacto(c) for c in rel) if rel else cab + "\nnenhum por enquanto.")
        msgs.append("A partir de agora você recebe só novidades, prorrogações e lembretes de prazo.")
        return msgs

    novos = ordenar(res.novos)
    if len(novos) <= MAX_INDIVIDUAIS:
        msgs.extend(fmt_concurso(c, hoje) for c in novos)
    else:
        msgs.append(f"🆕 <b>{len(novos)} novos concursos</b>\n\n" + "\n".join(fmt_compacto(c) for c in novos))

    for c in ordenar(res.lembretes):
        msgs.append(fmt_concurso(c, hoje, prefixo="⏰ <b>Prazo acabando:</b>"))

    for c, fim_antigo in res.prorrogados:
        antigo = date.fromisoformat(fim_antigo)
        msgs.append(
            fmt_concurso(c, hoje, prefixo="🔁 <b>Inscrições prorrogadas</b> (antes: "
                         f"{_fmt_data(antigo)})\n")
        )

    if res.noticias:
        corpo = "\n".join(
            f'• <a href="{esc(n.id)}">{esc(n.titulo)}</a>' + (f" <i>({esc(n.fonte)})</i>" if n.fonte else "")
            for n in res.noticias
        )
        msgs.append(f"📰 <b>Concursos previstos / autorizados — novidades</b>\n\n{corpo}")

    if res.erros:
        msgs.append("⚠️ <b>Erros nesta execução</b>\n" + "\n".join(esc(e) for e in res.erros))
    return msgs


def rodar(cfg: dict, estado: Estado, tg: Telegram) -> int:
    hoje = hoje_local()
    primeira = estado.primeira_execucao
    res = executar(cfg, estado, hoje)
    for m in mensagens(res, hoje, primeira):
        tg.enviar(m)
    estado.salvar()
    print(
        f"[ok] relevantes={len(res.total_relevantes)} novos={len(res.novos)} "
        f"lembretes={len(res.lembretes)} prorrogados={len(res.prorrogados)} noticias={len(res.noticias)}"
    )
    return 1 if res.erros else 0
