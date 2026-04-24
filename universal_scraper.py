"""
Univerzalni scraper dynamickych stranek.

Dva rezimy:
  1) Interaktivni  — otevre se prohlizec, kliknes na prvek, ktery chces stahnout.
                     Skript si vygeneruje unikatni CSS selektor a pak data extrahuje.
  2) CLI            — zadas URL + selektor a skript rovnou stahne data.

Podporuje libovolny prvek:
    - <table> / <tbody>   -> CSV + JSON (radky jako zaznamy)
    - <ul> / <ol>          -> JSON (seznam polozek) + TXT
    - odkazy <a>           -> JSON (text + href) + TXT
    - obrazky <img>        -> JSON (alt + src) + TXT
    - libovolny div/span   -> TXT (cisty text) + HTML (raw)
    - vice prvku (selector vraci vic match) -> JSON (pole)

Instalace:
    pip install playwright beautifulsoup4
    playwright install chromium

Pouziti:
    # Interaktivni vyber kliknutim
    python universal_scraper.py https://example.com --pick

    # Prime zadani selektoru
    python universal_scraper.py https://example.com --selector ".product-card"

    # Vlastni nazev vystupnich souboru
    python universal_scraper.py https://example.com --pick --output produkty
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ============================================================================
#  INTERAKTIVNI VYBER — JS, ktery se injectne do stranky
# ============================================================================
#
# Uzivateli zvyrazni prvek pod mysi, po kliknuti vygeneruje unikatni CSS
# selektor a ulozi ho do window.__picked_selector.
# Skript pote hodnotu precte a ukonci browser.
#
PICKER_JS = r"""
() => {
    // Zrusime defaultni chovani stranky (odkazy, formulare) behem vybirani
    const style = document.createElement('style');
    style.textContent = `
        .__picker_highlight {
            outline: 3px solid #ff3860 !important;
            outline-offset: 2px !important;
            cursor: crosshair !important;
            background: rgba(255, 56, 96, 0.1) !important;
        }
        .__picker_banner {
            position: fixed; top: 0; left: 0; right: 0; z-index: 2147483647;
            background: #1f2937; color: white; padding: 10px 16px;
            font-family: -apple-system, sans-serif; font-size: 14px;
            text-align: center; border-bottom: 2px solid #ff3860;
        }
    `;
    document.head.appendChild(style);

    const banner = document.createElement('div');
    banner.className = '__picker_banner';
    banner.textContent = '👆 Klikni na prvek, ktery chces stahnout (ESC pro zruseni)';
    document.body.appendChild(banner);

    let lastEl = null;

    function cssPath(el) {
        // Vygeneruje co nejkratsi unikatni CSS selektor
        if (!(el instanceof Element)) return '';
        const path = [];
        while (el.nodeType === Node.ELEMENT_NODE && el !== document.body) {
            let selector = el.nodeName.toLowerCase();
            if (el.id) {
                selector = '#' + CSS.escape(el.id);
                path.unshift(selector);
                break;
            }
            // pridej tridy (max 2, aby to bylo citelne)
            const classes = Array.from(el.classList)
                .filter(c => !c.startsWith('__picker'))
                .slice(0, 2);
            if (classes.length) {
                selector += '.' + classes.map(c => CSS.escape(c)).join('.');
            }
            // pozice mezi sourozenci stejneho typu
            const parent = el.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(
                    s => s.nodeName === el.nodeName
                );
                if (siblings.length > 1) {
                    const idx = siblings.indexOf(el) + 1;
                    selector += `:nth-of-type(${idx})`;
                }
            }
            path.unshift(selector);
            el = el.parentElement;
        }
        return path.join(' > ');
    }

    function onMove(e) {
        const el = e.target;
        if (el === banner || el.closest('.__picker_banner')) return;
        if (lastEl) lastEl.classList.remove('__picker_highlight');
        el.classList.add('__picker_highlight');
        lastEl = el;
        banner.textContent = `👆 ${el.tagName.toLowerCase()}` +
            (el.id ? '#' + el.id : '') +
            (el.className && typeof el.className === 'string'
                ? '.' + el.className.split(' ').filter(c => !c.startsWith('__picker')).slice(0,2).join('.')
                : '') +
            '  —  klikni pro vyber';
    }

    function onClick(e) {
        e.preventDefault();
        e.stopPropagation();
        const el = e.target;
        if (el === banner || el.closest('.__picker_banner')) return;
        const selector = cssPath(el);
        window.__picked_selector = selector;
        banner.textContent = `✓ Vybrano: ${selector}`;
        banner.style.background = '#059669';
        if (lastEl) lastEl.classList.remove('__picker_highlight');
    }

    function onKey(e) {
        if (e.key === 'Escape') {
            window.__picked_selector = '__CANCELLED__';
        }
    }

    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
}
"""


# ============================================================================
#  NACTENI STRANKY + VOLITERNE INTERAKTIVNI VYBER
# ============================================================================
def fetch_page(url: str, pick: bool = False, selector: str = None, timeout: int = 60000):
    """
    Vrati (html, pouzity_selektor).
    Pokud pick=True, otevre viditelny prohlizec a necha uzivatele kliknout.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not pick)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        print(f"[info] Nacitam {url} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        page.wait_for_timeout(1000)  # dej JS chvili na dokresleni

        chosen_selector = selector

        if pick:
            print("[info] Spoustim interaktivni vyber — klikni na prvek v prohlizeci.")
            page.evaluate(PICKER_JS)

            # Cekej, nez uzivatel klikne (az 5 minut)
            try:
                page.wait_for_function(
                    "window.__picked_selector !== undefined",
                    timeout=300000
                )
                chosen_selector = page.evaluate("window.__picked_selector")
            except PlaywrightTimeout:
                browser.close()
                raise RuntimeError("Vyprsel cas pro vyber (5 minut).")

            if chosen_selector == "__CANCELLED__":
                browser.close()
                raise RuntimeError("Vyber zrusen uzivatelem.")

            print(f"[info] Vybrany selektor: {chosen_selector}")
            page.wait_for_timeout(500)

        elif selector:
            try:
                page.wait_for_selector(selector, timeout=timeout)
            except PlaywrightTimeout:
                print(f"[warn] Selektor '{selector}' se neobjevil do {timeout} ms.")

        html = page.content()
        browser.close()
        return html, chosen_selector


# ============================================================================
#  EXTRAKCE OBSAHU PODLE TYPU PRVKU
# ============================================================================
def classify_element(el: Tag) -> str:
    """Rozhodne, jaky typ obsahu element reprezentuje."""
    tag = el.name.lower()
    if tag in ("table", "tbody"):
        return "table"
    if tag in ("ul", "ol"):
        return "list"
    if tag == "a":
        return "link"
    if tag == "img":
        return "image"
    if tag == "form":
        return "form"
    # Heuristika: pokud kontejner obsahuje vic opakujicich se deti se stejnou tridou
    children = [c for c in el.find_all(recursive=False) if isinstance(c, Tag)]
    if len(children) >= 3:
        classes = [tuple(c.get("class") or []) for c in children]
        if len(set(classes)) <= 2 and classes[0]:
            return "repeating"
    return "generic"


def extract_table(el: Tag):
    """Vrati (headers, rows) z <table> nebo <tbody>."""
    if el.name == "table":
        tbody = el.find("tbody") or el
        thead = el.find("thead")
    else:
        tbody = el
        parent_table = el.find_parent("table")
        thead = parent_table.find("thead") if parent_table else None

    headers = []
    if thead:
        header_row = thead.find("tr")
        if header_row:
            headers = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]

    rows = []
    for tr in tbody.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    if not headers and rows:
        max_cols = max(len(r) for r in rows)
        headers = [f"col_{i+1}" for i in range(max_cols)]
    rows = [r + [""] * (len(headers) - len(r)) for r in rows]
    return headers, rows


def extract_list(el: Tag):
    """Vrati list polozek z <ul>/<ol>."""
    items = []
    for li in el.find_all("li", recursive=False):
        link = li.find("a")
        item = {"text": li.get_text(strip=True)}
        if link and link.get("href"):
            item["href"] = link["href"]
        items.append(item)
    return items


def extract_links(el: Tag):
    """Vrati vsechny odkazy uvnitr elementu (nebo samotny element pokud je to <a>)."""
    if el.name == "a":
        links = [el]
    else:
        links = el.find_all("a")
    return [
        {"text": a.get_text(strip=True), "href": a.get("href", ""), "title": a.get("title", "")}
        for a in links
        if a.get("href")
    ]


def extract_images(el: Tag):
    """Vrati vsechny obrazky."""
    if el.name == "img":
        imgs = [el]
    else:
        imgs = el.find_all("img")
    return [
        {"alt": i.get("alt", ""), "src": i.get("src", ""), "title": i.get("title", "")}
        for i in imgs
    ]


def extract_repeating(el: Tag):
    """
    Opakujici se kontejner (napr. seznam produktu, clanku, karet).
    Kazde prime dite se prevede na slovnik s texty, odkazy a obrazky.
    """
    items = []
    for child in el.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        item = {
            "text": child.get_text(" ", strip=True),
        }
        links = extract_links(child)
        if links:
            item["links"] = links
        imgs = extract_images(child)
        if imgs:
            item["images"] = imgs
        items.append(item)
    return items


def extract_generic(el: Tag):
    """Jakykoliv jiny prvek — vrati text, HTML a atributy."""
    return {
        "tag": el.name,
        "text": el.get_text(" ", strip=True),
        "html": str(el),
        "attributes": dict(el.attrs),
    }


# ============================================================================
#  UKLADANI VYSTUPU
# ============================================================================
def save_outputs(kind: str, data, output_base: str):
    """Ulozi data ve vhodnych formatech podle typu."""
    base = Path(output_base)
    saved = []

    if kind == "table":
        headers, rows = data
        if not rows:
            print("[warn] Tabulka je prazdna.")
            return saved

        csv_path = base.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)
        saved.append(csv_path)
        print(f"[ok] CSV: {csv_path} ({len(rows)} radku)")

        json_path = base.with_suffix(".json")
        records = [dict(zip(headers, r)) for r in rows]
        json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(json_path)
        print(f"[ok] JSON: {json_path}")

    elif kind in ("list", "link", "image", "repeating"):
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(json_path)
        print(f"[ok] JSON: {json_path} ({len(data)} polozek)")

        # Navic pekny TXT pro rychle prohledeni
        txt_path = base.with_suffix(".txt")
        lines = []
        for item in data:
            if isinstance(item, dict):
                lines.append(" | ".join(f"{k}: {v}" for k, v in item.items() if v))
            else:
                lines.append(str(item))
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        saved.append(txt_path)
        print(f"[ok] TXT: {txt_path}")

    else:  # generic / form
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(json_path)
        print(f"[ok] JSON: {json_path}")

        txt_path = base.with_suffix(".txt")
        txt_path.write_text(data.get("text", "") if isinstance(data, dict) else str(data),
                            encoding="utf-8")
        saved.append(txt_path)
        print(f"[ok] TXT: {txt_path}")

        html_path = base.with_suffix(".html")
        html_path.write_text(data.get("html", "") if isinstance(data, dict) else "",
                             encoding="utf-8")
        saved.append(html_path)
        print(f"[ok] HTML: {html_path}")

    return saved


# ============================================================================
#  HLAVNI PIPELINE
# ============================================================================
def scrape(url: str, selector: str = None, pick: bool = False, output: str = "scraped"):
    html, used_selector = fetch_page(url, pick=pick, selector=selector)
    if not used_selector:
        raise ValueError("Nebyl zadan selektor ani zvolen prvek.")

    soup = BeautifulSoup(html, "html.parser")
    matches = soup.select(used_selector)

    if not matches:
        raise ValueError(f"Selektor '{used_selector}' nenasel zadny prvek.")

    print(f"[info] Nalezeno {len(matches)} prvku odpovidajicich selektoru.")

    # Pokud je jen jeden prvek, zpracuj ho podle typu.
    # Pokud je jich vic, povazuj to za opakujici se seznam.
    if len(matches) == 1:
        el = matches[0]
        kind = classify_element(el)
        print(f"[info] Detekovany typ prvku: {kind}")

        if kind == "table":
            data = extract_table(el)
        elif kind == "list":
            data = extract_list(el)
        elif kind == "link":
            data = extract_links(el)
        elif kind == "image":
            data = extract_images(el)
        elif kind == "repeating":
            data = extract_repeating(el)
        else:
            data = extract_generic(el)
    else:
        kind = "repeating"
        print(f"[info] Vice prvku — extrahuji jako opakujici se seznam.")
        data = []
        for el in matches:
            item = {"text": el.get_text(" ", strip=True)}
            links = extract_links(el)
            if links:
                item["links"] = links
            imgs = extract_images(el)
            if imgs:
                item["images"] = imgs
            data.append(item)

    save_outputs(kind, data, output)


def main():
    parser = argparse.ArgumentParser(
        description="Univerzalni scraper — stahne libovolny prvek z dynamicke stranky."
    )
    parser.add_argument("url", help="URL stranky")
    parser.add_argument("--pick", action="store_true",
                        help="Interaktivni vyber prvku kliknutim v prohlizeci")
    parser.add_argument("--selector", help="CSS selektor (pokud nepouzivas --pick)")
    parser.add_argument("--output", default="scraped",
                        help="Zaklad nazvu vystupnich souboru (vychozi: 'scraped')")
    args = parser.parse_args()

    if not args.pick and not args.selector:
        parser.error("Muses zadat bud --pick, nebo --selector.")

    try:
        scrape(args.url, selector=args.selector, pick=args.pick, output=args.output)
    except Exception as e:
        print(f"[chyba] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
