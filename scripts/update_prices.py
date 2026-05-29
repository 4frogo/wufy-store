import json, urllib.request, urllib.error, ssl, time, os, sys, urllib.parse
from datetime import datetime, timezone

PRODUCTS = [
    {"search": "Projetor HY320 Davely Smart TV Android", "link": "https://meli.la/1yBfiUy"},
    {"search": "Whey Protein Concentrado 1kg Chocolate Dark Lab", "link": "https://meli.la/2LMdTFf"},
    {"search": "Lavadora Lava Jato Portatil Pressao 2 Baterias MyMotors", "link": "https://meli.la/19ErgKc"},
    {"search": "Whey Pro Max Titanium Concentrado 1kg", "link": "https://meli.la/25unFmR"},
    {"search": "Bota Bull Terrier Bruce Masculina Couro", "link": "https://meli.la/1RuihHY"},
    {"search": "Smart TV AOC 50 4K DLED 50U7045", "link": "https://meli.la/2u6hu7K"},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
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

def fetch_json(url):
    for ua in USER_AGENTS:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Accept-Language": "pt-BR,pt;q=0.9",
                "Origin": "https://www.mercadolivre.com.br",
                "Referer": "https://www.mercadolivre.com.br/",
            })
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                return json.loads(r.read().decode())
        except:
            continue
    return None

def buscar_precos(existing):
    resultados = []
    for prod in PRODUCTS:
        url = f"https://api.mercadolibre.com/sites/MLB/search?q={urllib.parse.quote(prod['search'])}&limit=1"
        data = fetch_json(url)
        item = data.get("results", [None])[0] if data else None

        if item:
            price = item.get("price", 0)
            orig = item.get("original_price") or price
            desconto = round((1 - price / orig) * 100) if orig > 0 else 0
            pix = round(price * 0.9, 2)
            parcelas = item.get("installments", {})
            resultados.append({
                "search": prod["search"],
                "link": prod["link"],
                "price": price,
                "original_price": orig,
                "discount": desconto,
                "pix_price": pix,
                "installments_qty": parcelas.get("quantity", 0),
                "installments_amount": parcelas.get("amount", 0),
                "updated": datetime.now(timezone.utc).isoformat(),
            })
            print(f"OK: {prod['search'][:40]}... R${price}")
        elif prod["search"] in existing:
            resultados.append(existing[prod["search"]])
            print(f"EXISTENTE: {prod['search'][:40]}... manteve preco anterior")
        else:
            print(f"FALHOU: {prod['search'][:40]}... sem dados anteriores")

    return resultados

def main():
    existing = load_existing_prices()
    precos = buscar_precos(existing)
    if not precos:
        print("Nenhum preco obtido")
        sys.exit(1)

    path = os.path.join(repo_root, "prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "prices": precos}, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {path} ({len(precos)} produtos)")

if __name__ == "__main__":
    main()
