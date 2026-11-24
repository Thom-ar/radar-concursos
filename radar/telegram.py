from __future__ import annotations

import html
import json
import os
import time

import requests

LIMITE = 4000  # Telegram aceita 4096; deixamos folga


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, dry_run: bool = False):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.dry_run = dry_run
        if not dry_run and not (self.token and self.chat_id):
            raise SystemExit("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (ou use --dry-run).")

    @property
    def chats_autorizados(self) -> set[str]:
        """TELEGRAM_CHAT_ID aceita vários ids separados por vírgula."""
        return {c.strip() for c in self.chat_id.split(",") if c.strip()}

    def _api(self, metodo: str, timeout: int = 30, **dados):
        r = requests.post(
            f"https://api.telegram.org/bot{self.token}/{metodo}", data=dados, timeout=timeout
        )
        if r.status_code == 429:  # flood control
            espera = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(espera + 1)
            return self._api(metodo, timeout=timeout, **dados)
        r.raise_for_status()
        return r.json()

    def atualizacoes(self, offset: int | None = None, espera: int = 0) -> list[dict]:
        """getUpdates. Chamar com offset = último update_id + 1 confirma os anteriores."""
        dados = {"timeout": espera, "allowed_updates": '["message"]'}
        if offset is not None:
            dados["offset"] = offset
        return self._api("getUpdates", timeout=espera + 15, **dados).get("result", [])

    def digitando(self, chat_id: str) -> None:
        if self.dry_run:
            return
        try:
            self._api("sendChatAction", chat_id=chat_id, action="typing")
        except requests.RequestException:
            pass

    def registrar_comandos(self, comandos: list[tuple[str, str]]) -> None:
        """Mostra os comandos no menu "/" do Telegram."""
        if self.dry_run:
            return
        lista = [{"command": c, "description": d} for c, d in comandos]
        self._api("setMyCommands", commands=json.dumps(lista, ensure_ascii=False))

    def enviar(self, texto: str, chat_id: str | None = None) -> None:
        destinos = [chat_id] if chat_id else sorted(self.chats_autorizados)
        for parte in dividir(texto):
            if self.dry_run:
                print("─" * 60 + "\n" + parte)
                continue
            for destino in destinos:
                self._api(
                    "sendMessage",
                    chat_id=destino,
                    text=parte,
                    parse_mode="HTML",
                    disable_web_page_preview="true",
                )
                time.sleep(1.1)  # evita limite de ~1 msg/s por chat


def dividir(texto: str, limite: int = LIMITE) -> list[str]:
    """Quebra em blocos (separados por linha em branco) sem passar do limite.

    Um bloco que sozinho passa do limite é quebrado por linha, para não cortar
    uma tag HTML ao meio (o Telegram rejeitaria a mensagem).
    """
    partes, atual = [], ""

    def acrescentar(trecho: str, sep: str) -> None:
        nonlocal atual
        candidato = f"{atual}{sep}{trecho}" if atual else trecho
        if len(candidato) <= limite:
            atual = candidato
            return
        if atual:
            partes.append(atual)
        atual = trecho[:limite]

    for bloco in texto.split("\n\n"):
        if len(bloco) <= limite:
            acrescentar(bloco, "\n\n")
        else:
            for i, linha in enumerate(bloco.split("\n")):
                acrescentar(linha, "\n\n" if i == 0 else "\n")
    if atual:
        partes.append(atual)
    return partes
