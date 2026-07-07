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

## Passo 4 — Banco de dados PostgreSQL

O bot cria automaticamente as tabelas na primeira execução:

- `produtos` — catálogo de produtos únicos por (fonte, url)
- `historico_precos` — série histórica de preço/avaliação por produto
- `notificacoes` — registro de cada notificação enviada (usado para
  evitar reenvio e para dedução de desconto real)

No Railway, adicione o plugin **PostgreSQL** ao projeto — a variável
`DATABASE_URL` é criada automaticamente.

---

## Passo 5 — Deploy no Railway

1. Crie conta em https://railway.app
2. **New Project → Deploy from GitHub repo**
3. Adicione o plugin **PostgreSQL**
4. Em **Variables**, adicione todas as variáveis do `env.example`
   (`DATABASE_URL` já vem preenchida pelo plugin)
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
