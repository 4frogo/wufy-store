import json, urllib.request, urllib.error, ssl, time, os
from datetime import datetime, timezone

PRODUCTS = [
    {"search": "Projetor HY320 Davely Smart TV Android", "link": "https://meli.la/1yBfiUy"},
    {"search": "Whey Protein Concentrado 1kg Chocolate Dark Lab", "link": "https://meli.la/2LMdTFf"},
    {"search": "Lavadora Lava Jato Portatil Pressao 2 Baterias MyMotors", "link": "https://meli.la/19ErgKc"},
    {"search": "Whey Pro Max Titanium Concentrado 1kg", "link": "https://meli.la/25unFmR"},
    {"search": "Bota Bull Terrier Bruce Masculina Couro", "link": "https://meli.la/1RuihHY"},
    {"search": "Smart TV AOC 50 4K DLED 50U7045", "link": "https://meli.la/2u6hu7K"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

def fetch_json(url, retries=2):
    for attempt in range(retries):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
    return None

def buscar_precos():
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
        else:
            print(f"FALHOU: {prod['search'][:40]}...")

    return resultados

def main():
    import urllib.parse
    precos = buscar_precos()
    if not precos:
        print("Nenhum preco obtido")
        sys.exit(1)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(), "prices": precos}, f, ensure_ascii=False, indent=2)
    print(f"Salvo: {path} ({len(precos)} produtos)")

if __name__ == "__main__":
    import sys
    main()
