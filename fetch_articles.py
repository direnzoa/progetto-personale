#!/usr/bin/env python3
"""
Script per scaricare tutti gli articoli da winechannel.it via WordPress REST API.
Uso: python3 fetch_articles.py
"""

import requests
import json
import sys
import time
from requests.auth import HTTPBasicAuth

# ── CONFIGURA QUI ──────────────────────────────────────────────
WP_URL   = "https://winechannel.it"
USERNAME = ""          # es. "admin"
APP_PASS = ""          # es. "xxxx xxxx xxxx xxxx xxxx xxxx"
# ───────────────────────────────────────────────────────────────

BASE = f"{WP_URL}/wp-json/wp/v2"
auth = HTTPBasicAuth(USERNAME, APP_PASS)

def fetch_page(endpoint, params, retries=5):
    """Scarica una singola pagina con retry su timeout."""
    delay = 5
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{BASE}/{endpoint}",
                auth=auth,
                params=params,
                timeout=90
            )
            return r
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            if attempt == retries - 1:
                raise
            print(f"  Timeout/errore, attendo {delay}s e riprovo (tentativo {attempt+2}/{retries})...", flush=True)
            time.sleep(delay)
            delay *= 2

def fetch_all(endpoint, params=None):
    items = []
    page  = 1
    params = params or {}
    while True:
        r = fetch_page(endpoint, {**params, "per_page": 100, "page": page})
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  {endpoint}: pagina {page}/{total_pages} — {len(items)} elementi", flush=True)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.5)   # pausa tra le pagine per non sovraccaricare il server
    return items

def main():
    if not USERNAME or not APP_PASS:
        print("ERRORE: inserisci USERNAME e APP_PASS nello script.")
        sys.exit(1)

    print("Connessione a WordPress...")
    r = requests.get(f"{BASE}/users/me", auth=auth, timeout=30)
    if r.status_code != 200:
        print(f"ERRORE autenticazione: {r.status_code} {r.text}")
        sys.exit(1)
    print(f"Autenticato come: {r.json().get('name')}\n")

    print("Scarico articoli (posts)...")
    posts = fetch_all("posts", {"status": "any", "_fields": (
        "id,date,modified,status,title,slug,link,"
        "categories,tags,author,comment_status,ping_status,"
        "meta,excerpt,content,featured_media,sticky"
    )})

    print("\nScarico pagine (pages)...")
    pages = fetch_all("pages", {"status": "any", "_fields": (
        "id,date,modified,status,title,slug,link,parent,author,"
        "comment_status,meta,excerpt,content,featured_media"
    )})

    print("\nScarico categorie...")
    categories = fetch_all("categories")

    print("\nScarico tag...")
    tags = fetch_all("tags")

    print("\nScarico autori...")
    authors = fetch_all("users")

    print("\nScarico media (solo metadati)...")
    media = fetch_all("media", {"_fields": "id,date,title,source_url,alt_text,media_details"})

    data = {
        "site": WP_URL,
        "totals": {
            "posts":      len(posts),
            "pages":      len(pages),
            "categories": len(categories),
            "tags":       len(tags),
            "authors":    len(authors),
            "media":      len(media),
        },
        "posts":      posts,
        "pages":      pages,
        "categories": categories,
        "tags":       tags,
        "authors":    authors,
        "media":      media,
    }

    out = "winechannel_export.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Export completato: {out}")
    print(f"  Articoli: {len(posts)} | Pagine: {len(pages)} | "
          f"Categorie: {len(categories)} | Tag: {len(tags)} | Media: {len(media)}")

if __name__ == "__main__":
    main()
