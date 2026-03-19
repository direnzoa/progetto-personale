#!/usr/bin/env python3
"""
obsidian_to_pdf.py
Esporta ogni nota Obsidian come file PDF individuale.

Utilizzo:
    python3 obsidian_to_pdf.py --vault /percorso/vault --output ./pdf-export
    python3 obsidian_to_pdf.py --vault "X:\\articoli" --output "C:\\Desktop\\pdf"

Requisiti:
    pip install weasyprint

Note Windows:
    Se weasyprint dà errori di dipendenze su Windows, installa prima GTK3:
    https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
    In alternativa: pip install xhtml2pdf  (qualità inferiore, nessuna dep di sistema)
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

# ─── Backend PDF ───────────────────────────────────────────────────────────────

def _try_import_backend():
    """Prova weasyprint, poi xhtml2pdf. Ritorna ('weasyprint'|'xhtml2pdf', modulo)."""
    try:
        import weasyprint  # noqa: F401
        return "weasyprint", weasyprint
    except ImportError:
        pass
    try:
        import xhtml2pdf.pisa as pisa  # noqa: F401
        return "xhtml2pdf", pisa
    except ImportError:
        pass
    return None, None


# ─── CSS per il PDF ────────────────────────────────────────────────────────────

PDF_CSS = """
@page {
    size: A4;
    margin: 2.5cm 2cm 2.5cm 2cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #888;
    }
}
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
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
    margin: 0.8em 0 0.8em 0;
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
th, td {
    border: 1px solid #ccc;
    padding: 0.35em 0.65em;
    text-align: left;
}
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


# ─── Funzione di conversione ───────────────────────────────────────────────────

def _build_html(article: dict, css: str) -> str:
    """Assembla il documento HTML per un articolo, con immagini inline (base64)."""
    title = article["title"]
    body  = article["body"]
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
        css=css,
    )


def article_to_pdf_weasyprint(article: dict, output_dir: Path, wp_module) -> Path:
    html_doc = _build_html(article, PDF_CSS)
    out_path = output_dir / f"{article['slug']}.pdf"
    wp_module.HTML(string=html_doc, base_url=str(output_dir)).write_pdf(
        target=str(out_path),
    )
    return out_path


def article_to_pdf_xhtml2pdf(article: dict, output_dir: Path, pisa_module) -> Path:
    html_doc = _build_html(article, PDF_CSS)
    out_path = output_dir / f"{article['slug']}.pdf"
    with open(out_path, "wb") as f:
        result = pisa_module.CreatePDF(html_doc, dest=f)
    if result.err:
        raise RuntimeError(f"xhtml2pdf ha riportato {result.err} errori")
    return out_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Esporta ogni nota Obsidian come file PDF individuale",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python3 obsidian_to_pdf.py --vault ~/Obsidian/Blog --output ./pdf-export

  python3 obsidian_to_pdf.py \\
    --vault "X:\\articoli_francesco\\Wine Channel\\articoli" \\
    --output "C:\\Users\\Admini\\Desktop\\pdf-export"

Requisiti:
  pip install weasyprint
  (oppure: pip install xhtml2pdf  se weasyprint dà problemi su Windows)

Note Windows (weasyprint):
  Se ottieni errori GTK, scarica l'installer da:
  https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
""",
    )
    parser.add_argument("--vault",  "-v", required=True,
                        help="Percorso della cartella vault Obsidian")
    parser.add_argument("--output", "-o", default="pdf-export",
                        help="Cartella di output per i PDF (default: pdf-export)")

    args = parser.parse_args()

    # ── Controlla backend ──────────────────────────────────────────────────────
    backend_name, backend_mod = _try_import_backend()
    if backend_name is None:
        print("ERRORE: nessun backend PDF trovato.", file=sys.stderr)
        print("       Installa con:  pip install weasyprint", file=sys.stderr)
        print("       Alternativa:   pip install xhtml2pdf", file=sys.stderr)
        sys.exit(1)
    print(f"Backend PDF: {backend_name}")

    # ── Vault ──────────────────────────────────────────────────────────────────
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERRORE: La cartella '{vault}' non esiste.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Scansione ─────────────────────────────────────────────────────────────
    print(f"Scansione vault: {vault}")
    articles = collect_articles(vault)

    if not articles:
        print("Nessuna nota .md trovata nel vault.", file=sys.stderr)
        sys.exit(1)

    print(f"Trovati {len(articles)} articoli → output in: {output_dir}\n")

    # ── Conversione ───────────────────────────────────────────────────────────
    ok = 0
    errors = 0
    for article in articles:
        short = article["title"][:55]
        print(f"  • {short:<55}", end=" ", flush=True)
        try:
            if backend_name == "weasyprint":
                pdf_path = article_to_pdf_weasyprint(article, output_dir, backend_mod)
            else:
                pdf_path = article_to_pdf_xhtml2pdf(article, output_dir, backend_mod)
            size_kb = pdf_path.stat().st_size / 1024
            print(f"✓  {pdf_path.name}  ({size_kb:.0f} KB)")
            ok += 1
        except Exception as exc:
            print(f"✗  ERRORE: {exc}")
            errors += 1

    # ── Riepilogo ─────────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"Completato: {ok} PDF generati", end="")
    if errors:
        print(f", {errors} errori")
    else:
        print()
    print(f"Cartella output: {output_dir}")


if __name__ == "__main__":
    main()
