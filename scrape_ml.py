#!/usr/bin/env python3
"""
Scraper de publicaciones dueño directo - MercadoLibre Inmuebles Córdoba.
Usa la API pública de ML (sin auth) + headers de navegador para evitar bloqueos.
"""

import requests
import json
import time
import csv
import re
import sys
from datetime import datetime

# ── configuración ─────────────────────────────────────────────────────────────
TARGET = 300          # publicaciones únicas deseadas
BATCH_SIZE = 50       # mostrar tabla cada N registros
SLEEP_BETWEEN = 2     # segundos entre aperturas de detalle
API_LIMIT = 50        # ML devuelve hasta 50 por llamada

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "es-AR,es;q=0.9",
    "Referer": "https://inmuebles.mercadolibre.com.ar/",
}

# ML category IDs
# MLA1459 = Inmuebles > Todas las categorías
# Córdoba state ID  = TUxBUENPUjI1MTZa  (verificado en API /classified_locations)
CATEGORY_IDS = {
    "MLA1459": "Inmuebles (todas)",
}
CORDOBA_STATE = "TUxBUENPUjI1MTZa"

# Palabras que indican inmobiliaria
INMOB_KEYWORDS = [
    "re/max", "remax", "century 21", "tizado", "toribio", "bullrich",
    "coldwell", "adrián mercado", "adrian mercado", "cucicba", "cpi",
    "matrícula", "matricula", "corredor inmobiliario", "corredor prop",
    "broker", "inmobiliaria",
]

PROP_TYPE_MAP = {
    "casa": "casa",
    "departamento": "departamento",
    "ph": "ph",
    "lote": "lote",
    "terreno": "terreno",
    "local": "local",
    "galp": "galpón",
    "cochera": "cochera",
    "campo": "campo",
    "quinta": "quinta",
    "oficina": "oficina",
}

# ── helpers ───────────────────────────────────────────────────────────────────

def get_prop_type(title: str, category: str) -> str:
    t = (title + " " + category).lower()
    for k, v in PROP_TYPE_MAP.items():
        if k in t:
            return v
    return "otro"


def extract_phone(text: str) -> str:
    """Extrae primer número de teléfono del texto si existe."""
    # patrones AR: 0351-..., +54 351, 351 4..., 15-...
    patterns = [
        r'(?:\+?54\s*)?(?:0?351|0?358|0?3541|0?3543|0?3544|0?3546|0?3547|0?3548|0?3549)'
        r'[\s\-]?\d{3,4}[\s\-]?\d{4}',
        r'(?:tel|cel|whatsapp|wsp|llam)[^\d]{0,10}(\d[\d\s\-\.]{7,14}\d)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            raw = m.group(0) if '(' not in p else m.group(1)
            return re.sub(r'[^\d+]', '', raw)
    return ""


def is_inmobiliaria(title: str, description: str, seller_name: str) -> bool:
    combined = (title + " " + description + " " + seller_name).lower()
    return any(kw in combined for kw in INMOB_KEYWORDS)


def fetch_search_page(offset: int, category: str = "MLA1459") -> dict:
    url = (
        f"https://api.mercadolibre.com/sites/MLA/search"
        f"?category={category}"
        f"&state={CORDOBA_STATE}"
        f"&seller_type=private"          # dueño directo
        f"&offset={offset}"
        f"&limit={API_LIMIT}"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_item_detail(item_id: str) -> dict:
    url = f"https://api.mercadolibre.com/items/{item_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return {}
    return r.json()


def fetch_item_description(item_id: str) -> str:
    url = f"https://api.mercadolibre.com/items/{item_id}/description"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return ""
    return r.json().get("plain_text", "")


def fetch_seller_info(seller_id: int) -> dict:
    url = f"https://api.mercadolibre.com/users/{seller_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return {}
    return r.json()


def count_seller_listings(seller_id: int) -> int:
    url = (
        f"https://api.mercadolibre.com/sites/MLA/search"
        f"?seller_id={seller_id}"
        f"&category=MLA1459"
        f"&limit=1"
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return 0
    return r.json().get("paging", {}).get("total", 0)


# ── tabla markdown ─────────────────────────────────────────────────────────────

HEADER_ROW = (
    "| # | Link | Tipo | Teléfono | Vendedor | Título (60c) | "
    "Precio | Ubicación | Pubs vendedor | Sospechoso |"
)
SEP_ROW = "|---|---|---|---|---|---|---|---|---|---|"


def fmt_row(n: int, rec: dict) -> str:
    link = f"[ver]({rec['url']})"
    return (
        f"| {n} | {link} | {rec['tipo']} | {rec['telefono']} | "
        f"{rec['vendedor']} | {rec['titulo'][:60]} | "
        f"{rec['precio']} | {rec['ubicacion']} | "
        f"{rec['pubs_vendedor']} | {rec['sospechoso']} |"
    )


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    results = []
    seen_ids = set()
    offset = 0
    page = 1
    total_fetched = 0

    print(f"\n{'='*70}")
    print(f"  SCRAPER ML - Dueño Directo - Córdoba  |  Objetivo: {TARGET}")
    print(f"  Inicio: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")

    while len(results) < TARGET:
        print(f"[Página {page} | offset {offset}] Buscando...", flush=True)

        try:
            data = fetch_search_page(offset)
        except Exception as e:
            print(f"  ERROR en búsqueda: {e}")
            if "403" in str(e) or "429" in str(e):
                print("  → ML bloqueó el acceso. Esperando 30s...")
                time.sleep(30)
                continue
            break

        items = data.get("results", [])
        total_available = data.get("paging", {}).get("total", 0)
        print(f"  Total disponible en ML: {total_available} | Esta página: {len(items)} items")

        if not items:
            print("  No hay más items. Fin de resultados.")
            break

        for item in items:
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            total_fetched += 1

            title = item.get("title", "")
            url = item.get("permalink", "")
            price_val = item.get("price", 0)
            currency = item.get("currency_id", "")
            precio = f"{currency} {price_val:,.0f}" if price_val else "Consultar"

            # ubicación desde search result
            address = item.get("location", item.get("address", {}))
            city = address.get("city", {}).get("name", "") if isinstance(address.get("city"), dict) else ""
            state_name = address.get("state", {}).get("name", "") if isinstance(address.get("state"), dict) else ""
            neighborhood = address.get("neighborhood", {}).get("name", "") if isinstance(address.get("neighborhood"), dict) else ""
            ubicacion = ", ".join(filter(None, [city, neighborhood, state_name]))

            seller = item.get("seller", {})
            seller_id = seller.get("id", 0)
            seller_name = seller.get("nickname", "")

            category_id = item.get("category_id", "")
            tipo = get_prop_type(title, category_id)

            # detalle completo
            time.sleep(SLEEP_BETWEEN)
            try:
                detail = fetch_item_detail(item_id)
                desc = fetch_item_description(item_id)
            except Exception as e:
                print(f"    WARN: no se pudo obtener detalle de {item_id}: {e}")
                detail = {}
                desc = ""

            # mejorar ubicación con el detalle
            if detail:
                dloc = detail.get("location", {})
                dcity = dloc.get("city", {}).get("name", city) if isinstance(dloc.get("city"), dict) else city
                dneigh = dloc.get("neighborhood", {}).get("name", neighborhood) if isinstance(dloc.get("neighborhood"), dict) else neighborhood
                ubicacion = ", ".join(filter(None, [dcity, dneigh]))

            # filtro inmobiliaria
            if is_inmobiliaria(title, desc, seller_name):
                print(f"    SKIP (inmobiliaria detectada): {title[:50]}")
                continue

            # teléfono en descripción
            telefono = extract_phone(desc)

            # conteo de publicaciones del vendedor
            try:
                n_pubs = count_seller_listings(seller_id)
            except Exception:
                n_pubs = 0
            sospechoso = "sí" if n_pubs > 10 else "no"

            rec = {
                "id": item_id,
                "url": url,
                "tipo": tipo,
                "telefono": telefono,
                "vendedor": seller_name,
                "titulo": title,
                "precio": precio,
                "ubicacion": ubicacion,
                "pubs_vendedor": n_pubs,
                "sospechoso": sospechoso,
            }
            results.append(rec)

            # mostrar tanda de 50
            n = len(results)
            if n % BATCH_SIZE == 0:
                print(f"\n{'─'*70}")
                print(f"  TANDA {n // BATCH_SIZE} — Publicaciones {n - BATCH_SIZE + 1} a {n}")
                print(f"{'─'*70}")
                print(HEADER_ROW)
                print(SEP_ROW)
                for i, r in enumerate(results[n - BATCH_SIZE:n], start=n - BATCH_SIZE + 1):
                    print(fmt_row(i, r))
                print()

            if len(results) >= TARGET:
                break

        # siguiente página
        offset += API_LIMIT
        page += 1

        # ML limita a 1000 resultados via paginación
        if offset >= min(total_available, 1000):
            print("  Alcanzado el límite de paginación de ML (1000 items).")
            break

    # ── reporte final ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  REPORTE FINAL — {len(results)} publicaciones recolectadas")
    print(f"{'='*70}")

    con_tel = sum(1 for r in results if r["telefono"])
    print(f"  Con teléfono en descripción: {con_tel} ({con_tel/len(results)*100:.1f}%)")

    # tipos
    from collections import Counter
    tipos = Counter(r["tipo"] for r in results)
    print(f"\n  Tipos predominantes:")
    for t, c in tipos.most_common():
        print(f"    {t}: {c}")

    # localidades
    locs = Counter(r["ubicacion"].split(",")[0].strip() for r in results if r["ubicacion"])
    print(f"\n  Top 10 localidades:")
    for l, c in locs.most_common(10):
        print(f"    {l}: {c}")

    # top vendedores
    vends = Counter(r["vendedor"] for r in results)
    print(f"\n  Top 5 vendedores con más publicaciones:")
    for v, c in vends.most_common(5):
        print(f"    {v}: {c} pub(s) en esta extracción")

    # tabla completa final
    print(f"\n{'='*70}")
    print(f"  TABLA COMPLETA")
    print(f"{'='*70}")
    print(HEADER_ROW)
    print(SEP_ROW)
    for i, r in enumerate(results, 1):
        print(fmt_row(i, r))

    # guardar CSV
    csv_path = "/home/user/Emimanzur/ml_dueno_directo_cordoba.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()) if results else [])
        writer.writeheader()
        writer.writerows(results)
    print(f"\n  CSV guardado: {csv_path}")

    # guardar JSON
    json_path = "/home/user/Emimanzur/ml_dueno_directo_cordoba.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  JSON guardado: {json_path}")

    return results


if __name__ == "__main__":
    main()
