#!/usr/bin/env python3
"""
obsidian_to_wordpress.py
Converte un vault Obsidian in formato WXR (WordPress eXtended RSS) pronto per l'importazione.

Utilizzo:
    python3 obsidian_to_wordpress.py --vault /percorso/vault --output export.xml --url https://tuosito.com
    python3 obsidian_to_wordpress.py --vault /percorso/vault --output export.xml --url https://tuosito.com --embed-images
    python3 obsidian_to_wordpress.py --vault /percorso/vault --output export.xml --url https://tuosito.com --status draft

Strutture vault supportate:
    1. Una cartella per articolo (ogni cartella = un post, le immagini sono dentro la cartella)
    2. File .md nella root con cartella immagini separata (es. assets/, attachments/, images/)
    3. Tutto nella root (file .md e immagini nella stessa cartella)

Requisiti: Python 3.6+ (nessuna dipendenza esterna)
"""

import os
import re
import sys
import base64
import hashlib
import mimetypes
import argparse
import unicodedata
from pathlib import Path
import random
from datetime import datetime, timezone, timedelta


# ─── Utility ──────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Converte testo in slug URL-friendly."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text


def xml_escape(text: str) -> str:
    """Escape caratteri speciali XML."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


def random_time(dt: datetime) -> datetime:
    """Sostituisce l'orario di un datetime con uno casuale tra le 9:00 e le 13:30."""
    start_minutes = 9 * 60        # 540 minuti
    end_minutes   = 13 * 60 + 30  # 810 minuti
    minutes = random.randint(start_minutes, end_minutes)
    return dt.replace(hour=minutes // 60, minute=minutes % 60, second=random.randint(0, 59))


def image_to_base64(path: Path) -> tuple[str, str]:
    """Converte un'immagine in stringa base64. Restituisce (mime_type, data_uri)."""
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/jpeg"
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return mime_type, f"data:{mime_type};base64,{data}"


# ─── Parser Frontmatter YAML minimale ─────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Estrae il frontmatter YAML dalla nota Obsidian.
    Restituisce (metadata_dict, body_senza_frontmatter).
    """
    meta = {}
    if not content.startswith("---"):
        return meta, content

    end = content.find("\n---", 3)
    if end == -1:
        return meta, content

    yaml_block = content[3:end].strip()
    body = content[end + 4:].lstrip("\n")

    current_key: str | None = None
    for line in yaml_block.splitlines():
        stripped = line.strip()

        # Voce di lista YAML in stile blocco:  "  - valore"
        if stripped.startswith("- ") and current_key is not None:
            item = stripped[2:].strip().strip('"').strip("'")
            if isinstance(meta.get(current_key), list):
                meta[current_key].append(item)
            else:
                meta[current_key] = [item]
            continue

        if ":" not in stripped:
            current_key = None
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key

        # Liste inline: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",") if v.strip()]
            current_key = None  # lista completa, nessuna continuazione
        # Stringa quotata
        elif (value.startswith('"') and value.endswith('"')) or \
             (value.startswith("'") and value.endswith("'")):
            meta[key] = value[1:-1]
            current_key = None
        elif value == "":
            meta[key] = []   # prepara per lista in stile blocco
        else:
            meta[key] = value
            current_key = None

    return meta, body


# ─── Convertitore Markdown → HTML ─────────────────────────────────────────────

def md_to_html(md: str, image_resolver=None) -> str:
    """
    Converte Markdown (con sintassi Obsidian) in HTML.
    image_resolver(filename) -> URL o data URI dell'immagine.
    """

    lines = md.split("\n")
    html_lines = []
    i = 0

    def process_inline(text: str) -> str:
        """Applica le trasformazioni inline."""
        # Immagini Obsidian: ![[nome.png]] o ![[nome.png|alt]]
        def repl_obs_img(m):
            parts = m.group(1).split("|")
            filename = parts[0].strip()
            alt = parts[1].strip() if len(parts) > 1 else filename
            src = image_resolver(filename) if image_resolver else filename
            return f'<img src="{src}" alt="{xml_escape(alt)}" />'
        text = re.sub(r"!\[\[([^\]]+)\]\]", repl_obs_img, text)

        # Immagini Markdown: ![alt](src)
        def repl_md_img(m):
            alt, src = m.group(1), m.group(2)
            if image_resolver and not src.startswith("http"):
                resolved = image_resolver(Path(src).name)
                if resolved:
                    src = resolved
            return f'<img src="{src}" alt="{xml_escape(alt)}" />'
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl_md_img, text)

        # Link Obsidian: [[pagina]] o [[pagina|testo]]
        def repl_obs_link(m):
            parts = m.group(1).split("|")
            page = parts[0].strip()
            label = parts[1].strip() if len(parts) > 1 else page
            return f'<a href="{slugify(page)}">{xml_escape(label)}</a>'
        text = re.sub(r"\[\[([^\]]+)\]\]", repl_obs_link, text)

        # Link Markdown: [testo](url)
        text = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: f'<a href="{m.group(2)}">{xml_escape(m.group(1))}</a>',
            text
        )

        # Grassetto e corsivo: ***testo***
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
        # Grassetto: **testo** o __testo__
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
        # Corsivo: *testo* o _testo_
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
        # Barrato: ~~testo~~
        text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
        # Evidenziato Obsidian: ==testo==
        text = re.sub(r"==(.+?)==", r"<mark>\1</mark>", text)
        # Codice inline: `codice`
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        return text

    in_code_block = False
    code_lang = ""
    code_lines = []
    in_list = None       # "ul" o "ol"
    list_depth = 0
    in_blockquote = False
    in_table = False
    table_rows = []

    def flush_list():
        nonlocal in_list
        if in_list:
            html_lines.append(f"</{in_list}>")
            in_list = None

    def flush_blockquote():
        nonlocal in_blockquote
        if in_blockquote:
            html_lines.append("</blockquote>")
            in_blockquote = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            html_lines.append("<table>")
            for r_idx, row in enumerate(table_rows):
                html_lines.append("<tr>")
                tag = "th" if r_idx == 0 else "td"
                for cell in row:
                    html_lines.append(f"<{tag}>{process_inline(cell.strip())}</{tag}>")
                html_lines.append("</tr>")
            html_lines.append("</table>")
            in_table = False
            table_rows = []

    while i < len(lines):
        line = lines[i]

        # ── Blocchi di codice ──────────────────────────────────────────────
        if line.startswith("```"):
            if not in_code_block:
                flush_list()
                flush_blockquote()
                flush_table()
                in_code_block = True
                code_lang = line[3:].strip()
                code_lines = []
            else:
                in_code_block = False
                lang_attr = f' class="language-{code_lang}"' if code_lang else ""
                escaped = xml_escape("\n".join(code_lines))
                html_lines.append(f"<pre><code{lang_attr}>{escaped}</code></pre>")
                code_lines = []
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # ── Tabelle ────────────────────────────────────────────────────────
        if line.startswith("|") and line.endswith("|"):
            # Riga separatore: |---|---|
            if re.match(r"^\|[\s\-:|]+\|$", line):
                i += 1
                continue
            in_table = True
            cells = [c for c in line.split("|") if c != ""][:]
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            flush_table()

        # ── Linea orizzontale ──────────────────────────────────────────────
        if re.match(r"^[-*_]{3,}\s*$", line):
            flush_list()
            flush_blockquote()
            html_lines.append("<hr />")
            i += 1
            continue

        # ── Blockquote ─────────────────────────────────────────────────────
        if line.startswith("> "):
            if not in_blockquote:
                flush_list()
                html_lines.append("<blockquote>")
                in_blockquote = True
            html_lines.append(f"<p>{process_inline(line[2:])}</p>")
            i += 1
            continue
        elif in_blockquote:
            flush_blockquote()

        # ── Intestazioni ───────────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            flush_list()
            flush_blockquote()
            level = len(m.group(1))
            text = process_inline(m.group(2))
            html_lines.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # ── Liste ──────────────────────────────────────────────────────────
        ul_m = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
        ol_m = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
        list_m = ul_m or ol_m
        if list_m:
            list_type = "ul" if ul_m else "ol"
            text = process_inline(list_m.group(2))
            if in_list != list_type:
                if in_list:
                    html_lines.append(f"</{in_list}>")
                flush_blockquote()
                html_lines.append(f"<{list_type}>")
                in_list = list_type
            html_lines.append(f"<li>{text}</li>")
            i += 1
            continue
        elif in_list:
            flush_list()

        # ── Riga vuota ─────────────────────────────────────────────────────
        if line.strip() == "":
            flush_blockquote()
            i += 1
            continue

        # ── Paragrafo ──────────────────────────────────────────────────────
        html_lines.append(f"<p>{process_inline(line)}</p>")
        i += 1

    # Chiudi tag aperti
    flush_list()
    flush_blockquote()
    flush_table()
    if in_code_block and code_lines:
        html_lines.append(f"<pre><code>{xml_escape(chr(10).join(code_lines))}</code></pre>")

    return "\n".join(html_lines)


# ─── Scanner del vault ────────────────────────────────────────────────────────

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}
IMAGE_FOLDER_NAMES = {"assets", "attachments", "images", "img", "media", "files", "static"}


def find_image(name: str, search_dirs: list[Path]) -> Path | None:
    """Cerca un'immagine per nome in una lista di cartelle."""
    for d in search_dirs:
        candidate = d / name
        if candidate.exists():
            return candidate
        # Ricerca ricorsiva nella cartella
        for p in d.rglob(name):
            return p
    return None


def collect_articles(vault: Path) -> list[dict]:
    """
    Raccoglie tutti gli articoli dal vault.
    Supporta le tre strutture più comuni di Obsidian.
    """
    articles = []

    # Raccoglie tutte le immagini nel vault (mappa nome → path)
    all_images: dict[str, Path] = {}
    for ext in IMAGE_EXTENSIONS:
        for img in vault.rglob(f"*{ext}"):
            all_images[img.name] = img

    def make_image_dirs(md_file: Path) -> list[Path]:
        """Cartelle in cui cercare le immagini per un dato file .md."""
        dirs = [md_file.parent]
        # Cartelle immagini standard nella stessa directory
        for name in IMAGE_FOLDER_NAMES:
            p = md_file.parent / name
            if p.is_dir():
                dirs.append(p)
        # Cartelle immagini standard nella root del vault
        for name in IMAGE_FOLDER_NAMES:
            p = vault / name
            if p.is_dir():
                dirs.append(p)
        return dirs

    for md_file in sorted(vault.rglob("*.md")):
        # Ignora file nelle cartelle nascoste Obsidian
        if any(part.startswith(".") for part in md_file.parts):
            continue

        content = md_file.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(content)

        # Metadati dall'articolo
        title = meta.get("title") or meta.get("titolo") or md_file.stem
        date_str = meta.get("date") or meta.get("data") or meta.get("created") or ""
        tags = meta.get("tags") or meta.get("tag") or []
        categories = meta.get("categories") or meta.get("categoria") or meta.get("category") or []
        status = meta.get("status") or meta.get("stato") or "publish"
        excerpt = meta.get("excerpt") or meta.get("descrizione") or meta.get("description") or ""
        author = meta.get("author") or meta.get("autore") or "admin"

        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",")]

        # Data
        try:
            pub_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.fromtimestamp(md_file.stat().st_mtime)
        except ValueError:
            pub_date = datetime.fromtimestamp(md_file.stat().st_mtime)
        pub_date = random_time(pub_date)

        # Immagini referenziate nel testo
        image_dirs = make_image_dirs(md_file)
        referenced_images: dict[str, Path] = {}

        def collect_image(name: str) -> str:
            """Segna l'immagine come usata e restituisce il nome."""
            img_path = find_image(name, image_dirs)
            if img_path is None and name in all_images:
                img_path = all_images[name]
            if img_path:
                referenced_images[name] = img_path
            return name  # placeholder; sarà sostituito in fase di export

        # Scansione immagini nel body (per la raccolta)
        for m in re.finditer(r"!\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", body):
            collect_image(m.group(1).strip())
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", body):
            src = m.group(1)
            if not src.startswith("http"):
                collect_image(Path(src).name)

        # Immagine di copertina (featured image)
        featured_image_name = meta.get("featured_image") or meta.get("copertina") or meta.get("cover_image") or ""
        featured_image_path: Path | None = None
        if featured_image_name:
            featured_image_path = find_image(featured_image_name, image_dirs)
            if featured_image_path is None and featured_image_name in all_images:
                featured_image_path = all_images[featured_image_name]

        articles.append({
            "md_file": md_file,
            "title": title,
            "slug": slugify(title),
            "body": body,
            "meta": meta,
            "pub_date": pub_date,
            "tags": [t for t in tags if t],
            "categories": [c for c in categories if c],
            "status": status if status in ("publish", "draft", "private") else "publish",
            "excerpt": excerpt,
            "author": author,
            "images": referenced_images,   # {nome_file: path_assoluto}
            "image_dirs": image_dirs,
            "featured_image_name": featured_image_name,
            "featured_image_path": featured_image_path,
        })

    return articles


# ─── Generatore WXR ───────────────────────────────────────────────────────────

WXR_HEADER = '''<?xml version="1.0" encoding="UTF-8" ?>
<!-- Generato da obsidian_to_wordpress.py -->
<!-- Importa in WordPress: Strumenti → Importa → WordPress -->
<rss version="2.0"
  xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:wfw="http://wellformedweb.org/CommentAPI/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:wp="http://wordpress.org/export/1.2/"
>
<channel>
  <title>{site_title}</title>
  <link>{site_url}</link>
  <description>{site_desc}</description>
  <pubDate>{pub_date}</pubDate>
  <language>{language}</language>
  <wp:wxr_version>1.2</wp:wxr_version>
  <wp:base_site_url>{site_url}</wp:base_site_url>
  <wp:base_blog_url>{site_url}</wp:base_blog_url>
  <wp:author>
    <wp:author_id>1</wp:author_id>
    <wp:author_login>{author}</wp:author_login>
    <wp:author_email>{author_email}</wp:author_email>
    <wp:author_display_name><![CDATA[{author}]]></wp:author_display_name>
    <wp:author_first_name><![CDATA[]]></wp:author_first_name>
    <wp:author_last_name><![CDATA[]]></wp:author_last_name>
  </wp:author>
'''

WXR_FOOTER = '''</channel>
</rss>
'''


def generate_wxr(
    articles: list[dict],
    site_url: str,
    site_title: str = "Il mio blog",
    site_desc: str = "",
    author: str = "admin",
    author_email: str = "admin@example.com",
    language: str = "it-IT",
    default_status: str | None = None,
    embed_images: bool = False,
    images_base_url: str | None = None,
) -> str:
    """Genera il file WXR come stringa XML."""

    now = datetime.now()
    pub_date_rfc = now.strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml_parts = [WXR_HEADER.format(
        site_title=xml_escape(site_title),
        site_url=site_url.rstrip("/"),
        site_desc=xml_escape(site_desc),
        pub_date=pub_date_rfc,
        language=language,
        author=xml_escape(author),
        author_email=xml_escape(author_email),
    )]

    # Raccogli categorie e tag unici
    all_categories: set[str] = set()
    all_tags: set[str] = set()
    for a in articles:
        all_categories.update(a["categories"])
        all_tags.update(a["tags"])

    for cat in sorted(all_categories):
        xml_parts.append(f'''  <wp:category>
    <wp:term_id>{abs(hash(cat)) % 10000}</wp:term_id>
    <wp:category_nicename>{xml_escape(slugify(cat))}</wp:category_nicename>
    <wp:category_parent></wp:category_parent>
    <wp:cat_name><![CDATA[{cat}]]></wp:cat_name>
  </wp:category>''')

    for tag in sorted(all_tags):
        xml_parts.append(f'''  <wp:tag>
    <wp:term_id>{abs(hash("tag_" + tag)) % 10000}</wp:term_id>
    <wp:tag_slug>{xml_escape(slugify(tag))}</wp:tag_slug>
    <wp:tag_name><![CDATA[{tag}]]></wp:tag_name>
  </wp:tag>''')

    post_id = 1
    attachment_id = 10000

    for article in articles:
        post_id += 1
        title = article["title"]
        slug = article["slug"]
        body = article["body"]
        pub_date = article["pub_date"]
        tags = article["tags"]
        categories = article["categories"]
        status = default_status or article["status"]
        excerpt = article["excerpt"]
        art_author = article["author"] or author
        images: dict[str, Path] = article["images"]
        image_dirs = article["image_dirs"]
        featured_image_name: str = article.get("featured_image_name", "")
        featured_image_path: Path | None = article.get("featured_image_path")

        date_fmt = pub_date.strftime("%Y-%m-%d %H:%M:%S")
        date_rfc = pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        guid = f"{site_url.rstrip('/')}/{slug}/"

        # ── Image resolver per questo articolo ────────────────────────────
        # Mappa nome_file → URL finale (o data URI se embed)
        image_url_map: dict[str, str] = {}
        attachment_items: list[str] = []

        featured_attachment_id: int | None = None

        for img_name, img_path in images.items():
            if embed_images:
                try:
                    _, data_uri = image_to_base64(img_path)
                    image_url_map[img_name] = data_uri
                except Exception:
                    image_url_map[img_name] = img_name
            else:
                base = (images_base_url or f"{site_url.rstrip('/')}/wp-content/uploads/{pub_date.year}/{pub_date.month:02d}").rstrip("/")
                img_url = f"{base}/{img_name}"
                image_url_map[img_name] = img_url

                # Aggiungi attachment item
                attachment_id += 1
                attachment_items.append(f'''  <item>
    <title>{xml_escape(img_name)}</title>
    <link>{img_url}</link>
    <pubDate>{date_rfc}</pubDate>
    <dc:creator><![CDATA[{art_author}]]></dc:creator>
    <guid isPermaLink="false">{img_url}</guid>
    <description></description>
    <content:encoded><![CDATA[]]></content:encoded>
    <excerpt:encoded><![CDATA[]]></excerpt:encoded>
    <wp:post_id>{attachment_id}</wp:post_id>
    <wp:post_date>{date_fmt}</wp:post_date>
    <wp:post_date_gmt>{date_fmt}</wp:post_date_gmt>
    <wp:comment_status>closed</wp:comment_status>
    <wp:ping_status>closed</wp:ping_status>
    <wp:post_name>{xml_escape(slugify(img_name))}</wp:post_name>
    <wp:status>inherit</wp:status>
    <wp:post_parent>{post_id}</wp:post_parent>
    <wp:menu_order>0</wp:menu_order>
    <wp:post_type>attachment</wp:post_type>
    <wp:post_password></wp:post_password>
    <wp:is_sticky>0</wp:is_sticky>
    <wp:attachment_url>{img_url}</wp:attachment_url>
  </item>''')

        # ── Featured image (immagine di copertina) ────────────────────────
        if featured_image_name and not embed_images:
            fi_path = featured_image_path
            # Se non trovata prima, prova nei dirs
            if fi_path is None:
                fi_path = find_image(featured_image_name, image_dirs)

            if fi_path is not None or featured_image_name:
                base = (images_base_url or f"{site_url.rstrip('/')}/wp-content/uploads/{pub_date.year}/{pub_date.month:02d}").rstrip("/")
                fi_url = f"{base}/{featured_image_name}"
                attachment_id += 1
                featured_attachment_id = attachment_id
                # Aggiungi anche alla mappa URL (utile se viene usata nel body)
                image_url_map[featured_image_name] = fi_url
                attachment_items.append(f'''  <item>
    <title>{xml_escape(featured_image_name)}</title>
    <link>{fi_url}</link>
    <pubDate>{date_rfc}</pubDate>
    <dc:creator><![CDATA[{art_author}]]></dc:creator>
    <guid isPermaLink="false">{fi_url}</guid>
    <description></description>
    <content:encoded><![CDATA[]]></content:encoded>
    <excerpt:encoded><![CDATA[]]></excerpt:encoded>
    <wp:post_id>{featured_attachment_id}</wp:post_id>
    <wp:post_date>{date_fmt}</wp:post_date>
    <wp:post_date_gmt>{date_fmt}</wp:post_date_gmt>
    <wp:comment_status>closed</wp:comment_status>
    <wp:ping_status>closed</wp:ping_status>
    <wp:post_name>{xml_escape(slugify(featured_image_name))}</wp:post_name>
    <wp:status>inherit</wp:status>
    <wp:post_parent>{post_id}</wp:post_parent>
    <wp:menu_order>0</wp:menu_order>
    <wp:post_type>attachment</wp:post_type>
    <wp:post_password></wp:post_password>
    <wp:is_sticky>0</wp:is_sticky>
    <wp:attachment_url>{fi_url}</wp:attachment_url>
  </item>''')

        # ── Converti Markdown → HTML ───────────────────────────────────────
        def resolve_image(name: str) -> str:
            img_path = find_image(name, image_dirs)
            if img_path is None:
                img_path = images.get(name)
            if img_path and embed_images:
                try:
                    _, data_uri = image_to_base64(img_path)
                    return data_uri
                except Exception:
                    pass
            return image_url_map.get(name, name)

        html_content = md_to_html(body, image_resolver=resolve_image)

        # ── Costruisci item XML ────────────────────────────────────────────
        cat_xml = ""
        for cat in categories:
            cat_xml += f'    <category domain="category" nicename="{xml_escape(slugify(cat))}"><![CDATA[{cat}]]></category>\n'
        for tag in tags:
            cat_xml += f'    <category domain="post_tag" nicename="{xml_escape(slugify(tag))}"><![CDATA[{tag}]]></category>\n'

        # _thumbnail_id postmeta per la featured image
        thumbnail_meta_xml = ""
        if featured_attachment_id is not None:
            thumbnail_meta_xml = f'''    <wp:postmeta>
      <wp:meta_key>_thumbnail_id</wp:meta_key>
      <wp:meta_value><![CDATA[{featured_attachment_id}]]></wp:meta_value>
    </wp:postmeta>
'''

        xml_parts.append(f'''  <item>
    <title>{xml_escape(title)}</title>
    <link>{guid}</link>
    <pubDate>{date_rfc}</pubDate>
    <dc:creator><![CDATA[{art_author}]]></dc:creator>
    <guid isPermaLink="false">{guid}</guid>
    <description></description>
    <content:encoded><![CDATA[{html_content}]]></content:encoded>
    <excerpt:encoded><![CDATA[{excerpt}]]></excerpt:encoded>
    <wp:post_id>{post_id}</wp:post_id>
    <wp:post_date>{date_fmt}</wp:post_date>
    <wp:post_date_gmt>{date_fmt}</wp:post_date_gmt>
    <wp:comment_status>open</wp:comment_status>
    <wp:ping_status>open</wp:ping_status>
    <wp:post_name>{xml_escape(slug)}</wp:post_name>
    <wp:status>{status}</wp:status>
    <wp:post_parent>0</wp:post_parent>
    <wp:menu_order>0</wp:menu_order>
    <wp:post_type>post</wp:post_type>
    <wp:post_password></wp:post_password>
    <wp:is_sticky>0</wp:is_sticky>
{cat_xml}{thumbnail_meta_xml}  </item>''')

        xml_parts.extend(attachment_items)

    xml_parts.append(WXR_FOOTER)
    return "\n".join(xml_parts)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Converte un vault Obsidian in formato WXR per WordPress",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Esportazione base
  python3 obsidian_to_wordpress.py --vault ~/Obsidian/Blog --url https://miosito.it

  # Con immagini in base64 (file XML standalone, più grande)
  python3 obsidian_to_wordpress.py --vault ~/Obsidian/Blog --url https://miosito.it --embed-images

  # Tutti gli articoli come bozze
  python3 obsidian_to_wordpress.py --vault ~/Obsidian/Blog --url https://miosito.it --status draft

  # Personalizzato
  python3 obsidian_to_wordpress.py --vault ~/Obsidian/Blog --output mio-export.xml \\
    --url https://miosito.it --title "Il mio blog" --author mario --author-email mario@example.com

Frontmatter YAML supportato nelle note Obsidian:
  ---
  title: Titolo dell'articolo
  date: 2024-01-15
  tags: [php, wordpress, tutorial]
  categories: [Tech, Guide]
  status: publish        # publish | draft | private
  author: mario
  excerpt: Breve descrizione
  featured_image: copertina.jpg   # immagine di copertina (nella stessa cartella del .md)
  ---
"""
    )
    parser.add_argument("--vault", "-v", required=True, help="Percorso della cartella vault Obsidian")
    parser.add_argument("--output", "-o", default="wordpress-export.xml", help="Nome del file XML di output (default: wordpress-export.xml)")
    parser.add_argument("--url", "-u", required=True, help="URL del sito WordPress (es. https://miosito.it)")
    parser.add_argument("--title", "-t", default="Il mio blog", help="Titolo del sito")
    parser.add_argument("--description", "-d", default="", help="Descrizione del sito")
    parser.add_argument("--author", "-a", default="admin", help="Username dell'autore (default: admin)")
    parser.add_argument("--author-email", default="admin@example.com", help="Email dell'autore")
    parser.add_argument("--language", default="it-IT", help="Lingua del blog (default: it-IT)")
    parser.add_argument("--status", choices=["publish", "draft", "private"], default=None,
                        help="Forza lo stato di tutti gli articoli (sovrascrive il frontmatter)")
    parser.add_argument("--embed-images", action="store_true",
                        help="Incorpora le immagini come base64 nel file XML (standalone, nessun upload separato)")
    parser.add_argument("--images-base-url", default=None,
                        help="URL base per le immagini (default: <url>/wp-content/uploads/YYYY/MM)")

    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERRORE: La cartella '{vault}' non esiste.", file=sys.stderr)
        sys.exit(1)

    print(f"Scansione vault: {vault}")
    articles = collect_articles(vault)

    if not articles:
        print("Nessuna nota .md trovata nel vault.", file=sys.stderr)
        sys.exit(1)

    print(f"Trovati {len(articles)} articoli:")
    total_images = 0
    for a in articles:
        n_img = len(a["images"])
        total_images += n_img
        img_str = f" ({n_img} immagini)" if n_img else ""
        print(f"  • {a['title']}{img_str}")

    print(f"\nImmagini totali referenziate: {total_images}")
    if not args.embed_images and total_images > 0:
        print("  ℹ  Le immagini NON sono incorporate nel XML.")
        print("     Durante l'importazione WordPress spunterà 'Scarica e importa allegati'.")
        print("     Assicurati che le immagini siano accessibili via URL, oppure usa --embed-images.")

    print("\nGenerazione XML WXR...")
    wxr = generate_wxr(
        articles=articles,
        site_url=args.url,
        site_title=args.title,
        site_desc=args.description,
        author=args.author,
        author_email=args.author_email,
        language=args.language,
        default_status=args.status,
        embed_images=args.embed_images,
        images_base_url=args.images_base_url,
    )

    output = Path(args.output)
    output.write_text(wxr, encoding="utf-8")
    size_kb = output.stat().st_size / 1024
    print(f"\n✓ File creato: {output} ({size_kb:.1f} KB)")
    print("\nProssimi passi:")
    print("  1. Apri il pannello WordPress → Strumenti → Importa")
    print("  2. Clicca 'Installa' sotto 'WordPress'")
    print("  3. Clicca 'Esegui importatore'")
    print(f"  4. Carica il file: {output.name}")
    if not args.embed_images and total_images > 0:
        print("  5. Spunta 'Scarica e importa allegati' per importare le immagini")


if __name__ == "__main__":
    main()
