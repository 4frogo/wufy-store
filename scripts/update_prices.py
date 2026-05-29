import re, json, os, sys
from datetime import datetime, timezone

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


def find_card_data(page):
    """Encontra o primeiro poly-card da pagina e extrai amounts, installments e titulo."""
    card = page.query_selector("[class*='poly-card']")
    if not card:
        amts = page.query_selector_all(".andes-money-amount")
        return {
            "amounts": [amts[i] for i in range(min(5, len(amts)))] if amts else [],
            "installments": ""
        }

    result = card.evaluate("""
        card => {
            let amts = card.querySelectorAll('.andes-money-amount');
            let inst = card.querySelector('.poly-price__installments');
            let title = card.querySelector('.poly-component__title');
            return {
                title: title ? title.innerText.trim() : '',
                amounts: Array.from(amts).map(a => ({
                    text: a.innerText.trim().replace(/\\s+/g, ' '),
                    cls: a.className
                })),
                installments: inst ? inst.innerText.trim().replace(/\\s+/g, ' ') : ''
            };
        }
    """)
    return result


def extract_prices_from_amounts(card_data):
    amounts = card_data.get("amounts", []) if isinstance(card_data, dict) else card_data
    installments_text = card_data.get("installments", "") if isinstance(card_data, dict) else ""

    if isinstance(amounts, list) and len(amounts) > 0 and isinstance(amounts[0], dict):
        pass
    elif isinstance(amounts, list) and len(amounts) > 0:
        installments_text = ""

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
            if m2:
                inst_amt = float(m2.group(1))
            else:
                inst_amt = float(cleaned)

    if not price_val:
        for amt in amounts:
            text = amt["text"] if isinstance(amt, dict) else amt.inner_text()
            cls = amt["cls"] if isinstance(amt, dict) else (amt.get_attribute("class") or "")
            val = extract_float(text)
            if val and "previous" not in cls and "phrase" not in cls and "installments" not in cls:
                price_val = val
                break

    return {
        "price": price_val,
        "original_price": orig_val,
        "installments_qty": inst_qty,
        "installments_amount": inst_amt,
    }


def scrape_first_card(page, url):
    page.goto(url, wait_until="networkidle", timeout=30000)
    card_data = find_card_data(page)
    if not card_data or not card_data.get("amounts"):
        return None
    return extract_prices_from_amounts(card_data)


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
        )
        page = context.new_page()

        for prod in PRODUCTS:
            data = None
            try:
                data = scrape_first_card(page, prod["link"])
            except Exception as e:
                print(f"ERRO: {prod['search'][:40]}... {e}")

            if data and data["price"]:
                price = data["price"]
                orig = data["original_price"]
                if not orig or orig <= price:
                    orig = round(price * 1.15, 2)
                desconto = round((1 - price / orig) * 100) if orig > 0 else 0
                pix = round(price * 0.9, 2)

                print(f"OK: {prod['search'][:40]}... R${price}")
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
