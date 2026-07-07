# Bot de Promoções — Amazon, Magalu e Shopee

Monitora ofertas nesses três marketplaces a cada 2 horas, guarda o histórico
de preços no PostgreSQL e notifica no Telegram apenas promoções com desconto
real (comparado à média de preço dos últimos 30 dias) e qualidade mínima
garantida.

---

## Filtros aplicados

- Preço atual até **R$ 2.000**
- Desconto real ≥ **20%** sobre a média de preço dos últimos 30 dias
- Nota mínima de **4.0** estrelas com pelo menos **50 avaliações**
- Pelo menos **10 registros históricos** do produto antes de notificar (evita
  notificar com base em pouquíssimos dados)
- Suplementos e eletrônicos **sem marca identificada** são excluídos
- Um produto só é notificado de novo se o preço cair **ainda mais** que da
  última vez notificado (evita spam do mesmo produto a cada ciclo)

---

## Passo 1 — Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot` e escolha um nome
3. Copie o token gerado
4. Crie um grupo/canal no Telegram e adicione o bot como membro
5. Para pegar o ID do grupo, acesse no navegador:
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
   e copie o campo `"id"` dentro de `"chat"` (começa com `-100`)

---

## Passo 2 — Criar conta no Apify

1. Acesse https://apify.com e crie uma conta
2. Vá em **Settings → API & Integrations** e copie o token
3. Os actors usados por padrão (ajuste em `main.py` se necessário):
   - Amazon: `dtrungtin/amazon-scraper`
   - Magazine Luiza: `stealth_mode/magazineluiza-product-search-scraper`
   - Shopee: `gio21/shopee-scraper`

---

## Passo 3 — Obter chave da API Claude

1. Acesse https://console.anthropic.com
2. Vá em **API Keys** e crie uma nova chave

---

## Passo 4 — Criar o banco PostgreSQL no Railway

O bot cria automaticamente as tabelas na primeira execução:

- `produtos` — catálogo de produtos únicos por (fonte, url)
- `historico_precos` — série histórica de preço/avaliação por produto
- `notificacoes` — registro de cada notificação enviada (usado para
  evitar reenvio e para dedução de desconto real)

Você só precisa provisionar o banco vazio — o schema é criado pelo próprio
`main.py` (`garantir_schema`) a cada execução, de forma idempotente.

1. Acesse https://railway.app e abra o projeto onde o bot será hospedado
   (ou crie um novo projeto primeiro, conforme o Passo 5)
2. Clique em **+ New** (ou **Create** → **New**) dentro do projeto
3. Selecione **Database → Add PostgreSQL**
4. O Railway provisiona o banco em alguns segundos e cria automaticamente
   um serviço "Postgres" no projeto, com a variável `DATABASE_URL` já
   preenchida
5. Para conferir/copiar a connection string:
   - Clique no serviço **Postgres** criado
   - Vá na aba **Variables**
   - Copie o valor de `DATABASE_URL` (formato
     `postgresql://usuario:senha@host:porta/banco`)
6. Se o serviço do bot (`main.py`) estiver em um **serviço separado** do
   Postgres dentro do mesmo projeto, use uma **variável de referência** em
   vez de colar o valor fixo, para que ele sempre aponte para o banco
   correto:
   - No serviço do bot, vá em **Variables → New Variable**
   - Nome: `DATABASE_URL`
   - Valor: `${{Postgres.DATABASE_URL}}` (troque `Postgres` pelo nome exato
     do serviço de banco, visível na aba do projeto)
7. Faça o redeploy do serviço do bot para que a variável seja aplicada

---

## Passo 5 — Deploy no Railway

1. Crie conta em https://railway.app
2. **New Project → Deploy from GitHub repo**
3. Adicione o plugin **PostgreSQL** conforme o Passo 4, se ainda não tiver
   feito
4. Em **Variables** do serviço do bot, adicione todas as variáveis do
   `env.example` (`APIFY_TOKEN`, `ANTHROPIC_API_KEY`, `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID`, `DATABASE_URL`)
5. Configure o cron job em **Settings → Cron Jobs**:
   - Expressão: `0 */2 * * *` (executa a cada 2 horas)

---

## Estrutura dos arquivos

```
Promo-es/
├── main.py           # Script principal
├── requirements.txt  # Dependências Python
├── railway.toml      # Configuração Railway
├── env.example       # Modelo de variáveis de ambiente
└── README.md         # Este arquivo
```

---

## Como o bot funciona

```
A cada 2 horas:
  1. Coleta ofertas → Amazon + Magalu + Shopee (via Apify)
  2. Grava/atualiza cada produto e seu preço no PostgreSQL
  3. Calcula desconto real → preço atual vs média de 30 dias
  4. Filtra → preço, desconto, nota, avaliações, marca, histórico mínimo
  5. Gera resumo de uma linha com a API Claude
  6. Envia no Telegram com nome, preço, desconto real, resumo e link
```

---

## Ajustes no código

Os principais parâmetros ficam no topo de `main.py`:

```python
PRECO_MAXIMO            = 2000.00
DESCONTO_MINIMO_PCT     = 20.0
AVALIACAO_MINIMA        = 4.0
NUM_AVALIACOES_MINIMO   = 50
MIN_HISTORICO_REGISTROS = 10
JANELA_MEDIA_DIAS       = 30
```

As URLs/keywords de busca de cada marketplace estão em
`AMAZON_URLS_OFERTAS`, `MAGALU_URLS_OFERTAS` e `SHOPEE_KEYWORDS_OFERTAS`.
