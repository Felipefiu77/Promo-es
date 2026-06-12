# Agente de Promoções — MEI Comércio / Mercado Livre

Monitora promoções da Amazon, Magazine Luiza e Shopee a cada 2 horas,
filtra os produtos com margem acima de 15% para revenda no ML (já descontando
DAS R$ 87,05 e taxa ML 16% + R$ 6,00) e envia automaticamente no grupo do Telegram.

---

## Passo 1 — Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot` e escolha um nome (ex: `Agente ML Promoções`)
3. Copie o token gerado (ex: `123456789:AAFxxx...`)
4. Crie um grupo no Telegram e adicione o bot como membro
5. Para pegar o ID do grupo, acesse no navegador:
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
   e copie o campo `"id"` dentro de `"chat"` (começa com `-100`)

---

## Passo 2 — Criar conta no Apify

1. Acesse https://apify.com e crie uma conta gratuita
2. Vá em **Settings → API & Integrations** e copie o token
3. O plano gratuito oferece $5/mês de créditos — suficiente para testes
4. Para uso contínuo a cada 2h, o plano Starter (~$49/mês) é recomendado

---

## Passo 3 — Obter chave da API Claude

1. Acesse https://console.anthropic.com
2. Vá em **API Keys** e crie uma nova chave
3. Copie e guarde com segurança

---

## Passo 4 — Deploy no Railway

1. Crie conta em https://railway.app (plano Hobby ~$5/mês)
2. Crie um novo projeto: **New Project → Deploy from GitHub repo**
3. Conecte este repositório
4. Vá em **Variables** e adicione todas as variáveis do `.env.example`
5. Configure o cron job em **Settings → Cron Jobs**:
   - Expressão: `0 */2 * * *` (executa a cada 2 horas)

---

## Estrutura dos arquivos

```
agente_promocoes/
├── main.py           # Script principal
├── requirements.txt  # Dependências Python
├── railway.toml      # Configuração Railway
├── .env.example      # Modelo de variáveis de ambiente
└── README.md         # Este arquivo
```

---

## Como o agente funciona

```
A cada 2 horas:
  1. Coleta promoções → Amazon + Magalu + Shopee (via Apify)
  2. Calcula margem → preco_compra → taxa ML (16% + R$6) → DAS rateado
  3. Filtra → apenas produtos com margem > 15%
  4. Analisa com IA → Claude avalia demanda e riscos de cada produto
  5. Envia no Telegram → resumo + card formatado por produto
```

---

## Exemplo de mensagem no Telegram

```
━━━━━━━━━━━━━━━━━━━━━
🤖 Agente ML — 10/06/2025 14:00
Analisados: 87 | ✅ Aprovados: 6
Filtro: margem > 15% após DAS R$87.05 e taxa ML
━━━━━━━━━━━━━━━━━━━━━

🛒 Fone Bluetooth XYZ
📦 Fonte: Amazon
💰 Compra: R$ 45.90
🏷️ Venda sugerida ML: R$ 89.90
📊 Margem líquida: 22.3% | ROI: 34.1%
💡 Alta demanda no ML, categoria competitiva mas com volume alto de vendas.
🔗 https://amazon.com.br/...
```

---

## Ajustes no código

Para mudar o filtro de margem mínima, edite `main.py`:
```python
MARGEM_MINIMA = 0.15   # 15% → mude para 0.20 para exigir 20%
PEDIDOS_MES   = 40     # estimativa de pedidos/mês para rateio do DAS
```
