"""Uso:
    python -m radar                 # execução normal (envia ao Telegram)
    python -m radar --dry-run       # imprime as mensagens no terminal, não envia
    python -m radar --teste         # envia uma mensagem de teste ao Telegram
    python -m radar --descobrir-chat  # mostra o chat_id de quem falou com o bot
    python -m radar --editais [termo] # imprime os editais das fontes oficiais
    python -m radar --responder     # responde os comandos pendentes do Telegram e sai
    python -m radar --bot           # fica ligado respondendo comandos na hora
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml

from . import comandos
from .app import hoje_local, rodar
from .estado import Estado
from .telegram import Telegram


def descobrir_chat() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Defina TELEGRAM_BOT_TOKEN primeiro.")
        return 1
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    chats = {}
    for upd in r.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")
    if not chats:
        print("Nenhuma mensagem encontrada. Mande um 'oi' para o bot no Telegram e rode de novo.")
        return 1
    for cid, nome in chats.items():
        print(f"chat_id={cid}  ({nome})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="radar", description="Radar de concursos públicos")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--estado", default="data/estado.json")
    p.add_argument("--dry-run", action="store_true", help="não envia nada, só imprime")
    p.add_argument("--teste", action="store_true", help="envia mensagem de teste")
    p.add_argument("--descobrir-chat", action="store_true")
    p.add_argument("--editais", nargs="?", const="", metavar="TERMO",
                   help="imprime os editais das fontes oficiais (sem Telegram)")
    p.add_argument("--responder", action="store_true",
                   help="responde os comandos pendentes do Telegram e sai")
    p.add_argument("--bot", action="store_true", help="fica escutando comandos do Telegram")
    a = p.parse_args()

    if a.descobrir_chat:
        return descobrir_chat()

    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    if a.editais is not None:
        print(comandos.tratar(f"/editais {a.editais}", cfg, hoje_local()))
        return 0

    tg = Telegram(dry_run=a.dry_run)
    if a.teste:
        tg.registrar_comandos(comandos.COMANDOS)
        tg.enviar("🔔 Teste do <b>Radar de Concursos</b>: o bot está funcionando!\nMande /editais para ver os editais abertos.")
        return 0
    if a.responder:
        n = comandos.responder_pendentes(tg, cfg, hoje_local())
        print(f"[ok] {n} atualização(ões) processada(s)")
        return 0
    if a.bot:
        try:
            comandos.escutar(tg, cfg, hoje_local)
        except KeyboardInterrupt:
            pass
        return 0

    estado = Estado(Path(a.estado))
    return rodar(cfg, estado, tg)


if __name__ == "__main__":
    sys.exit(main())
