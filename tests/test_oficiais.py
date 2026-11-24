from datetime import date
from pathlib import Path

import pytest

from radar import comandos
from radar.fontes import oficiais
from radar.modelos import Edital
from radar.telegram import dividir

FIX = Path(__file__).parent / "fixtures"
HOJE = date(2026, 11, 24)
CFG = {
    "area": {"palavras_chave": ["TI", "engenharia"]},
    "oficiais": {
        "dou": {"ativo": True, "dias": 2},
        "paginas": [{"nome": "Banca X", "situacao": "inscrições abertas",
                     "url": "https://www.exemplo.org.br/index/abertos/", "padrao_link": r"/informacoes/\d+"}],
    },
}


def test_parse_dou_filtra_e_identifica_orgao():
    editais = oficiais.parse_dou((FIX / "dou_busca.html").read_text(encoding="utf-8"))
    # retificação e licitação ficam de fora
    assert [e.orgao for e in editais] == ["Universidade Federal do Pará", "Ministério da Agricultura e Pecuária"]
    ufpa = editais[0]
    assert ufpa.id == "https://www.in.gov.br/web/dou/-/edital-n-12-de-20-de-novembro-de-2026-111"
    assert ufpa.publicado == date(2026, 11, 23)
    assert "<span" not in ufpa.resumo and "CONCURSO PÚBLICO" in ufpa.resumo


def test_parse_dou_layout_mudou():
    with pytest.raises(RuntimeError):
        oficiais.parse_dou("<html><body>sem resultados</body></html>")


@pytest.mark.parametrize("texto, titulo, esperado", [
    ("EDITAL Nº 259, DE 19 DE NOVEMBRO DE 2026 ABERTURA DE SELEÇÃO PÚBLICA PARA PROFESSOR SUBSTITUTO "
     "A Reitora da Universidade Federal de Santa Maria, no uso...",
     "EDITAL Nº 259, DE 19 DE NOVEMBRO DE 2026", "ABERTURA DE SELEÇÃO PÚBLICA PARA PROFESSOR SUBSTITUTO"),
    ("EDITAL Nº 3 PROCESSO SELETIVO SIMPLIFICADO PARA PROFESSOR SUBSTITUTO O DIRETOR-GERAL DO CAMPUS PONTA PORÃ "
     "do Instituto Federal...", "EDITAL Nº 3", "PROCESSO SELETIVO SIMPLIFICADO PARA PROFESSOR SUBSTITUTO"),
    ("Edital A DIRETORA-GERAL DA SECRETARIA DO TRIBUNAL torna público...", "Edital", ""),
])
def test_ementa(texto, titulo, esperado):
    assert oficiais.ementa(texto, titulo) == esperado


def test_parse_pagina_de_banca():
    html = (FIX / "banca.html").read_text(encoding="utf-8")
    editais = oficiais.parse_pagina(html, "https://www.exemplo.org.br/index/abertos/", "Banca X",
                                    r"/informacoes/\d+", "inscrições abertas")
    assert [(e.id, e.titulo[:30]) for e in editais] == [
        ("https://www.exemplo.org.br/informacoes/168/", "Concurso Público nº 001/2025 -"),
        ("https://www.exemplo.org.br/informacoes/170/", "Processo Seletivo - SECRETARIA"),
    ]
    assert all(e.fonte == "Banca X" and e.situacao == "inscrições abertas" for e in editais)


@pytest.fixture
def fontes_falsas(monkeypatch):
    dou = [
        Edital(id="https://dou/1", titulo="EDITAL Nº 1", orgao="Universidade Federal do Pará", fonte="DOU",
               publicado=date(2026, 11, 23), resumo="concurso para professor de história",
               descricao="ABERTURA DE CONCURSO PÚBLICO"),
        Edital(id="https://dou/2", titulo="EDITAL Nº 2", orgao="Ministério X", fonte="DOU",
               publicado=date(2026, 11, 20), resumo="processo seletivo para analista de TI & <redes>"),
    ]
    monkeypatch.setattr(oficiais, "buscar_dou", lambda cfg, hoje: [Edital(**vars(e)) for e in dou])

    def pagina(cfg):
        raise RuntimeError("Falha ao baixar https://www.exemplo.org.br/index/abertos/: timeout")
    monkeypatch.setattr(oficiais, "buscar_pagina", pagina)


def test_comando_editais(fontes_falsas):
    resp = comandos.tratar("/editais", CFG, HOJE)
    linhas = resp.splitlines()
    # quem bate com as palavras-chave vem primeiro e marcado
    i_ti = next(i for i, l in enumerate(linhas) if "https://dou/2" in l)
    i_ufpa = next(i for i, l in enumerate(linhas) if "https://dou/1" in l)
    assert i_ti < i_ufpa and "🔎 TI" in linhas[i_ti]
    assert "Universidade Federal do Pará: Abertura de concurso público" in linhas[i_ufpa]
    # fonte fora do ar vira aviso, não erro
    assert "Fontes indisponíveis" in resp and "Banca X" in resp


def test_comando_editais_com_termo(fontes_falsas):
    resp = comandos.tratar("/editais@MeuRadarBot professor", CFG, HOJE)
    assert "https://dou/1" in resp and "https://dou/2" not in resp
    assert "Filtro: <i>professor</i>" in resp


def test_outros_comandos():
    assert comandos.tratar("oi", CFG, HOJE) is None
    assert "/editais" in comandos.tratar("/start", CFG, HOJE)
    assert comandos.tratar("/xyz", CFG, HOJE).startswith("Comando não reconhecido")


class TelegramFalso:
    chats_autorizados = {"111"}

    def __init__(self, updates):
        self.updates, self.enviadas, self.confirmados = updates, [], []

    def atualizacoes(self, offset=None, espera=0):
        if offset is not None:
            self.confirmados.append(offset)
            return []
        return self.updates

    def digitando(self, chat_id):
        pass

    def enviar(self, texto, chat_id=None):
        self.enviadas.append((chat_id, texto))


def test_responder_pendentes_so_para_chat_autorizado(fontes_falsas):
    tg = TelegramFalso([
        {"update_id": 10, "message": {"chat": {"id": 111}, "text": "/editais"}},
        {"update_id": 11, "message": {"chat": {"id": 999}, "text": "/editais"}},  # estranho
        {"update_id": 12, "message": {"chat": {"id": 111}, "text": "bom dia"}},
    ])
    assert comandos.responder_pendentes(tg, CFG, HOJE) == 3
    assert [c for c, _ in tg.enviadas] == ["111"]
    assert tg.confirmados[-1] == 13  # tudo confirmado: não responde de novo na próxima execução


def test_dividir_bloco_grande_nao_corta_tags():
    bloco = "\n".join(f'• <a href="https://x/{i}">Item {i} {"y" * 80}</a>' for i in range(100))
    partes = dividir("Cabeçalho\n\n" + bloco)
    assert len(partes) > 1
    for p in partes:
        assert len(p) <= 4000 and p.count("<a ") == p.count("</a>")
