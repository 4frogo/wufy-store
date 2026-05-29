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


def load_existing_prices():
    path = os.path.join(repo_root, "prices.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {p["search"]: p for p in data.get("prices", [])}
    except:
        return {}


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


def find_card_for_product(page, search_term):
    cards = page.query_selector_all("[class*='poly-card']")
    if not cards:
        return {}

    keywords = [w.lower() for w in search_term.split() if len(w) > 2]
    best, best_score = None, 0

    for card in cards:
        title_el = card.query_selector(".poly-component__title")
        if not title_el:
            continue
        title_text = title_el.inner_text().lower()
        score = sum(1 for kw in keywords if kw in title_text)
        if score > best_score:
            best_score = score
            best = card

    if not best:
        best = cards[0]

    result = best.evaluate("""
        card => {
            let amts = card.querySelectorAll('.andes-money-amount');
            let inst = card.querySelector('.poly-price__installments');
            let title = card.querySelector('.poly-component__title');
            return {
                title: title ? title.innerText.trim() : '',
                productUrl: title ? title.href : '',
                amounts: Array.from(amts).map(a => ({
                    text: a.innerText.trim().replace(/\\s+/g, ' '),
                    cls: a.className
                })),
                installments: inst ? inst.innerText.trim().replace(/\\s+/g, ' ') : ''
            };
        }
    """)
    return result


def extract_prices(amounts, installments_text):
    price_val = None
    orig_val = None
    inst_qty = 0
    inst_amt = 0

    for amt in amounts:
        if isinstance(amt, dict):
            text = amt["text"]
            cls = amt["cls"]
        else:
            text = amt.inner_text().strip().replace("\n", " ")
            cls = amt.get_attribute("class") or ""
        val = extract_float(text)
        if not val:
            continue
        if "previous" in cls:
            orig_val = val
        elif "cents-superscript" in cls:
            if price_val is None:
                price_val = val

    if installments_text:
        flat = installments_text.replace(" ", "")
        m = re.search(r'(\d+)x(?:R?\$?\s*)?([\d.,]+)', flat)
        if m:
            inst_qty = int(m.group(1))
            cleaned = m.group(2).replace(".", "").replace(",", ".")
            m2 = re.search(r'(\d+\.\d{2})', cleaned)
            inst_amt = float(m2.group(1)) if m2 else float(cleaned)

    if not price_val:
        for amt in amounts:
            text = amt["text"] if isinstance(amt, dict) else amt.inner_text()
            cls = amt["cls"] if isinstance(amt, dict) else (amt.get_attribute("class") or "")
            val = extract_float(text)
            if val and "previous" not in cls and "phrase" not in cls and "installments" not in cls:
                price_val = val
                break

    return {"price": price_val, "original_price": orig_val, "installments_qty": inst_qty, "installments_amount": inst_amt}


def scrape_real_product(page, product_url):
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(4)

        title = page.title()
        if "seguridad" in title.lower():
            return None

        prices = page.evaluate("""
            () => {
                const meta = document.querySelector('meta[itemprop="price"]');
                const metaPrice = meta ? parseFloat(meta.getAttribute('content')) : null;

                const containers = document.querySelectorAll('[class*="ui-pdp-price"]');
                let mainContainer = null;
                for (const c of containers) {
                    if (c.innerText.trim().length > 0 && c.innerText.includes('R$')) {
                        mainContainer = c;
                        break;
                    }
                }

                let prevPrice = null;
                let currentPrice = null;

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
                    if (txt.includes('x') && txt.includes('R$')) {
                        installmentsText = txt;
                        break;
                    }
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

        return {
            "price": price_val,
            "original_price": orig_val,
            "installments_qty": inst_qty,
            "installments_amount": inst_amt,
        }

    except Exception as e:
        return None


def main():
    existing = load_existing_prices()
    resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
            device_scale_factor=1.0,
        )
        page = context.new_page()
        page.add_init_script(STEALTH_SCRIPT)

        for prod in PRODUCTS:
            data = None
            real_url = None
            card_installments = ""
            try:
                page.goto(prod["link"], wait_until="domcontentloaded", timeout=30000)
                time.sleep(4)
                card = find_card_for_product(page, prod["search"])
                if card and card.get("amounts"):
                    card_installments = card.get("installments", "")
                    real_url = card.get("productUrl", "")
                    if real_url and "/p/MLB" in real_url:
                        real_data = scrape_real_product(page, real_url)
                        if real_data and real_data.get("price"):
                            if not real_data["installments_qty"] and card_installments:
                                flat = card_installments.replace(" ", "")
                                m = re.search(r'(\d+)x(?:R?\$?\s*)?([\d.,]+)', flat)
                                if m:
                                    real_data["installments_qty"] = int(m.group(1))
                                    cleaned = m.group(2).replace(".", "").replace(",", ".")
                                    m2 = re.search(r'(\d+\.\d{2})', cleaned)
                                    real_data["installments_amount"] = float(m2.group(1)) if m2 else float(cleaned)
                            data = real_data
                            print(f"REAL: {prod['search'][:40]}... R${real_data['price']}")
                    if not data:
                        data = extract_prices(card["amounts"], card_installments)
                        print(f"CARD: {prod['search'][:40]}... R${data.get('price', '?')}")
            except Exception as e:
                print(f"ERRO: {prod['search'][:40]}... {e}")

            if data and data["price"]:
                price = data["price"]
                orig = data["original_price"]
                if not orig or orig <= price:
                    orig = round(price * 1.15, 2)
                desconto = round((1 - price / orig) * 100) if orig > 0 else 0
                pix = round(price * 0.9, 2)
                resultados.append({
                    "search": prod["search"],
                    "link": prod["link"],
                    "price": price,
                    "original_price": orig,
                    "discount": desconto,
                    "pix_price": pix,
                    "installments_qty": data["installments_qty"],
                    "installments_amount": data["installments_amount"],
                })
            elif prod["search"] in existing:
                print(f"EXISTENTE: {prod['search'][:40]}... manteve anterior")
                resultados.append(existing[prod["search"]])
            else:
                print(f"FALHOU: {prod['search'][:40]}... sem dados")

        page.close()
        context.close()
        browser.close()

    if not resultados:
        print("Nenhum preco obtido")
        sys.exit(1)

    path = os.path.join(repo_root, "prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "prices": resultados}, f, ensure_ascii=False, indent=2)
    print(f"\nSalvo: {path} ({len(resultados)} produtos)")


if __name__ == "__main__":
    main()
