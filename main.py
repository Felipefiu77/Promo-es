"""
Agente Autônomo de Promoções — MEI Comércio / Mercado Livre
Monitora Amazon, Magalu e Shopee, filtra margem > 15% e envia no Telegram.
"""

import os
import json
import asyncio
import logging
import httpx
from datetime import datetime
from apify_client import ApifyClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configurações (via variáveis de ambiente)
# ─────────────────────────────────────────────
APIFY_TOKEN       = os.environ["APIFY_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]   # ID do grupo (ex: -100123456789)

# Parâmetros MEI / ML
DAS_MENSAL        = 87.05
PEDIDOS_MES       = int(os.getenv("PEDIDOS_MES", "40"))
TAXA_ML_PCT       = 0.16       # Clássico
TAXA_ML_FIXO      = 6.00
MARGEM_MINIMA     = 0.15       # 15%

# Categorias que você vende
CATEGORIAS = [
    "eletrônicos", "esporte e lazer", "moda", "casa e jardim", "beleza e saúde"
]


# ─────────────────────────────────────────────
# 1. COLETA DE PROMOÇÕES (Apify)
# ─────────────────────────────────────────────

def coletar_amazon() -> list[dict]:
    """Coleta ofertas do dia na Amazon Brasil via Apify."""
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Amazon...")
    run = client.actor("vaclavrut/amazon-product-scraper").call(run_input={
        "country": "BR",
        "searchKeywords": CATEGORIAS,
        "maxItemsPerSearch": 10,
        "useDealFilter": True,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return [
        {
            "fonte": "Amazon",
            "nome": i.get("title", "")[:80],
            "preco": float(i.get("price", {}).get("value") or 0),
            "preco_original": float(i.get("listPrice", {}).get("value") or 0),
            "url": i.get("url", ""),
            "categoria": i.get("breadCrumbs", [""])[0],
        }
        for i in items if i.get("price", {}).get("value")
    ]


def coletar_magalu() -> list[dict]:
    """Coleta ofertas do Magazine Luiza via Apify."""
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Magalu...")
    run = client.actor("epctex/magazine-luiza-scraper").call(run_input={
        "startUrls": [
            {"url": "https://www.magazineluiza.com.br/oferta-do-dia/"},
        ],
        "maxItems": 40,
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return [
        {
            "fonte": "Magazine Luiza",
            "nome": i.get("name", "")[:80],
            "preco": float(i.get("price") or 0),
            "preco_original": float(i.get("originalPrice") or 0),
            "url": i.get("url", ""),
            "categoria": i.get("category", ""),
        }
        for i in items if i.get("price")
    ]


def coletar_shopee() -> list[dict]:
    """Coleta flash deals da Shopee via Apify."""
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Shopee...")
    run = client.actor("epctex/shopee-scraper").call(run_input={
        "startUrls": [
            {"url": "https://shopee.com.br/flash_sale"},
        ],
        "maxItems": 40,
        "country": "BR",
    })
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return [
        {
            "fonte": "Shopee",
            "nome": i.get("name", "")[:80],
            "preco": float(i.get("price") or 0),
            "preco_original": float(i.get("originalPrice") or 0),
            "url": i.get("url", ""),
            "categoria": i.get("catName", ""),
        }
        for i in items if i.get("price")
    ]


# ─────────────────────────────────────────────
# 2. ANÁLISE DE MARGEM (local, sem IA)
# ─────────────────────────────────────────────

def calcular_margem(preco_compra: float, preco_venda: float) -> dict:
    """
    Calcula margem líquida para MEI Comércio revendendo no ML.
    Preço de venda sugerido = preco_compra * 1.5 (markup 50%) se não informado.
    """
    if preco_venda <= 0:
        preco_venda = preco_compra * 1.5

    taxa_ml     = preco_venda * TAXA_ML_PCT + TAXA_ML_FIXO
    das_rateado = DAS_MENSAL / PEDIDOS_MES
    custo_total = preco_compra + taxa_ml + das_rateado
    lucro       = preco_venda - custo_total
    margem      = lucro / preco_venda if preco_venda > 0 else 0
    roi         = lucro / preco_compra if preco_compra > 0 else 0

    return {
        "preco_compra":  round(preco_compra, 2),
        "preco_venda":   round(preco_venda, 2),
        "taxa_ml":       round(taxa_ml, 2),
        "das_rateado":   round(das_rateado, 2),
        "lucro":         round(lucro, 2),
        "margem":        round(margem, 4),
        "roi":           round(roi, 4),
        "viavel":        margem >= MARGEM_MINIMA,
    }


# ─────────────────────────────────────────────
# 3. ANÁLISE QUALITATIVA COM CLAUDE
# ─────────────────────────────────────────────

async def analisar_com_ia(produtos: list[dict]) -> list[dict]:
    """
    Envia lote de produtos para o Claude avaliar potencial de revenda.
    Retorna lista com campo 'analise_ia' preenchido.
    """
    if not produtos:
        return []

    lista = "\n".join(
        f"{i+1}. [{p['fonte']}] {p['nome']} — R$ {p['preco_compra']:.2f} "
        f"(venda sugerida R$ {p['preco_venda']:.2f}, margem {p['margem']*100:.1f}%)"
        for i, p in enumerate(produtos)
    )

    prompt = f"""Você é especialista em revenda no Mercado Livre para MEI Comércio.
Avalie cada produto abaixo para revenda no ML nas categorias: {', '.join(CATEGORIAS)}.

Para cada produto diga em UMA frase curta:
- Se tem boa demanda no ML
- Qualquer risco (ex: muita concorrência, produto sazonal, difícil de enviar)

Responda em JSON: [{{"id": 1, "resumo": "..."}}]
Somente JSON, sem texto fora.

Produtos:
{lista}"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"].strip()

    try:
        avaliacoes = {a["id"]: a["resumo"] for a in json.loads(text)}
    except Exception:
        avaliacoes = {}

    for i, p in enumerate(produtos):
        p["analise_ia"] = avaliacoes.get(i + 1, "Análise indisponível")

    return produtos


# ─────────────────────────────────────────────
# 4. FORMATAÇÃO DA MENSAGEM
# ─────────────────────────────────────────────

def formatar_mensagem(produto: dict) -> str:
    desconto = ""
    if produto.get("preco_original") and produto["preco_original"] > produto["preco_compra"]:
        pct = (1 - produto["preco_compra"] / produto["preco_original"]) * 100
        desconto = f"  🔻 -{pct:.0f}% do preço original\n"

    return (
        f"🛒 *{produto['nome']}*\n"
        f"📦 Fonte: {produto['fonte']}\n"
        f"💰 Compra: R$ {produto['preco_compra']:.2f}{' → ' + desconto.strip() if desconto else ''}\n"
        f"🏷️ Venda sugerida ML: R$ {produto['preco_venda']:.2f}\n"
        f"📊 Margem líquida: *{produto['margem']*100:.1f}%* | ROI: {produto['roi']*100:.1f}%\n"
        f"💡 {produto['analise_ia']}\n"
        f"🔗 {produto['url']}"
    )


def formatar_resumo(aprovados: int, analisados: int) -> str:
    hora = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *Agente ML — {hora}*\n"
        f"Analisados: {analisados} | ✅ Aprovados: {aprovados}\n"
        f"Filtro: margem > {MARGEM_MINIMA*100:.0f}% após DAS R${DAS_MENSAL} e taxa ML\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


# ─────────────────────────────────────────────
# 5. ENVIO PARA TELEGRAM
# ─────────────────────────────────────────────

async def enviar_telegram(texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": texto,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        })
    if resp.status_code != 200:
        log.warning(f"Telegram erro: {resp.text}")


# ─────────────────────────────────────────────
# 6. PIPELINE PRINCIPAL
# ─────────────────────────────────────────────

async def executar():
    log.info("=== Iniciando ciclo do agente ===")

    # Coleta
    todos = []
    for fn in [coletar_amazon, coletar_magalu, coletar_shopee]:
        try:
            todos.extend(fn())
        except Exception as e:
            log.error(f"Erro na coleta {fn.__name__}: {e}")

    log.info(f"Total coletado: {len(todos)} produtos")
    if not todos:
        log.warning("Nenhum produto coletado. Encerrando ciclo.")
        return

    # Calcula margem e filtra viáveis
    for p in todos:
        m = calcular_margem(p["preco"], p.get("preco_original", 0))
        p.update(m)

    viaveis = [p for p in todos if p["viavel"]]
    log.info(f"Viáveis (margem >{MARGEM_MINIMA*100:.0f}%): {len(viaveis)}")

    if not viaveis:
        log.info("Nenhum produto viável neste ciclo.")
        return

    # Análise qualitativa com IA (em lotes de 10)
    analisados = []
    for i in range(0, len(viaveis), 10):
        lote = viaveis[i:i+10]
        try:
            analisados.extend(await analisar_com_ia(lote))
        except Exception as e:
            log.error(f"Erro na análise IA: {e}")
            for p in lote:
                p["analise_ia"] = "Análise indisponível"
            analisados.extend(lote)

    # Ordena por margem (maiores primeiro)
    analisados.sort(key=lambda x: x["margem"], reverse=True)

    # Envia resumo
    await enviar_telegram(formatar_resumo(len(analisados), len(todos)))
    await asyncio.sleep(1)

    # Envia cada produto
    for produto in analisados:
        msg = formatar_mensagem(produto)
        await enviar_telegram(msg)
        await asyncio.sleep(1.5)   # evita flood no Telegram

    log.info("=== Ciclo concluído ===")


if __name__ == "__main__":
    asyncio.run(executar())
