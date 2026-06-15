import re, json, os, sys
from datetime import datetime, timezone
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright nao instalado")
    sys.exit(1)

PRODUCTS = [
    {"search": "Projetor HY320 Davely Smart TV Android", "link": "https://meli.la/1yBfiUy"},
    {"search": "Whey Protein Concentrado 1kg Chocolate Dark Lab", "link": "https://meli.la/2LMdTFf"},
    {"search": "Lavadora Lava Jato Portatil Pressao 2 Baterias MyMotors", "link": "https://meli.la/19ErgKc"},
    {"search": "Whey Pro Max Titanium Concentrado 1kg", "link": "https://meli.la/25unFmR"},
    {"search": "Bota Bull Terrier Bruce Masculina Couro", "link": "https://meli.la/1RuihHY"},
    {"search": "Smart TV AOC 50 4K DLED 50U7045", "link": "https://meli.la/2u6hu7K"},
]

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    window.chrome = {runtime: {}};
"""


def extract_float(text):
    if not text:
        return None
    cleaned = text.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    m = re.search(r'(\d+\.\d{2})', cleaned)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+)', cleaned)
    if m:
        return float(m.group(1))
    return None


def extract_card_prices(card_data):
    amounts = card_data.get("amounts", [])
    installments_text = card_data.get("installments", "")
    price_val, orig_val, inst_qty, inst_amt = None, None, 0, 0

    for amt in amounts:
        val = extract_float(amt["text"])
        if not val:
            continue
        if "previous" in amt["cls"]:
            orig_val = val
        elif "cents-superscript" in amt["cls"] and price_val is None:
            price_val = val

    if installments_text:
        flat = installments_text.replace(" ", "")
        m = re.search(r'(\d+)x(?:R?\$?\s*)?([\d.,]+)', flat)
        if m:
            inst_qty = int(m.group(1))
            cleaned = m.group(2).replace(".", "").replace(",", ".")
            m2 = re.search(r'(\d+\.\d{2})', cleaned)
            inst_amt = float(m2.group(1)) if m2 else float(cleaned)

    return {"price": price_val, "original_price": orig_val, "installments_qty": inst_qty, "installments_amount": inst_amt}


def extract_ml_ids(url):
    ml_product_id, ml_item_id = "", ""
    m = re.search(r'/p/(MLB\d+)', url)
    if m:
        ml_product_id = m.group(1)
    m = re.search(r'[?&]wid=(MLB\d+)', url)
    if m:
        ml_item_id = m.group(1)
    m = re.search(r'item_id%3D(MLB\d+)', url)
    if m:
        ml_item_id = m.group(1)
    m = re.search(r'/MLB-(\d+)', url)
    if m:
        ml_item_id = f"MLB{m.group(1)}"
    return ml_product_id, ml_item_id


def scrape_product_price(page, url, max_wait=3):
    """Visita a pagina do produto e extrai o preco real.
    Retorna dict com price, original_price, installments ou None se bloqueado."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(max_wait * 1000)

        body = page.inner_text("body")
        if "seguran" in body.lower():
            return None

        prices = page.evaluate("""
            () => {
                const meta = document.querySelector('meta[itemprop="price"]');
                const metaPrice = meta ? parseFloat(meta.getAttribute('content')) : null;

                const containers = document.querySelectorAll('[class*="ui-pdp-price"]');
                let mainContainer = null;
                for (const c of containers) {
                    if (c.innerText.trim().length > 0 && c.innerText.includes('R$')) {
                        mainContainer = c; break;
                    }
                }
                let prevPrice = null, currentPrice = null;
                if (mainContainer) {
                    const prev = mainContainer.querySelector('[class*="andes-money-amount--previous"]');
                    if (prev) prevPrice = prev.innerText.trim().replace(/\\s+/g, ' ');
                    const curr = mainContainer.querySelector('[class*="andes-money-amount--cents-superscript"]');
                    if (curr) currentPrice = curr.innerText.trim().replace(/\\s+/g, ' ');
                }

                let installmentsText = '';
                const allInst = document.querySelectorAll('[class*="price__installments"]');
                for (const el of allInst) {
                    const txt = el.innerText.trim().replace(/\\s+/g, ' ');
                    if (txt.includes('x') && txt.includes('R$')) { installmentsText = txt; break; }
                }
                return { metaPrice, prevPrice, currentPrice, installmentsText };
            }
        """)
        if not prices.get("metaPrice") and not prices.get("currentPrice"):
            return None

        price_val = prices.get("metaPrice") or extract_float(prices.get("currentPrice", ""))
        orig_val = extract_float(prices.get("prevPrice", ""))
        inst_qty, inst_amt = 0, 0
        if prices.get("installmentsText"):
            flat = prices["installmentsText"].replace(" ", "")
            m = re.search(r'(\d+)x(?:R?\$?\s*)?([\d.,]+)', flat)
            if m:
                inst_qty = int(m.group(1))
                cleaned = m.group(2).replace(".", "").replace(",", ".")
                m2 = re.search(r'(\d+\.\d{2})', cleaned)
                inst_amt = float(m2.group(1)) if m2 else float(cleaned)
        return {"price": price_val, "original_price": orig_val, "installments_qty": inst_qty, "installments_amount": inst_amt}
    except:
        return None


def make_product_url(prod):
    """Tenta construir uma URL de pagina de produto a partir dos dados disponiveis."""
    # Se ja tem uma URL /p/MLB, usa ela
    url = prod.get("productUrl", "")
    if "/p/MLB" in url:
        return url.split("?")[0]
    # Se tem mlProductId, constroi URL limpa
    if prod.get("mlProductId"):
        return f"https://www.mercadolivre.com.br/p/{prod['mlProductId']}"
    # Se tem mlItemId e parece uma listing page, tenta
    if prod.get("mlItemId") and prod["mlItemId"].startswith("MLB"):
        return f"https://produto.mercadolivre.com.br/MLB-{prod['mlItemId'][3:]}-_JM"
    return url.split("?")[0] if url else ""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        # -- PASSO 1: Desktop context para descobrir produtos dos cards --
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}, locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
            device_scale_factor=1.0,
        )
        page = context.new_page()
        page.add_init_script(STEALTH_SCRIPT)

        seen_urls = set()
        all_products = []

        page.goto(PRODUCTS[0]["link"], wait_until="domcontentloaded", timeout=30000)
        time.sleep(1.5)
        page.wait_for_selector("[class*='poly-card']", timeout=15000)

        for prod in PRODUCTS:
            try:
                page.goto(prod["link"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("[class*='poly-card']", timeout=15000)
                time.sleep(1.5)
            except:
                print(f"  AVISO: {prod['search'][:40]}... sem cards")
                continue

            found = page.evaluate("""
                () => {
                    const cards = document.querySelectorAll('[class*="poly-card"]');
                    return Array.from(cards).map(c => {
                        const title = c.querySelector('.poly-component__title');
                        const img = c.querySelector('.poly-component__picture');
                        const amts = c.querySelectorAll('.andes-money-amount');
                        const inst = c.querySelector('.poly-price__installments');
                        return {
                            title: title ? title.innerText.trim() : '',
                            href: title ? title.href : '',
                            image: img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '',
                            amounts: Array.from(amts).map(a => ({
                                text: a.innerText.trim().replace(/\\s+/g, ' '),
                                cls: a.className
                            })),
                            installments: inst ? inst.innerText.trim().replace(/\\s+/g, ' ') : ''
                        };
                    });
                }
            """)

            for card in found[:5]:
                url_key = card.get("href", "").split("?")[0]
                if not url_key or url_key in seen_urls:
                    continue
                seen_urls.add(url_key)

                prices = extract_card_prices(card)
                if not prices["price"]:
                    continue

                ml_product_id, ml_item_id = extract_ml_ids(card.get("href", ""))
                all_products.append({
                    "title": card.get("title", ""),
                    "link": prod["link"],
                    "productUrl": card.get("href", ""),
                    "image": card.get("image", ""),
                    "price_card": prices["price"],
                    "original_price_card": prices["original_price"],
                    "installments_qty_card": prices["installments_qty"],
                    "installments_amount_card": prices["installments_amount"],
                    "mlProductId": ml_product_id,
                    "mlItemId": ml_item_id,
                })

            print(f"  {prod['search'][:40]}... {len(found)} cards, {len(all_products)} unicos")

        page.close()
        context.close()

        if not all_products:
            print("Nenhum produto encontrado!")
            return

        # -- PASSO 2: Scraping das paginas reais dos produtos --
        # Usa um context fresh (mobile-like evita mais captchas)
        print(f"\n>>> Scraping precos reais de {len(all_products)} produtos...")
        ctx2 = browser.new_context(
            viewport={"width": 375, "height": 812}, locale="pt-BR",
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            device_scale_factor=3.0,
            is_mobile=True, has_touch=True,
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )
        page2 = ctx2.new_page()
        page2.add_init_script(STEALTH_SCRIPT)

        # Primeiro visita um meli.la pra setar cookies
        try:
            page2.goto(PRODUCTS[0]["link"], wait_until="domcontentloaded", timeout=30000)
            time.sleep(1.5)
        except:
            pass

        ok_count = 0
        block_count = 0
        for prod in all_products:
            url = make_product_url(prod)
            if not url:
                print(f"  SEM URL: {prod['title'][:50]}")
                continue

            result = scrape_product_price(page2, url, max_wait=3)
            if result and result.get("price"):
                prod["price"] = result["price"]
                prod["original_price"] = result["original_price"] or prod.get("original_price_card")
                prod["installments_qty"] = result["installments_qty"]
                prod["installments_amount"] = result["installments_amount"]
                ok_count += 1
                print(f"  OK: R${result['price']} <- {prod['title'][:50]}")
            else:
                # Fallback: usa preco do card
                prod["price"] = prod.get("price_card")
                prod["original_price"] = prod.get("original_price_card")
                prod["installments_qty"] = prod.get("installments_qty_card", 0)
                prod["installments_amount"] = prod.get("installments_amount_card", 0)
                block_count += 1
                print(f"  CARD: R${prod['price_card']} (bloqueado) <- {prod['title'][:50]}")

        # Se mobile falhou pra muitos, tenta desktop com cookie priming
        if block_count > ok_count and ok_count < 3:
            print(f"\n>>> Mobile bloqueou muito, tentando desktop...")
            ctx3 = browser.new_context(
                viewport={"width": 1920, "height": 1080}, locale="pt-BR",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
            )
            page3 = ctx3.new_page()
            page3.add_init_script(STEALTH_SCRIPT)

            try:
                page3.goto(PRODUCTS[0]["link"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(1.5)
            except:
                pass

            for prod in all_products:
                # So tenta de novo os que falharam
                if prod.get("price") and prod["price"] == prod.get("price_card"):
                    url = make_product_url(prod)
                    if url:
                        result = scrape_product_price(page3, url, max_wait=3)
                        if result and result.get("price"):
                            prod["price"] = result["price"]
                            prod["original_price"] = result["original_price"] or prod.get("original_price_card")
                            prod["installments_qty"] = result["installments_qty"]
                            prod["installments_amount"] = result["installments_amount"]
                            print(f"  DESKTOP OK: R${result['price']} <- {prod['title'][:50]}")
                        else:
                            print(f"  DESKTOP BLOQ: {prod['title'][:50]}")

            page3.close()
            ctx3.close()

        page2.close()
        ctx2.close()
        browser.close()

    # -- PASSO 3: Calcular derivados e salvar --
    for prod in all_products:
        if not prod.get("original_price") or prod.get("original_price", 0) <= prod.get("price", 0):
            prod["original_price"] = round(prod["price"] * 1.15, 2)
        prod["discount"] = round((1 - prod["price"] / prod["original_price"]) * 100) if prod["original_price"] > 0 else 0
        prod["pix_price"] = round(prod["price"] * 0.9, 2)

        # Remove campos temporarios do card
        for key in ["price_card", "original_price_card", "installments_qty_card", "installments_amount_card"]:
            prod.pop(key, None)

    # Ordenar por desconto (maior primeiro)
    all_products.sort(key=lambda x: x.get("discount", 0), reverse=True)

    # Salvar produtos.json
    path = os.path.join(repo_root, "produtos.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "products": all_products}, f, ensure_ascii=False, indent=2)

    # Salvar prices.json (legado)
    prices_data = [{
        "search": p["title"],
        "link": p["link"],
        "price": p["price"],
        "original_price": p["original_price"],
        "discount": p["discount"],
        "pix_price": p["pix_price"],
        "installments_qty": p["installments_qty"],
        "installments_amount": p["installments_amount"],
    } for p in all_products]

    prices_path = os.path.join(repo_root, "prices.json")
    with open(prices_path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "prices": prices_data}, f, ensure_ascii=False, indent=2)

    print(f"\nSalvo: {path} ({len(all_products)} produtos)")
    print(f"Salvo: {prices_path} ({len(prices_data)} produtos)")


if __name__ == "__main__":
    main()
