# Monitor de Congressos & Publicações — Jully

Painel automático de **congressos, chamadas de trabalhos (CFP), periódicos e dossiês** nas áreas da Jully (metadados, ciência da informação, comunicação, Flusser, IA e humanidades digitais — Brasil + Ibero-América).

**Como funciona, em uma frase:** um robô do GitHub roda **toda segunda e quarta às 7h**, recalcula o que está aberto/encerrado, procura novas chamadas, **publica o painel atualizado no GitHub Pages** e **envia um e-mail** para a Jully — sem ninguém precisar fazer nada.

---

## Arquivos do projeto

| Arquivo | Para que serve |
|---|---|
| `index.html` | O painel (abre no navegador). Lê os dados de `events.json`. |
| `events.json` | A base de oportunidades. É o arquivo que o robô atualiza. |
| `last_update.json` | Marca a data/hora da última atualização (mostrada no topo do painel). |
| `update.py` | O robô: recalcula status, agrega as fontes, curadoria e dispara o e-mail. |
| `sources.json` | Lista de fontes (feeds, consultas DOAJ/OpenAlex/WikiCFP/Google). Adicionar fonte = editar aqui. |
| `requirements.txt` | Dependência do robô (`feedparser`). |
| `.github/workflows/update.yml` | O agendamento (seg/qua 7h) que roda tudo automaticamente. |
| `.gitignore` | Arquivos que não devem ir para o GitHub. |

---

## Passo a passo (faz uma vez só)

### 1. Criar o repositório e subir os arquivos
1. Em https://github.com/new, crie um repositório **público** (ex.: `monitor-congressos-jully`). Público é necessário para o GitHub Pages gratuito.
2. Suba **todos** os arquivos desta pasta, **mantendo a pasta `.github/workflows/`**. Duas formas:
   - **Pela web:** botão *Add file → Upload files*, arraste os arquivos. ⚠️ O upload pela web às vezes não cria a pasta `.github`; se acontecer, use *Add file → Create new file* e digite o caminho `.github/workflows/update.yml` (o GitHub cria as pastas) e cole o conteúdo.
   - **Pelo Git (recomendado):**
     ```bash
     git init
     git add .
     git commit -m "Monitor de congressos - versao inicial"
     git branch -M main
     git remote add origin https://github.com/SEU-USUARIO/monitor-congressos-jully.git
     git push -u origin main
     ```

### 2. Ativar o GitHub Pages (o site)
1. No repositório: **Settings → Pages**.
2. Em *Build and deployment → Source*, escolha **Deploy from a branch**.
3. Branch: **main**, pasta: **/ (root)**. Salve.
4. Após ~1 minuto, o painel estará em: `https://SEU-USUARIO.github.io/monitor-congressos-jully/`
   (esse é o link para mandar para a Jully).

### 3. Configurar o e-mail automático (Secrets)
O robô envia o e-mail pela conta Gmail usando uma **senha de app** (não é a senha normal).

1. Gere a senha de app: conta Google → **Segurança → Verificação em duas etapas** (precisa estar ativa) → **Senhas de app** → crie uma para "Mail". Copie os 16 caracteres.
2. No repositório: **Settings → Secrets and variables → Actions → New repository secret**. Crie **três** secrets:

   | Nome do secret | Valor |
   |---|---|
   | `GMAIL_USER` | o Gmail que vai **enviar** (ex.: `seuendereco@gmail.com`) |
   | `GMAIL_APP_PASSWORD` | a senha de app de 16 caracteres (sem espaços) |
   | `MAIL_TO` | o e-mail da Jully (pode pôr vários separados por vírgula) |

   > Sem esses secrets, tudo funciona normalmente — só o envio de e-mail é pulado.

### 4. O agendamento já está pronto
O arquivo `.github/workflows/update.yml` já agenda **segundas e quartas às 10:00 UTC = 07:00 de Brasília**. Não precisa fazer nada além de tê-lo subido no passo 1.

---

## Como testar agora (sem esperar a segunda-feira)
1. No repositório, aba **Actions**.
2. Clique no workflow **"Atualizar Monitor de Congressos"** → botão **Run workflow** → **Run**.
3. Em ~1 minuto o job aparece. Clique nele e veja os logs (deve terminar com `[ok] total=...`).

## Como saber se a atualização automática funcionou
Quatro sinais, em ordem de confiança:
1. **Aba Actions:** o workflow aparece com ✅ verde nas segundas e quartas.
2. **Commits automáticos:** aparece um commit *"Atualização automática: …"* feito por `github-actions[bot]` (só quando houve mudança nos dados).
3. **E-mail:** a Jully recebe o digest naquela manhã.
4. **Painel:** o texto *"Última atualização"* no topo do site mostra a data/hora recentes.

> Dica: o GitHub pode atrasar ou pausar o `cron` em repositórios sem atividade por ~60 dias. Se isso acontecer, basta rodar uma vez pelo *Run workflow* que ele volta a agendar.

---

## Como a Jully usa o painel
- **Filtra** por status (abertos/monitorar/sempre aberto/encerrados), tipo, idioma, área (chips) e busca livre.
- **"✕ Não me interessa"** em qualquer card: o item some do painel (fica guardado no navegador dela). Ela vai limpando até sobrar só o que importa.
- **"Mostrar arquivados"** + **"↩︎ Restaurar"**: para rever ou trazer de volta um item.
- A seção **🔥 Prioridades** destaca prazos nos próximos 45 dias.

> O "não me interessa" é salvo **no navegador da Jully** (não no GitHub). Como cada oportunidade tem um identificador fixo, a escolha dela **continua valendo** mesmo depois das atualizações automáticas.

---

## De onde vêm os dados (agregador multi-fonte)
- **Base curada e verificada** (o alicerce): congressos e revistas reais da área, com prazos conferidos — ENANCIB, ISKO, DCMI/Dublin Core, CIM/UNAM, Intercom, Flusser Studies, Compós, AAHD, periódicos de CI/Comunicação etc.
- **Status automático:** a cada execução, itens com prazo vencido viram "Encerrado" e os vigentes ficam "Aberto", sozinhos.
- **Coleta automática de várias fontes** (definidas em `sources.json`, todas sem chave):
  - **Feeds RSS/Atom** de associações (Intercom, Compós, ANCIB, ISKO, HDH) e de revistas OJS;
  - **DOAJ** — catálogo de revistas de acesso aberto por assunto (ótimo para *onde publicar*);
  - **OpenAlex** — descoberta de periódicos/venues por tema;
  - **WikiCFP** — chamadas por categoria.
- Cada fonte é tolerante a falha: se uma cair, as outras seguem.

### Camadas opcionais (ligam sozinhas se você cadastrar a chave)
Estas duas melhoram muito a qualidade/cobertura, mas **não são obrigatórias** — sem a chave, o robô simplesmente as ignora.

1. **Curadoria por IA** — a IA lê os itens novos, descarta o que não tem a ver, resume em uma frase e pontua relevância (só entram itens com nota ≥ 55).
   - Crie a chave em https://console.anthropic.com → *API Keys* (precisa de um método de pagamento; o custo aqui é de centavos/mês).
   - Cadastre como secret **`ANTHROPIC_API_KEY`**.
   - Sem ela, a curadoria usa um filtro por palavras-chave (funciona, com mais ruído).

2. **Busca web ampla (Google Custom Search)** — varre a web além das fontes fixas.
   - Crie a chave em https://console.cloud.google.com (ative *Custom Search API*) e um mecanismo em https://programmablesearchengine.google.com (configurado para "buscar em toda a web"); pegue o **ID do mecanismo**.
   - Cadastre os secrets **`GOOGLE_API_KEY`** e **`GOOGLE_CSE_ID`**. A cota gratuita (100 buscas/dia) cobre nosso uso.

> Quando quiser ativar qualquer uma, me chame que eu te guio clique a clique para criar a chave.

### Para adicionar uma fonte nova
Edite `sources.json` (uma linha em `rss_feeds`, ou um termo em `doaj_queries`/`google_cse_queries`) e dê commit.

### Para adicionar uma oportunidade na mão
Edite `events.json` (siga o formato de um item existente; o `id` precisa ser único) e dê commit.
