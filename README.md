# Radar de Concursos 🔔

Monitora concursos públicos e avisa no **Telegram**. Roda de graça no **GitHub Actions**, 3× por dia, sem precisar do seu PC ligado.

## O que ele faz

| Notificação | Origem |
|---|---|
| 🆕 **Concurso novo** com inscrições abertas (ou prestes a abrir) que bate com seus filtros | Listagens do PCI Concursos (Norte + Nacional) |
| ⏰ **Prazo acabando** (padrão: faltando ≤ 3 dias) | idem |
| 🔁 **Inscrições prorrogadas** | idem |
| 📰 **Concursos previstos/autorizados**: notícias recentes | RSS de busca do Google News |
| 📜 **`/editais`** (sob demanda): editais abertos em **fontes oficiais** | Diário Oficial da União + sites das bancas (CETAP, Cesgranrio) |

Filtros padrão (`config.yaml`): Pará e demais UFs do Norte, mais os nacionais, só cargos de **TI/Engenharia**.
Quando o cargo aparece como "Vários Cargos", o radar abre a notícia e procura as palavras-chave no texto completo. O resultado fica em cache.

Na **primeira execução** chega uma única mensagem de resumo com tudo o que já está aberto. Depois disso, só novidades.

## Configuração (≈10 min)

### 1. Crie o bot
1. No Telegram, fale com **@BotFather** → `/newbot` → escolha nome e usuário.
2. Guarde o **token** (`123456:ABC...`).
3. Abra a conversa com o seu bot e mande um "oi".

### 2. Descubra seu chat_id
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123456:ABC..."      # PowerShell: $env:TELEGRAM_BOT_TOKEN="..."
python -m radar --descobrir-chat
```

### 3. Teste localmente
```bash
export TELEGRAM_CHAT_ID="987654321"
python -m radar --teste                         # mensagem de teste no Telegram
python -m radar --dry-run --estado /tmp/e.json  # roda tudo, só imprime (não mexe no estado real)
```

### 4. Suba para o GitHub
1. Crie um repositório (pode ser **privado**) e faça push deste projeto.
2. **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **Actions → Radar de concursos → Run workflow** para a primeira execução.

A partir daí ele roda sozinho às 07:17, 12:17 e 18:17 (horário de Belém). Para mudar, edite o `cron` em `.github/workflows/radar.yml` (horário em UTC).

## Comandos no Telegram

| Comando | O que faz |
|---|---|
| `/editais` | Lista os editais abertos nas **fontes oficiais**. Os que batem com suas palavras-chave vêm primeiro, marcados com 🔎 |
| `/editais <termo>` | Só os que citam o termo no texto do edital. Ex.: `/editais engenharia`, `/editais Pará`, `/editais professor` |
| `/ajuda` | Lista de comandos |

**Fontes oficiais consultadas** (`oficiais` no `config.yaml`):
- **Diário Oficial da União, Seção 3**: publicações dos últimos 7 dias com "edital de abertura" (concursos e seleções federais, universidades, institutos federais, conselhos). O radar lê o texto integral de cada edital para filtrar por cargo e descarta retificações, convocações, homologações e licitações.
- **CETAP**: página de inscrições abertas da banca.
- **Cesgranrio**: concursos em andamento.
- **FGV**: vem desativada, porque a lista "em andamento" do site inclui concursos antigos.

O bot só responde aos chats definidos em `TELEGRAM_CHAT_ID` (aceita vários ids separados por vírgula). Mensagens de outras pessoas são ignoradas.

**Onde os comandos são respondidos.** Escolha **uma** das opções. As duas juntas disputam as mensagens do bot.

1. **GitHub Actions** (padrão, grátis, sem PC ligado): o workflow `.github/workflows/comandos.yml` verifica os comandos a cada 30 min, então a resposta pode levar até ~30 min. Em repositório privado isso consome cerca de 1.500 dos 2.000 min/mês gratuitos. Em repositório público é ilimitado, e dá para trocar o `cron` por `*/10 * * * *`.
2. **Resposta imediata**: deixe rodando num PC, Raspberry Pi ou servidor e desative o workflow `Comandos do Telegram` em **Actions**:
   ```bash
   python -m radar --bot
   ```

Para ver a resposta no terminal, sem Telegram: `python -m radar --editais` ou `python -m radar --editais engenharia`.

> Rode `--descobrir-chat` **antes** de ativar os comandos: depois disso as mensagens já foram lidas pelo bot e não aparecem mais lá.

## Personalizando

Tudo fica em `config.yaml`:
- `pci.ufs`: inclua `PA` sozinho se quiser só o Pará.
- `area.palavras_chave`: adicione ou remova cargos. Siglas em maiúsculas (ex.: `TI`) só casam como palavra inteira e em caixa alta.
- `area.exigir_palavra_chave: false`: recebe tudo da região, com as palavras-chave apenas destacadas.
- `noticias.consultas`: buscas do Google News para o radar de previstos.

Para acrescentar o site de outra banca ao `/editais`, adicione uma entrada em `oficiais.paginas` com `nome`, `url` (a página que lista os concursos) e `padrao_link`, um regex que casa com o endereço dos links de cada concurso. Teste com `python -m radar --editais`. Sites que só carregam o conteúdo via JavaScript (ex.: Cebraspe) não funcionam com esse método.

Para acrescentar outra região do PCI, adicione uma entrada em `pci.paginas` (ex.: `https://www.pciconcursos.com.br/concursos/nordeste/`) e as UFs em `pci.ufs`.

## Estrutura

```
radar/
  __main__.py      CLI (--dry-run, --teste, --descobrir-chat, --editais, --responder, --bot)
  app.py           regras: novos, lembretes, prorrogações; formatação das mensagens
  comandos.py      comandos do Telegram (/editais, /ajuda)
  fontes/oficiais.py  Diário Oficial da União + páginas das bancas
  fontes/pci.py    parser das listagens do PCI (não depende de classes CSS)
  fontes/noticias.py  RSS do Google News
  estado.py        data/estado.json (o que já foi notificado)
  telegram.py      envio com divisão de mensagens e tratamento de flood (429)
tests/             pytest com HTML/RSS de exemplo
```

```bash
pip install pytest && python -m pytest -q
```

## Observações
- O estado é salvo por commit no próprio repositório. Isso também mantém o repo "ativo", e o GitHub não desativa o agendamento por inatividade.
- Se o PCI sair do ar ou mudar o layout a ponto de o parser não reconhecer nada, você recebe um ⚠️ no Telegram e a execução fica vermelha no Actions.
- Os dados vêm de sites de terceiros. Confirme sempre no edital oficial.
