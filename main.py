# -*- coding: utf-8 -*-
"""
Bot de Promocoes - Amazon, Magalu, Shopee e Americanas
Monitora ofertas a cada 2h, guarda historico de precos no PostgreSQL e notifica
no Telegram apenas descontos reais (vs média movel de 30 dias) com qualidade
minima garantida (nota, avaliacoes e marca).
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime

import httpx
import asyncpg
import anthropic
from apify_client import ApifyClient

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuração (variáveis de ambiente)
# ─────────────────────────────────────────────
APIFY_TOKEN       = os.environ["APIFY_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
DATABASE_URL      = os.environ["DATABASE_URL"]

# ─────────────────────────────────────────────
# Filtros de negócio
# ─────────────────────────────────────────────
PRECO_MAXIMO           = 2000.00
DESCONTO_MINIMO_PCT    = 20.0     # desconto real vs média de 30 dias
AVALIACAO_MINIMA       = 4.0
NUM_AVALIACOES_MINIMO  = 50
MIN_HISTORICO_REGISTROS = 10      # registros históricos antes de poder notificar
JANELA_MEDIA_DIAS      = 30

PALAVRAS_SUPLEMENTO = [
    "suplemento", "whey", "creatina", "vitamina", "proteina", "proteína",
    "bcaa", "colageno", "colágeno", "termogenico", "termogênico", "pre treino",
    "pré-treino", "glutamina", "multivitaminico", "multivitamínico",
]
PALAVRAS_ELETRONICO = [
    "eletron", "eletrôn", "celular", "smartphone", "notebook", "laptop", " tv ",
    "fone de ouvido", "fone bluetooth", "carregador", "tablet", "smartwatch",
    "câmera", "camera", "caixa de som", "soundbar", "console", "videogame",
]

# ─────────────────────────────────────────────
# Fontes monitoradas (páginas de ofertas de cada marketplace)
# Ajuste estas URLs/keywords e os actors do Apify conforme necessário.
# ─────────────────────────────────────────────
AMAZON_URLS_OFERTAS = [
    "https://www.amazon.com.br/deals",
]
MAGALU_URLS_OFERTAS = [
    "https://www.magazineluiza.com.br/selecao/ofertasdodia/",
]
AMERICANAS_TERMOS_OFERTAS = [
    "ofertas",
]
SHOPEE_KEYWORDS_OFERTAS = [
    "oferta relampago",
]

MAX_ITENS_POR_FONTE = 30


# ─────────────────────────────────────────────
# Helpers de normalização (schemas de actors variam)
# ─────────────────────────────────────────────

def _texto(item: dict, *chaves: str) -> str:
    for chave in chaves:
        valor = item.get(chave)
        if valor not in (None, ""):
            return str(valor).strip()
    return ""


def _parse_preco_brl(valor) -> float:
    if isinstance(valor, bool):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        texto = str(valor).replace("R$", "").strip()
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        return float(texto)
    except Exception:
        return 0.0


def _parse_preco_shopee(valor) -> float:
    """A API da Shopee costuma retornar o preço numérico em centavos."""
    if isinstance(valor, bool):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor) / 100
    return _parse_preco_brl(valor)


def _extrair_avaliacao(item: dict) -> float:
    for chave in ("rating", "stars", "ratingValue", "avgRating", "productRating"):
        valor = item.get(chave)
        if isinstance(valor, (int, float)):
            return float(valor)
    aninhado = item.get("itemRating") or item.get("item_rating")
    if isinstance(aninhado, dict):
        for chave in ("rating_star", "ratingStar", "rating"):
            valor = aninhado.get(chave)
            if isinstance(valor, (int, float)):
                return float(valor)
    return 0.0


def _extrair_num_avaliacoes(item: dict) -> int:
    for chave in ("reviewsCount", "reviewCount", "ratingsTotal", "totalRatings", "numReviews"):
        valor = item.get(chave)
        if isinstance(valor, (int, float)):
            return int(valor)
    aninhado = item.get("itemRating") or item.get("item_rating")
    if isinstance(aninhado, dict):
        valor = aninhado.get("rating_count") or aninhado.get("ratingCount")
        if isinstance(valor, list):
            return sum(v for v in valor if isinstance(v, (int, float)))
        if isinstance(valor, (int, float)):
            return int(valor)
    return 0


def _normalizar_item(item: dict, fonte: str, parse_preco) -> dict:
    preco_raw = (
        item.get("price") or item.get("salePrice") or item.get("currentPrice")
        or item.get("discountedPrice") or 0
    )
    return {
        "fonte": fonte,
        "nome": _texto(item, "title", "name", "productName")[:200],
        "marca": _texto(item, "brand", "manufacturer"),
        "categoria": _texto(item, "category", "categoryName", "breadCrumbs"),
        "preco": parse_preco(preco_raw),
        "avaliacao": _extrair_avaliacao(item),
        "num_avaliacoes": _extrair_num_avaliacoes(item),
        "url": _texto(item, "url", "link", "productUrl", "itemUrl"),
    }


# ─────────────────────────────────────────────
# 1. COLETA (Apify)
# ─────────────────────────────────────────────

def coletar_amazon() -> list[dict]:
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Amazon...")
    try:
        run = client.actor("dtrungtin/amazon-scraper").call(run_input={
            "startUrls": [{"url": u} for u in AMAZON_URLS_OFERTAS],
            "maxItems": MAX_ITENS_POR_FONTE,
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return [_normalizar_item(i, "Amazon", _parse_preco_brl) for i in items]
    except Exception as e:
        log.error(f"Erro Amazon: {e}")
        return []


def coletar_magalu() -> list[dict]:
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Magalu...")
    try:
        run = client.actor("stealth_mode/magazineluiza-product-search-scraper").call(run_input={
            "startUrls": MAGALU_URLS_OFERTAS,
            "maxItemsPerUrl": MAX_ITENS_POR_FONTE,
        })
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        return [_normalizar_item(i, "Magazine Luiza", _parse_preco_brl) for i in items]
    except Exception as e:
        log.error(f"Erro Magalu: {e}")
        return []


def coletar_shopee() -> list[dict]:
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Shopee...")
    todos = []
    for keyword in SHOPEE_KEYWORDS_OFERTAS:
        try:
            run = client.actor("gio21/shopee-scraper").call(run_input={
                "keyword": keyword,
                "country": "BR",
                "maxItems": MAX_ITENS_POR_FONTE,
            })
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            todos.extend(_normalizar_item(i, "Shopee", _parse_preco_shopee) for i in items)
        except Exception as e:
            log.error(f"Erro Shopee keyword {keyword}: {e}")
    return todos


def coletar_americanas() -> list[dict]:
    # Nota: este actor (VTEX Catalog API) não retorna avaliação/num_avaliacoes,
    # então produtos da Americanas nunca vão passar no filtro de nota mínima
    # até que uma fonte com essa informação seja adicionada.
    client = ApifyClient(APIFY_TOKEN)
    log.info("Coletando Americanas...")
    todos = []
    for termo in AMERICANAS_TERMOS_OFERTAS:
        try:
            run = client.actor("gio21/americanas-product-scraper").call(run_input={
                "searchTerm": termo,
                "maxItems": MAX_ITENS_POR_FONTE,
                "onlyAvailable": True,
            })
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            todos.extend(_normalizar_item(i, "Americanas", _parse_preco_brl) for i in items)
        except Exception as e:
            log.error(f"Erro Americanas termo {termo}: {e}")
    return todos


# ─────────────────────────────────────────────
# 2. FILTROS
# ─────────────────────────────────────────────

def _contem_palavra(texto: str, palavras: list[str]) -> bool:
    texto = f" {texto.lower()} "
    return any(p in texto for p in palavras)


def eh_exclusao_sem_marca(produto: dict) -> bool:
    """Suplementos e eletrônicos sem marca identificada são excluídos."""
    if produto["marca"]:
        return False
    contexto = f"{produto['categoria']} {produto['nome']}"
    return _contem_palavra(contexto, PALAVRAS_SUPLEMENTO) or _contem_palavra(contexto, PALAVRAS_ELETRONICO)


# ─────────────────────────────────────────────
# 3. BANCO DE DADOS (PostgreSQL)
# ─────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS produtos (
    id SERIAL PRIMARY KEY,
    fonte TEXT NOT NULL,
    url TEXT NOT NULL,
    nome TEXT NOT NULL,
    marca TEXT,
    categoria TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fonte, url)
);

CREATE TABLE IF NOT EXISTS historico_precos (
    id SERIAL PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    preco NUMERIC(10,2) NOT NULL,
    avaliacao NUMERIC(2,1),
    num_avaliacoes INTEGER,
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_historico_produto_data ON historico_precos (produto_id, coletado_em);

CREATE TABLE IF NOT EXISTS notificacoes (
    id SERIAL PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    preco_notificado NUMERIC(10,2) NOT NULL,
    desconto_pct NUMERIC(5,2) NOT NULL,
    enviado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notificacoes_produto ON notificacoes (produto_id, enviado_em);
"""


async def garantir_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(DDL)


async def upsert_produto(pool: asyncpg.Pool, produto: dict) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO produtos (fonte, url, nome, marca, categoria)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (fonte, url) DO UPDATE SET
                nome = EXCLUDED.nome,
                marca = EXCLUDED.marca,
                categoria = EXCLUDED.categoria,
                atualizado_em = now()
            RETURNING id
            """,
            produto["fonte"], produto["url"], produto["nome"],
            produto["marca"] or None, produto["categoria"] or None,
        )


async def obter_estatisticas(pool: asyncpg.Pool, produto_id: int) -> tuple[int, float | None]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                COUNT(*) AS total,
                AVG(preco) FILTER (
                    WHERE coletado_em >= now() - interval '{JANELA_MEDIA_DIAS} days'
                ) AS media_janela
            FROM historico_precos
            WHERE produto_id = $1
            """,
            produto_id,
        )
    media = float(row["media_janela"]) if row["media_janela"] is not None else None
    return row["total"], media


async def inserir_historico(pool: asyncpg.Pool, produto_id: int, produto: dict):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO historico_precos (produto_id, preco, avaliacao, num_avaliacoes)
            VALUES ($1, $2, $3, $4)
            """,
            produto_id, produto["preco"], produto["avaliacao"] or None,
            produto["num_avaliacoes"] or None,
        )


async def obter_ultimo_preco_notificado(pool: asyncpg.Pool, produto_id: int) -> float | None:
    async with pool.acquire() as conn:
        valor = await conn.fetchval(
            """
            SELECT preco_notificado FROM notificacoes
            WHERE produto_id = $1
            ORDER BY enviado_em DESC
            LIMIT 1
            """,
            produto_id,
        )
    return float(valor) if valor is not None else None


async def registrar_notificacao(pool: asyncpg.Pool, produto_id: int, preco: float, desconto_pct: float):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notificacoes (produto_id, preco_notificado, desconto_pct)
            VALUES ($1, $2, $3)
            """,
            produto_id, preco, desconto_pct,
        )


# ─────────────────────────────────────────────
# 4. RESUMO COM CLAUDE
# ─────────────────────────────────────────────

async def gerar_resumo_ia(client: anthropic.AsyncAnthropic, produto: dict) -> str:
    prompt = (
        "Gere um resumo de UMA linha curta (máximo 20 palavras) para ajudar um "
        "consumidor a decidir se vale a pena comprar esta promoção. Responda "
        "apenas com a frase, sem aspas e sem introdução.\n\n"
        f"Produto: {produto['nome']}\n"
        f"Marca: {produto['marca'] or 'não informada'}\n"
        f"Categoria: {produto['categoria'] or 'não informada'}\n"
        f"Preço atual: R$ {produto['preco']:.2f}\n"
        f"Desconto real vs média de {JANELA_MEDIA_DIAS} dias: {produto['desconto_pct']:.0f}%\n"
        f"Avaliação: {produto['avaliacao']:.1f} estrelas ({produto['num_avaliacoes']} avaliações)"
    )
    try:
        resp = await client.messages.create(
            model="claude-opus-4-8",
            max_tokens=100,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        texto = next((b.text for b in resp.content if b.type == "text"), "").strip()
        return texto or "Promoção detectada."
    except Exception as e:
        log.error(f"Erro ao gerar resumo IA: {e}")
        return "Resumo indisponível."


# ─────────────────────────────────────────────
# 5. TELEGRAM
# ─────────────────────────────────────────────

def formatar_mensagem(produto: dict) -> str:
    return (
        f"🛒 *{produto['nome']}*\n"
        f"💰 Preço atual: R$ {produto['preco']:.2f}\n"
        f"🔻 Desconto real: *{produto['desconto_pct']:.0f}%* (vs média de {JANELA_MEDIA_DIAS} dias)\n"
        f"⭐ {produto['avaliacao']:.1f} ({produto['num_avaliacoes']} avaliações) · 🏪 {produto['fonte']}\n"
        f"💡 {produto['resumo_ia']}\n"
        f"🔗 {produto['url']}"
    )


async def enviar_telegram(client: httpx.AsyncClient, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

async def processar_produto(pool, anthropic_client, http_client, produto: dict) -> bool:
    """Retorna True se uma notificação foi enviada."""
    produto_id = await upsert_produto(pool, produto)
    total_registros, media_30d = await obter_estatisticas(pool, produto_id)
    await inserir_historico(pool, produto_id, produto)

    if total_registros < MIN_HISTORICO_REGISTROS or media_30d is None or media_30d <= 0:
        return False

    desconto_pct = (media_30d - produto["preco"]) / media_30d * 100

    if produto["preco"] > PRECO_MAXIMO:
        return False
    if desconto_pct < DESCONTO_MINIMO_PCT:
        return False
    if produto["avaliacao"] < AVALIACAO_MINIMA:
        return False
    if produto["num_avaliacoes"] < NUM_AVALIACOES_MINIMO:
        return False

    ultimo_preco_notificado = await obter_ultimo_preco_notificado(pool, produto_id)
    if ultimo_preco_notificado is not None and produto["preco"] >= ultimo_preco_notificado:
        return False

    produto["desconto_pct"] = desconto_pct
    produto["resumo_ia"] = await gerar_resumo_ia(anthropic_client, produto)

    await enviar_telegram(http_client, formatar_mensagem(produto))
    await registrar_notificacao(pool, produto_id, produto["preco"], desconto_pct)
    return True


async def executar():
    log.info("=== Iniciando ciclo do bot de promoções ===")

    pool = await asyncpg.create_pool(DATABASE_URL)
    await garantir_schema(pool)

    todos: list[dict] = []
    for fn in (coletar_amazon, coletar_magalu, coletar_shopee, coletar_americanas):
        try:
            itens = await asyncio.to_thread(fn)
            todos.extend(itens)
        except Exception as e:
            log.error(f"Erro na coleta {fn.__name__}: {e}")

    log.info(f"Total coletado: {len(todos)} itens")

    validos = [
        p for p in todos
        if p["nome"] and p["url"] and p["preco"] > 0 and not eh_exclusao_sem_marca(p)
    ]
    log.info(f"Válidos após filtros básicos: {len(validos)}")

    if not validos:
        log.info("Nenhum produto válido neste ciclo.")
        await pool.close()
        return

    anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    notificados = 0

    async with httpx.AsyncClient(timeout=15) as http_client:
        for produto in validos:
            try:
                if await processar_produto(pool, anthropic_client, http_client, produto):
                    notificados += 1
                    await asyncio.sleep(1.5)  # evita flood no Telegram
            except Exception as e:
                log.error(f"Erro ao processar produto '{produto.get('nome')}': {e}")

    await pool.close()
    log.info(f"=== Ciclo concluído: {notificados} notificações enviadas ===")


if __name__ == "__main__":
    asyncio.run(executar())
