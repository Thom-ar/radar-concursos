"""Comandos do bot no Telegram.

    /editais            editais abertos nas fontes oficiais (seus filtros em destaque)
    /editais <termo>    só os que citam o termo (ex.: /editais engenharia, /editais Pará)
    /ajuda              lista de comandos

Dois modos de execução:
    responder_pendentes()  responde o que chegou desde a última vez e sai (GitHub Actions)
    escutar()              fica ligado com long polling, resposta imediata (PC/servidor)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date

import requests

from .fontes import oficiais
from .modelos import Edital
from .telegram import Telegram, esc
from .texto import compilar_palavras, encontrar_palavras, normalizar

COMANDOS = [
    ("editais", "Editais abertos em fontes oficiais (DOU e bancas)"),
    ("ajuda", "Como usar o radar"),
]

AJUDA = (
    "🔔 <b>Radar de Concursos</b>\n\n"
    "/editais: editais abertos em <b>fontes oficiais</b> (Diário Oficial da União e sites das bancas). "
    "Os que batem com suas palavras-chave aparecem primeiro, com 🔎.\n"
    "/editais <i>termo</i>: só os que citam o termo. Ex.: <code>/editais engenharia</code>, "
    "<code>/editais Pará</code>\n\n"
    "Os avisos automáticos (novos concursos, prazos, prorrogações) continuam chegando sozinhos."
)

RE_COMANDO = re.compile(r"^/(\w+)(?:@\w+)?(?:\s+(.*))?$", re.S)


@dataclass
class Coleta:
    por_fonte: dict[str, list[Edital]] = field(default_factory=dict)
    situacao: dict[str, str] = field(default_factory=dict)
    erros: list[str] = field(default_factory=list)


def coletar(cfg: dict, hoje: date) -> Coleta:
    cfg_of = cfg.get("oficiais", {})
    col = Coleta()
    padroes = compilar_palavras(cfg.get("area", {}).get("palavras_chave", []))

    cfg_dou = cfg_of.get("dou", {})
    if cfg_dou.get("ativo", True):
        nome = f"Diário Oficial da União (últimos {cfg_dou.get('dias', 7)} dias)"
        col.situacao[nome] = "edital de abertura"
        try:
            col.por_fonte[nome] = oficiais.buscar_dou(cfg_dou, hoje)
        except RuntimeError as e:
            col.erros.append(f"DOU: {e}")

    for p in cfg_of.get("paginas", []):
        if not p.get("ativo", True):
            continue
        col.situacao[p["nome"]] = p.get("situacao", "")
        try:
            col.por_fonte[p["nome"]] = oficiais.buscar_pagina(p)
        except RuntimeError as e:
            col.erros.append(f"{p['nome']}: {e}")

    for editais in col.por_fonte.values():
        for e in editais:
            e.palavras_encontradas = encontrar_palavras(e.texto_busca, padroes)
    return col


def _fmt_item(e: Edital) -> str:
    rotulo = e.orgao
    detalhe = e.descricao.capitalize() if e.descricao else e.titulo
    if e.fonte == "DOU" and detalhe and normalizar(detalhe) not in normalizar(e.orgao):
        rotulo = f"{e.orgao}: {detalhe}"
    linha = f'• <a href="{esc(e.id)}">{esc(rotulo[:180])}</a>'
    if e.publicado:
        linha += f" ({e.publicado.strftime('%d/%m')})"
    if e.palavras_encontradas:
        linha += f" 🔎 {esc(', '.join(e.palavras_encontradas[:3]))}"
    return linha


def formatar(col: Coleta, termo: str = "", max_por_fonte: int = 25) -> str:
    termo_n = normalizar(termo)
    cab = "📜 <b>Editais em fontes oficiais</b>"
    if termo:
        cab += f"\nFiltro: <i>{esc(termo)}</i>"
    blocos = [cab]
    total = 0
    for fonte, editais in col.por_fonte.items():
        if termo_n:
            editais = [e for e in editais if termo_n in normalizar(e.texto_busca)]
        # palavras-chave primeiro; dentro de cada grupo, mantém a ordem da fonte (mais recentes)
        editais = sorted(editais, key=lambda e: not e.palavras_encontradas)
        situacao = col.situacao.get(fonte, "")
        titulo = f"🏛 <b>{esc(fonte)}</b>" + (f": {esc(situacao)}" if situacao else "")
        if not editais:
            blocos.append(f"{titulo}\nnada encontrado.")
            continue
        total += len(editais)
        linhas = [_fmt_item(e) for e in editais[:max_por_fonte]]
        if len(editais) > max_por_fonte:
            linhas.append(f"… e mais {len(editais) - max_por_fonte}. Use /editais <i>termo</i> para filtrar.")
        blocos.append(titulo + "\n" + "\n".join(linhas))
    if col.erros:
        blocos.append("⚠️ <b>Fontes indisponíveis agora</b>\n" + "\n".join(esc(e) for e in col.erros))
    if not total and not col.erros:
        blocos.append("Nenhum edital encontrado" + (" com esse filtro." if termo else "."))
    blocos.append("<i>Confira sempre o edital completo no link oficial antes de se inscrever.</i>")
    return "\n\n".join(blocos)


def tratar(texto: str, cfg: dict, hoje: date) -> str | None:
    """Recebe o texto da mensagem e devolve a resposta (ou None se não for comando)."""
    m = RE_COMANDO.match((texto or "").strip())
    if not m:
        return None
    cmd, arg = m.group(1).lower(), (m.group(2) or "").strip()
    if cmd in ("editais", "edital", "oficiais"):
        cfg_of = cfg.get("oficiais", {})
        return formatar(coletar(cfg, hoje), arg, cfg_of.get("max_por_fonte", 25))
    if cmd in ("start", "ajuda", "help"):
        return AJUDA
    return "Comando não reconhecido.\n\n" + AJUDA


def _processar(upd: dict, tg: Telegram, cfg: dict, hoje: date) -> None:
    msg = upd.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    texto = msg.get("text", "")
    if not chat_id or not texto.startswith("/"):
        return
    if chat_id not in tg.chats_autorizados:
        print(f"[aviso] comando ignorado de chat não autorizado {chat_id}")
        return
    tg.digitando(chat_id)
    resposta = tratar(texto, cfg, hoje)
    if resposta:
        tg.enviar(resposta, chat_id=chat_id)


def responder_pendentes(tg: Telegram, cfg: dict, hoje: date) -> int:
    """Responde aos comandos acumulados e confirma-os no Telegram. Retorna quantos tratou."""
    updates = tg.atualizacoes()
    for upd in updates:
        try:
            _processar(upd, tg, cfg, hoje)
        except Exception as e:  # um comando com erro não pode travar os outros
            print(f"[erro] ao tratar update {upd.get('update_id')}: {e}")
        finally:
            tg.atualizacoes(offset=upd["update_id"] + 1)  # confirma: não responde de novo
    return len(updates)


def escutar(tg: Telegram, cfg: dict, hoje_fn) -> None:
    tg.registrar_comandos(COMANDOS)
    print("[ok] bot escutando comandos (Ctrl+C para sair)")
    offset = None
    while True:
        try:
            updates = tg.atualizacoes(offset=offset, espera=50)
        except requests.RequestException as e:
            print(f"[aviso] {e}; tentando de novo em 10 s")
            time.sleep(10)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                _processar(upd, tg, cfg, hoje_fn())
            except Exception as e:
                print(f"[erro] ao tratar update {upd.get('update_id')}: {e}")
