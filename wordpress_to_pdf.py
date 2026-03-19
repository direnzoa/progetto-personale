#!/usr/bin/env python3
"""
wordpress_to_pdf.py
Genera un PDF per ogni articolo WordPress visitando le pagine live del sito.
Legge gli URL direttamente dal file XML di esportazione già generato.

Utilizzo:
    python3 wordpress_to_pdf.py --xml wordpress-export.xml --output ./pdf-export
    python3 wordpress_to_pdf.py --xml wordpress-export.xml --url https://winechannel.it --output ./pdf-export

Requisiti:
    pip install playwright
    playwright install chromium
"""

import sys
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


# ─── Parser XML ────────────────────────────────────────────────────────────────

WP_NS  = "http://wordpress.org/export/1.2/"
DC_NS  = "http://purl.org/dc/elements/1.1/"

def parse_articles_from_wxr(xml_path: Path, override_url: str | None = None) -> tuple[list[dict], str]:
    """
    Estrae titoli e URL degli articoli (post) dal file WXR.
    Restituisce (lista_articoli, base_url).
    """
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print(f"ERRORE: impossibile leggere il file XML: {e}", file=sys.stderr)
        sys.exit(1)

    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        print("ERRORE: file XML non valido (nessun tag <channel>).", file=sys.stderr)
        sys.exit(1)

    # URL base dal file XML (o da --url)
    base_url = override_url
    if not base_url:
        link_el = channel.find("link")
        if link_el is not None and link_el.text:
            base_url = link_el.text.rstrip("/")

    articles = []
    for item in channel.findall("item"):
        post_type = item.find(f"{{{WP_NS}}}post_type")
        if post_type is None or post_type.text != "post":
            continue

        status = item.find(f"{{{WP_NS}}}status")
        if status is not None and status.text not in ("publish", "draft", "private"):
            continue

        title_el = item.find("title")
        title = (title_el.text or "Senza titolo").strip()

        slug_el = item.find(f"{{{WP_NS}}}post_name")
        slug = (slug_el.text or "").strip()

        link_el = item.find("link")
        url = (link_el.text or "").strip()

        # Se è passato --url, ricostruisce l'indirizzo con la nuova base
        if override_url and slug:
            url = f"{override_url.rstrip('/')}/{slug}/"

        date_el = item.find(f"{{{WP_NS}}}post_date")
        pub_date = None
        if date_el is not None and date_el.text:
            try:
                pub_date = datetime.strptime(date_el.text.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        if pub_date is None:
            pub_date = datetime.min

        if url:
            articles.append({"title": title, "slug": slug or title, "url": url, "pub_date": pub_date})

    return articles, base_url or ""


# ─── Generazione PDF con Playwright ───────────────────────────────────────────

def generate_pdfs(
    articles: list[dict],
    output_dir: Path,
    format_page: str = "A4",
    wait_ms: int = 1500,
    print_bg: bool = True,
    no_header_footer: bool = False,
    scale: float = 1.0,
):
    """Visita ogni URL con Chromium headless e salva il PDF."""
    try:
        from playwright.sync_api import sync_playwright, Error as PWError
    except ImportError:
        print("ERRORE: playwright non è installato.", file=sys.stderr)
        print("       Installa con:", file=sys.stderr)
        print("           pip install playwright", file=sys.stderr)
        print("           playwright install chromium", file=sys.stderr)
        sys.exit(1)

    ok = 0
    errors = 0

    articles_sorted = sorted(articles, key=lambda a: a["pub_date"])
    width = max(2, len(str(len(articles_sorted))))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="it-IT",
        )
        page = context.new_page()

        for idx, article in enumerate(articles_sorted, start=1):
            title = article["title"]
            slug  = article["slug"]
            url   = article["url"]
            short = title[:55]
            print(f"  • {short:<55}", end=" ", flush=True)

            prefix = str(idx).zfill(width)
            out_path = output_dir / f"{prefix}_{slug}.pdf"
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                # Attesa extra opzionale per contenuti JS pesanti
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)

                page.pdf(
                    path=str(out_path),
                    format=format_page,
                    print_background=print_bg,
                    display_header_footer=not no_header_footer,
                    header_template=(
                        '<div style="font-size:8px;width:100%;text-align:center;'
                        'color:#888;padding:4px 0;"></div>'
                    ),
                    footer_template=(
                        '<div style="font-size:8px;width:100%;text-align:center;'
                        'color:#888;padding:4px 0;">'
                        '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                        '</div>'
                    ),
                    margin={"top": "1.5cm", "bottom": "1.5cm",
                            "left": "1.5cm",  "right": "1.5cm"},
                    scale=scale,
                )
                size_kb = out_path.stat().st_size / 1024
                print(f"✓  {out_path.name}  ({size_kb:.0f} KB)")
                ok += 1
            except PWError as exc:
                print(f"✗  ERRORE Playwright: {exc}")
                errors += 1
            except Exception as exc:
                print(f"✗  ERRORE: {exc}")
                errors += 1

        context.close()
        browser.close()

    return ok, errors


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Genera un PDF per ogni articolo WordPress visitando le pagine live",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Usa gli URL già presenti nel file XML
  python3 wordpress_to_pdf.py --xml wordpress-export.xml --output ./pdf-export

  # Sovrascrive la base URL (es. ambiente di staging o sito migrato)
  python3 wordpress_to_pdf.py --xml wordpress-export.xml \\
    --url https://winechannel.it --output ./pdf-export

  # Solo articoli pubblicati, formato A4, sfondo incluso
  python3 wordpress_to_pdf.py --xml wordpress-export.xml \\
    --url https://winechannel.it --output ./pdf-export --only-published

Installazione:
  pip install playwright
  playwright install chromium
""",
    )
    parser.add_argument("--xml", "-x", required=True,
                        help="Percorso del file XML di esportazione WordPress")
    parser.add_argument("--output", "-o", default="pdf-export",
                        help="Cartella di output per i PDF (default: pdf-export)")
    parser.add_argument("--url", "-u", default=None,
                        help="Sovrascrive la base URL del sito (es. https://winechannel.it)")
    parser.add_argument("--format", default="A4",
                        choices=["A4", "A3", "Letter"],
                        help="Formato pagina PDF (default: A4)")
    parser.add_argument("--wait", type=int, default=1500,
                        help="Millisecondi di attesa dopo il caricamento pagina (default: 1500)")
    parser.add_argument("--no-background", action="store_true",
                        help="Non stampare lo sfondo (immagini e colori CSS)")
    parser.add_argument("--no-header-footer", action="store_true",
                        help="Ometti intestazione e numero pagina")
    parser.add_argument("--scale", type=float, default=0.9,
                        help="Scala di rendering, tra 0.1 e 2.0 (default: 0.9)")
    parser.add_argument("--only-published", action="store_true",
                        help="Includi solo gli articoli con stato 'publish' nel XML")

    args = parser.parse_args()

    xml_path = Path(args.xml).expanduser().resolve()
    if not xml_path.is_file():
        print(f"ERRORE: file '{xml_path}' non trovato.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Lettura XML: {xml_path}")
    articles, base_url = parse_articles_from_wxr(xml_path, override_url=args.url)

    if not articles:
        print("Nessun articolo trovato nel file XML.", file=sys.stderr)
        sys.exit(1)

    # Filtro --only-published: richiede di rileggere lo stato dal XML
    # (parse_articles_from_wxr include publish/draft/private, qui filtriamo)
    if args.only_published:
        # rilancia il parse raccogliendo lo stato
        articles = _filter_published(xml_path, articles)

    print(f"Trovati {len(articles)} articoli")
    print(f"Sito:      {base_url or '(da XML)'}")
    print(f"Output:    {output_dir}\n")

    ok, errors = generate_pdfs(
        articles=articles,
        output_dir=output_dir,
        format_page=args.format,
        wait_ms=args.wait,
        print_bg=not args.no_background,
        no_header_footer=args.no_header_footer,
        scale=args.scale,
    )

    print(f"\n{'─' * 60}")
    print(f"Completato: {ok} PDF generati", end="")
    if errors:
        print(f", {errors} errori")
    else:
        print()
    print(f"Cartella output: {output_dir}")


def _filter_published(xml_path: Path, articles: list[dict]) -> list[dict]:
    """Filtra la lista tenendo solo gli slug degli articoli 'publish'."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    channel = root.find("channel")
    published_slugs = set()
    for item in channel.findall("item"):
        pt = item.find(f"{{{WP_NS}}}post_type")
        if pt is None or pt.text != "post":
            continue
        st = item.find(f"{{{WP_NS}}}status")
        if st is not None and st.text == "publish":
            sl = item.find(f"{{{WP_NS}}}post_name")
            if sl is not None and sl.text:
                published_slugs.add(sl.text.strip())
    return [a for a in articles if a["slug"] in published_slugs]


if __name__ == "__main__":
    main()
