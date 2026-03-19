#!/usr/bin/env python3
"""
obsidian_to_pdf.py
Esporta ogni nota Obsidian come file PDF individuale.
Usa Playwright (Chromium headless) — nessuna dipendenza di sistema.

Utilizzo:
    python3 obsidian_to_pdf.py --vault /percorso/vault --output ./pdf-export
    python3 obsidian_to_pdf.py --vault "X:\\articoli" --output "C:\\Desktop\\pdf"

Requisiti:
    pip install playwright
    playwright install chromium
"""

import sys
import argparse
from pathlib import Path

# ─── Importa funzioni condivise ────────────────────────────────────────────────

try:
    from obsidian_to_wordpress import (
        collect_articles,
        md_to_html,
        find_image,
        image_to_base64,
        xml_escape,
        slugify,
    )
except ImportError:
    print("ERRORE: obsidian_to_wordpress.py non trovato nella stessa cartella.", file=sys.stderr)
    sys.exit(1)

# ─── CSS per il PDF ────────────────────────────────────────────────────────────

PDF_CSS = """
* { box-sizing: border-box; }
@page { size: A4; margin: 2.5cm 2cm 2.5cm 2cm; }
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
    max-width: 100%;
}
h1 {
    font-size: 22pt;
    margin-top: 0;
    margin-bottom: 0.3em;
    color: #111;
    border-bottom: 2px solid #ccc;
    padding-bottom: 0.2em;
}
h2 { font-size: 15pt; margin-top: 1.4em; color: #222; }
h3 { font-size: 13pt; color: #333; }
h4, h5, h6 { font-size: 11pt; font-weight: bold; color: #444; }
.meta {
    font-size: 9pt;
    color: #666;
    margin-bottom: 1.8em;
    padding-bottom: 0.6em;
}
p { margin: 0.55em 0; text-align: justify; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
code {
    font-family: 'Courier New', Courier, monospace;
    font-size: 9pt;
    background: #f4f4f4;
    padding: 1px 4px;
    border-radius: 3px;
}
pre {
    background: #f4f4f4;
    padding: 0.7em 1em;
    border-left: 3px solid #bbb;
    overflow-x: auto;
    font-size: 9pt;
}
pre code { background: none; padding: 0; }
blockquote {
    border-left: 3px solid #ccc;
    margin: 0.8em 0;
    padding: 0.2em 0 0.2em 1em;
    color: #555;
    font-style: italic;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 10pt;
}
th, td { border: 1px solid #ccc; padding: 0.35em 0.65em; text-align: left; }
th { background: #f0f0f0; font-weight: bold; }
tr:nth-child(even) { background: #fafafa; }
a { color: #1a4f8a; text-decoration: none; }
ul, ol { margin: 0.4em 0; padding-left: 1.4em; }
li { margin: 0.2em 0; }
mark { background: #fff3a3; }
del { color: #aaa; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.5em 0; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <h1>{title_escaped}</h1>
  <div class="meta">{meta_line}</div>
  {content}
</body>
</html>
"""

# ─── Costruzione HTML ──────────────────────────────────────────────────────────

def build_html(article: dict) -> str:
    """Assembla il documento HTML per un articolo, con immagini inline (base64)."""
    title      = article["title"]
    body       = article["body"]
    pub_date   = article["pub_date"]
    tags       = article["tags"]
    categories = article["categories"]
    images     = article["images"]
    image_dirs = article["image_dirs"]

    def resolve_image(name: str) -> str:
        basename = Path(name).name
        img_path = (
            find_image(name, image_dirs)
            or find_image(basename, image_dirs)
            or images.get(name)
            or images.get(basename)
        )
        if img_path and img_path.exists():
            try:
                _, data_uri = image_to_base64(img_path)
                return data_uri
            except Exception:
                pass
        return basename

    html_content = md_to_html(body, image_resolver=resolve_image)

    meta_parts = [pub_date.strftime("%d %B %Y")]
    if categories:
        meta_parts.append("Categoria: " + ", ".join(categories))
    if tags:
        meta_parts.append("Tag: " + ", ".join(tags))
    meta_line = " &nbsp;·&nbsp; ".join(meta_parts)

    return HTML_TEMPLATE.format(
        title=xml_escape(title),
        title_escaped=xml_escape(title),
        meta_line=meta_line,
        content=html_content,
        css=PDF_CSS,
    )


# ─── Generazione PDF con Playwright ───────────────────────────────────────────

def generate_pdfs(articles: list[dict], output_dir: Path) -> tuple[int, int]:
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

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        for article in articles:
            short = article["title"][:55]
            print(f"  • {short:<55}", end=" ", flush=True)
            out_path = output_dir / f"{article['slug']}.pdf"
            try:
                html_doc = build_html(article)
                page.set_content(html_doc, wait_until="load")
                page.pdf(
                    path=str(out_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "2cm", "bottom": "2cm",
                            "left": "1.8cm", "right": "1.8cm"},
                    display_header_footer=True,
                    header_template='<div style="font-size:0;"></div>',
                    footer_template=(
                        '<div style="font-size:8px;width:100%;text-align:center;'
                        'color:#999;padding:4px 0;">'
                        '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                        '</div>'
                    ),
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

        browser.close()

    return ok, errors


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Esporta ogni nota Obsidian come file PDF individuale (Playwright)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python3 obsidian_to_pdf.py --vault ~/Obsidian/Blog --output ./pdf-export

  python3 obsidian_to_pdf.py \\
    --vault "X:\\articoli_francesco\\Wine Channel\\articoli" \\
    --output "C:\\Users\\Admini\\Desktop\\pdf-export"

Requisiti:
  pip install playwright
  playwright install chromium
""",
    )
    parser.add_argument("--vault",  "-v", required=True,
                        help="Percorso della cartella vault Obsidian")
    parser.add_argument("--output", "-o", default="pdf-export",
                        help="Cartella di output per i PDF (default: pdf-export)")

    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERRORE: La cartella '{vault}' non esiste.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scansione vault: {vault}")
    articles = collect_articles(vault)

    if not articles:
        print("Nessuna nota .md trovata nel vault.", file=sys.stderr)
        sys.exit(1)

    print(f"Trovati {len(articles)} articoli → output in: {output_dir}\n")

    ok, errors = generate_pdfs(articles, output_dir)

    print(f"\n{'─' * 60}")
    print(f"Completato: {ok} PDF generati", end="")
    if errors:
        print(f", {errors} errori")
    else:
        print()
    print(f"Cartella output: {output_dir}")


if __name__ == "__main__":
    main()
