from datetime import date
from pathlib import Path

import pytest

from radar import app
from radar.estado import Estado
from radar.fontes import noticias, pci
from radar.telegram import dividir
from radar.texto import compilar_palavras, encontrar_palavras

FIX = Path(__file__).parent / "fixtures"
BASE = "https://www.pciconcursos.com.br/concursos/norte/"
HOJE = date(2026, 11, 24)

CFG = {
    "pci": {"paginas": [{"url": BASE, "secao": "Norte"}], "ufs": ["PA", "AM", "Nacional"]},
    "area": {
        "exigir_palavra_chave": True,
        "verificar_pagina_detalhe": True,
        "palavras_chave": ["TI", "tecnologia da informação", "engenharia", "engenheiro"],
    },
    "lembretes": {"dias_antes_do_fim": 3},
    "noticias": {"ativo": False},
}


def listagem():
    return pci.parse_listagem((FIX / "pci_norte.html").read_text(encoding="utf-8"), BASE, "Norte")


def test_parse_listagem():
    cs = {c.orgao.split(" - ")[0]: c for c in listagem()}
    assert set(cs) == {"CRBM-4", "DPE", "Prefeitura de Belém", "SEPLAD"}

    crbm = cs["CRBM-4"]
    assert crbm.uf == "AM"
    assert crbm.vagas_salario == "1 vaga até R$ 2.765,11"
    assert crbm.cargos == "Agente Administrativo"
    assert crbm.escolaridade == "Ensino Médio"
    assert crbm.fim_inscricao == date(2026, 11, 27) and crbm.inicio_inscricao is None

    dpe = cs["DPE"]
    assert dpe.cargos_genericos
    assert (dpe.inicio_inscricao, dpe.fim_inscricao) == (date(2026, 11, 30), date(2027, 1, 4))

    belem = cs["Prefeitura de Belém"]
    assert belem.id == "https://www.pciconcursos.com.br/noticias/prefeitura-de-belem-pa-ti"
    assert belem.fim_inscricao == date(2026, 12, 10)
    assert "Tecnologia da Informação" in belem.cargos


def test_palavras_chave_sem_falso_positivo():
    p = compilar_palavras(["TI", "tecnologia da informação", "engenharia"])
    assert encontrar_palavras("Analista de TI", p) == ["TI"]
    assert encontrar_palavras("Analista de Tecnologia da Informacao", p) == ["tecnologia da informação"]
    assert encontrar_palavras("Gestão pública, contabilidade, ti-ti-ti", p) == []
    assert encontrar_palavras("Engenharia Elétrica", p) == ["engenharia"]


@pytest.fixture
def sem_rede(monkeypatch):
    monkeypatch.setattr(pci, "buscar", lambda paginas: listagem())
    detalhes = {
        "https://www.pciconcursos.com.br/noticias/dpe-am-abre-concurso": "Cargos: Analista em TI, Assistente",
        "https://www.pciconcursos.com.br/noticias/crbm-4-abre-concurso": "Agente administrativo",
        "https://www.pciconcursos.com.br/noticias/gestao-pa": "Contador e gestor",
    }
    monkeypatch.setattr(pci, "texto_da_noticia", lambda url: detalhes[url])
    monkeypatch.setattr(app.time, "sleep", lambda s: None)


def test_fluxo_completo(sem_rede, tmp_path):
    estado = Estado(tmp_path / "estado.json")

    # 1ª execução: resumo único com os relevantes (Belém por cargo, DPE pela página de detalhe)
    res = app.executar(CFG, estado, HOJE)
    nomes = {c.orgao.split(" - ")[0] for c in res.total_relevantes}
    assert nomes == {"Prefeitura de Belém", "DPE"}
    msgs = app.mensagens(res, HOJE, primeira=True)
    assert "Radar de concursos ativado" in msgs[0] and "Prefeitura de Belém" in msgs[0]
    estado.salvar()

    # 2ª execução igual: nada de novo
    estado = Estado(tmp_path / "estado.json")
    res = app.executar(CFG, estado, HOJE)
    assert not res.novos and not res.lembretes and not res.prorrogados
    assert app.mensagens(res, HOJE, primeira=False) == []
    estado.salvar()

    # 3ª execução perto do fim de Belém (10/12): lembrete, uma vez só
    estado = Estado(tmp_path / "estado.json")
    res = app.executar(CFG, estado, date(2026, 12, 8))
    assert [c.orgao for c in res.lembretes] == ["Prefeitura de Belém - PA"]
    assert "Prazo acabando" in app.mensagens(res, date(2026, 12, 8), False)[0]
    res = app.executar(CFG, estado, date(2026, 12, 9))
    assert not res.lembretes


def test_prorrogacao(sem_rede, tmp_path, monkeypatch):
    estado = Estado(tmp_path / "estado.json")
    app.executar(CFG, estado, HOJE)
    estado.salvar()

    prorrogada = listagem()
    for c in prorrogada:
        if c.orgao.startswith("Prefeitura"):
            c.fim_inscricao = date(2026, 12, 20)
    monkeypatch.setattr(pci, "buscar", lambda paginas: prorrogada)
    res = app.executar(CFG, Estado(tmp_path / "estado.json"), HOJE)
    assert [(c.orgao, antigo) for c, antigo in res.prorrogados] == [("Prefeitura de Belém - PA", "2026-12-10")]
    assert "prorrogadas" in app.mensagens(res, HOJE, False)[0]


def test_rss():
    xml = (FIX / "google_news.xml").read_text(encoding="utf-8")
    itens = noticias.parse_rss(xml, "concurso Pará")
    assert itens[0].titulo == "Concurso PCPA é autorizado com 237 vagas"
    assert itens[0].fonte == "O Liberal"
    assert itens[0].publicada == date(2026, 11, 23)


def test_dividir_mensagem():
    texto = "\n\n".join("x" * 1500 for _ in range(5))
    partes = dividir(texto)
    assert all(len(p) <= 4000 for p in partes) and len(partes) == 3
