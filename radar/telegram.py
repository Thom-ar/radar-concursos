from __future__ import annotations

import html
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

    def _api(self, metodo: str, **dados):
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{metodo}", data=dados, timeout=30)
        if r.status_code == 429:  # flood control
            espera = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(espera + 1)
            return self._api(metodo, **dados)
        r.raise_for_status()
        return r.json()

    def enviar(self, texto: str) -> None:
        for parte in dividir(texto):
            if self.dry_run:
                print("─" * 60 + "\n" + parte)
                continue
            self._api(
                "sendMessage",
                chat_id=self.chat_id,
                text=parte,
                parse_mode="HTML",
                disable_web_page_preview="true",
            )
            time.sleep(1.1)  # evita limite de ~1 msg/s por chat


def dividir(texto: str, limite: int = LIMITE) -> list[str]:
    """Quebra em blocos (separados por linha em branco) sem passar do limite."""
    partes, atual = [], ""
    for bloco in texto.split("\n\n"):
        candidato = f"{atual}\n\n{bloco}" if atual else bloco
        if len(candidato) <= limite:
            atual = candidato
        else:
            if atual:
                partes.append(atual)
            atual = bloco[:limite]
    if atual:
        partes.append(atual)
    return partes
