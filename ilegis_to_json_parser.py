#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, re, logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from bs4 import BeautifulSoup

from leg5_src.extractor.model import Entry, MetaInfo

# ---------- minimal PHP print_r Array(...) parser ----------
_KEY = re.compile(r"^\s*\[([^\]]+)\]\s*=>\s*(.*)$")
OPEN = re.compile(r"^\s*\($")
CLOSE = re.compile(r"^\s*\)\s*$")
WORD_ARRAY = re.compile(r"^\s*Array\s*$")


def parse_php_array(text: str):
    """Tiny parser for common print_r arrays: Array ( [k] => v ... )"""
    txt = text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    lines = [l.rstrip() for l in txt.splitlines() if l.strip() != ""]
    if not lines:
        return {}
    i = 0
    if WORD_ARRAY.match(lines[0]):  # skip "Array"
        i += 1
        if i < len(lines) and OPEN.match(lines[i]):
            i += 1

    def parse_value(j):
        if j < len(lines) and WORD_ARRAY.match(lines[j]):
            j += 1
            if j < len(lines) and OPEN.match(lines[j]): j += 1
            obj, j = parse_obj(j)
            return obj, j
        vals = [lines[j]]
        j += 1
        while j < len(lines) and not _KEY.match(lines[j]) and not CLOSE.match(lines[j]):
            vals.append(lines[j]);
            j += 1
        return "\n".join(vals).strip(), j

    def parse_obj(j):
        obj = {}
        while j < len(lines):
            if CLOSE.match(lines[j]): return obj, j + 1
            m = _KEY.match(lines[j])
            if not m: j += 1; continue
            k, after = m.group(1).strip(), m.group(2).strip()
            j += 1
            if after:
                if WORD_ARRAY.match(after):
                    if j < len(lines) and OPEN.match(lines[j]): j += 1
                    v, j = parse_obj(j)
                else:
                    lines.insert(j, after)
                    v, j = parse_value(j)
            else:
                v, j = parse_value(j)
            obj[k] = v
        return obj, j

    obj, _ = parse_obj(i)
    return _to_list_if_numeric(obj)


def _to_list_if_numeric(obj):
    if isinstance(obj, dict):
        keys = list(obj.keys())
        # If all keys are digits, try to coerce to a dense 0..N-1 list
        if keys and all(str(key).isdigit() for key in keys):
            pairs = sorted(((int(key), val) for key, val in obj.items()), key=lambda pair: pair[0])
            if all(pairs[i][0] == i for i in range(len(pairs))):
                return [_to_list_if_numeric(val) for _, val in pairs]
        # Otherwise keep it a dict and recurse
        return {key: _to_list_if_numeric(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_to_list_if_numeric(val) for val in obj]
    return obj


# ---------- numar/an helpers ----------
NUMAR_RE = re.compile(r"\[numar\]\s*=>\s*([^\s\]]+)")
AN_RE = re.compile(r"\[an\]\s*=>\s*([^\s\]]+)")


def _norm_printr(text: str) -> str:
    """Normalize HTML entities so [key] => is detectable."""
    if not text:
        return ""
    return (text
            .replace("&gt;", ">")
            .replace("&lt;", "<")
            .replace("&amp;", "&"))


def _find_numar_an_from_obj(obj):
    """Walk any dict/list tree and return first ('numar','an') seen as strings."""
    numar = an = None

    def walk(node):
        nonlocal numar, an
        if isinstance(node, dict):
            if numar is None and "numar" in node and node["numar"] is not None:
                numar = str(node["numar"]).strip()
            if an is None and "an" in node and node["an"] is not None:
                an = str(node["an"]).strip()
            for vv in node.values():
                if numar is not None and an is not None:
                    break
                walk(vv)
        elif isinstance(node, list):
            for vv in node:
                if numar is not None and an is not None:
                    break
                walk(vv)

    walk(obj)
    return numar, an


def _find_numar_an_from_text(text):
    """Fallback if array parse fails: regex scan raw text."""
    numar = None
    an = None
    m1 = NUMAR_RE.search(text or "")
    if m1: numar = m1.group(1).strip()
    m2 = AN_RE.search(text or "")
    if m2: an = m2.group(1).strip()
    return numar, an


def _find_numar_an_in_dom(soup: BeautifulSoup):
    """
    Extract numar/an from page-level form inputs, e.g.:
      <input id="numar" name="numar" value="1017">
      <input id="an"    name="an"    value="2009">
    Returns (numar, an) as strings or (None, None).
    """

    def pick(selectors):
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                val = el.get("value")
                if val is not None and str(val).strip() != "":
                    return str(val).strip()
        return None

    numar = pick(['input#numar', 'input[name="numar"]', 'input[id*="numar"]', 'input[name*="numar"]'])
    an = pick(['input#an', 'input[name="an"]', 'input[id*="an"]', 'input[name*="an"]'])
    return numar, an


def _extract_block(seg: str, key: str) -> str | None:
    """
    Return the value block for a key like [articol] => ...,
    stopping at the next [SOMEKEY] => or end of segment.
    Works with HTML entities and preserves newlines.
    """
    seg = _norm_printr(seg)
    # Match "[articol] => <anything until next key line or end>"
    m = re.search(
        rf"^\s*\[{re.escape(key)}\]\s*=>\s*(.*?)(?=\n\s*\[[A-Za-z0-9_]+\]\s*=>|\Z)",
        seg,
        re.S | re.M,
    )
    return m.group(1) if m else None


def _dedent_preserve_newlines(s: str) -> str:
    """Strip common left indentation and trim surrounding blank lines."""
    if s is None:
        return ""
    # normalize newlines
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    # drop leading/trailing empty lines
    while lines and lines[0].strip() == "": lines.pop(0)
    while lines and lines[-1].strip() == "": lines.pop()
    if not lines:
        return ""
    # compute common indent (spaces only—print_r uses spaces)
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() != ""]
    pad = min(indents) if indents else 0
    return "\n".join(l[pad:] if len(l) >= pad else l for l in lines)


# ---------- extraction from .col-lg-12 ----------
ARTICOL_ID = re.compile(r"^articol(\d+)$")


def extract_from_col_lg_12(soup: BeautifulSoup, log: logging.Logger, file_errors: list):
    """
    Yield one JSON-able dict per #articolNNNN block under any div.col-lg-12.
    Logs warnings if expected bits are missing.
    """
    page_numar, page_an = _find_numar_an_in_dom(soup)
    found_any = False
    for col in soup.select("div.col-lg-12"):
        for block in col.find_all("div", id=ARTICOL_ID):
            found_any = True
            m = ARTICOL_ID.match(block.get("id", ""))
            art_id = m.group(1) if m else None
            pre = block.find("pre")
            if not pre:
                msg = f"Missing <pre> for articol{art_id}"
                log.warning(msg);
                file_errors.append(msg)
            text = pre.get_text("\n", strip=True) if pre else ""

            numar = an = None
            if text and "Array" in text:
                try:
                    parsed_root = parse_php_array(text)
                    numar, an = _find_numar_an_from_obj(parsed_root)
                except Exception:
                    pass
            if numar is None or an is None:
                rx_numar, rx_an = _find_numar_an_from_text(text)
                numar = numar or rx_numar
                an = an or rx_an
            if numar is None: numar = page_numar
            if an is None: an = page_an

            header = block.find_previous_sibling("div", class_="col-lg-12 societateContainer")
            if not header:
                log.warning(f"Missing societateContainer for articol{art_id}")
            a = header.find("a") if header else None
            company = a.get_text(strip=True) if a else None
            href = a.get("href") if a and a.has_attr("href") else None

            parent_classes = " ".join(col.get("class", []))
            m_bull = re.search(r"listaarticole_(\d+)", parent_classes)
            bulletin_id = m_bull.group(1) if m_bull else None
            if not bulletin_id:
                log.warning(f"No bulletin_id (listaarticole_XXXX) found for articol{art_id}")

            yield {
                "type": "article",
                "company": company,
                "article_id": art_id,
                "bulletin_id": bulletin_id,
                "list_parent_classes": parent_classes or None,
                "collapse_id": f"articol{art_id}",
                "source_href": href,
                "text": text,
                "numar": numar,
                "an": an,
            }
    if not found_any:
        log.info("No articol* blocks found under any .col-lg-12")


# ---------- robust modal extractor ----------
def _get_articole_block(raw: str):
    lines = raw.splitlines()
    for i, l in enumerate(lines):
        if re.search(r"\[articole\]\s*=>\s*Array\s*$", l):
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*\(\s*$", lines[j]):
                j += 1
            if j >= len(lines): return None
            depth = 1;
            j += 1;
            start = j
            while j < len(lines) and depth > 0:
                if j + 1 < len(lines) and re.match(r"^\s*Array\s*$", lines[j]) and re.match(r"^\s*\(\s*$",
                                                                                            lines[j + 1]):
                    depth += 1;
                    j += 2;
                    continue
                if re.match(r"^\s*\(\s*$", lines[j]): depth += 1; j += 1; continue
                if re.match(r"^\s*\)\s*$", lines[j]): depth -= 1; j += 1; continue
                j += 1
            return "\n".join(lines[start:j - 1])
    return None


def _split_top_level_articole_items(block_text: str):
    lines = block_text.splitlines()
    items, i = [], 0
    while i < len(lines):
        if re.match(r"^\s*\[\d+\]\s*=>\s*Array\s*$", lines[i]) and i + 1 < len(lines) and re.match(r"^\s*\(\s*$",
                                                                                                   lines[i + 1]):
            depth = 1;
            i += 2;
            start = i
            while i < len(lines) and depth > 0:
                if i + 1 < len(lines) and re.match(r"^\s*Array\s*$", lines[i]) and re.match(r"^\s*\(\s*$",
                                                                                            lines[i + 1]):
                    depth += 1;
                    i += 2;
                    continue
                if re.match(r"^\s*\(\s*$", lines[i]): depth += 1; i += 1; continue
                if re.match(r"^\s*\)\s*$", lines[i]): depth -= 1; i += 1; continue
                i += 1
            items.append("\n".join(lines[start:i - 1]))
        else:
            i += 1
    return items


def _parse_articole_item(seg: str):
    def grab_scalar(name):
        m = re.search(rf"\[{re.escape(name)}\]\s*=>\s*(?!Array)(.*)", seg)
        return m.group(1).strip() if m else None

    def grab_array_first(name):
        m = re.search(rf"\[{re.escape(name)}\]\s*=>\s*Array\s*\(\s*\[\d+\]\s*=>\s*([^\)\n]*)", seg, re.S)
        return m.group(1).strip() if m else None

    company = (grab_scalar("numesocietate") or grab_scalar("numesocietateinit") or "").strip()

    articol_raw = _extract_block(seg, "articol")
    articol_text = _dedent_preserve_newlines(articol_raw)

    # NEW: keep the exact print_r item slice (dedented) for export
    print_r_item = _dedent_preserve_newlines(seg)

    return {
        "id": grab_scalar("id"),
        "company": company,
        "title": grab_scalar("titlu") or "",
        "regcom": grab_array_first("regcom") or "",
        "cif": grab_array_first("cif") or "",
        "buletinid": grab_scalar("buletinid") or "",
        "articol_text": articol_text,  # cleaned body for "text"
        "print_r_item": print_r_item,  # <<< the whole [id]..[titlu] block you asked for
    }


def _extract_articles_from_print_r(raw: str):
    """
    Robust extractor for articles list from a modal <pre> print_r.
    Works even if the general PHP array parser squashes siblings.
    """
    block = _get_articole_block(raw)
    if not block:
        return []
    parts = _split_top_level_articole_items(block)
    return [_parse_articole_item(p) for p in parts]


def extract_from_modals(soup: BeautifulSoup, log: logging.Logger):
    """
    Yield:
      - one dict per modal summarizing companies/articles found
      - and one dict per modal-article item (type='modal_article') for convenience
    """
    page_numar, page_an = _find_numar_an_in_dom(soup)
    modals = soup.select("div.modal.fade.bs-example-modal-lg")
    if not modals:
        log.info("No modals (bs-example-modal-lg) found")

    for idx, modal in enumerate(modals, start=1):
        modal_numar = modal_an = None
        companies = []
        items_out = []

        pres = modal.find_all("pre")
        used_pre = False
        for pre in pres:
            # IMPORTANT: don't strip; preserve line breaks for depth splitter
            raw = pre.get_text("\n", strip=False)
            if not raw:
                continue

            # only handle <pre> that actually has the articole list
            block = _get_articole_block(raw)
            if not block:
                continue

            used_pre = True

            # try to pick up numar/an from the overall dump as a convenience
            try:
                parsed_root = parse_php_array(raw)
                n, a = _find_numar_an_from_obj(parsed_root)
                if n: modal_numar = modal_numar or n
                if a: modal_an = modal_an or a
            except Exception:
                pass

            # split the articole block into top-level items and parse each
            items = _split_top_level_articole_items(block)
            for seg in items:
                rec = _parse_articole_item(seg)

                # prefer 'numesocietate', fall back to 'numesocietateinit'
                comp = rec.get("company")
                if not comp:
                    # if your _parse_articole_item doesn’t expose init, do it here:
                    m = re.search(r"\[numesocietateinit\]\s*=>\s*(?!Array)(.*)", seg)
                    if m:
                        comp = m.group(1).strip()
                        rec["company"] = comp

                if comp:
                    companies.append(comp)

                items_out.append({
                    "type": "modal_article",
                    "modal_index": idx,
                    "numar": modal_numar or page_numar,
                    "an": modal_an or page_an,
                    **rec
                })

        # Fallback: no print_r articole found; try visible text
        if not used_pre:
            body_text = modal.get_text("\n", strip=True)
            for m in re.finditer(r"\b([A-Z0-9][A-Z0-9\.\-\s&]+?)\s*-\s*S\.R\.L\.", body_text):
                name = m.group(1).strip()
                if name not in companies:
                    companies.append(name)

        if companies or items_out:
            yield {
                "type": "modal",
                "modal_index": idx,
                "numar": modal_numar or page_numar,
                "an": modal_an or page_an,
                "companies": companies,
                "items": items_out,
            }


# ---------- logging setup ----------
def setup_logger(logfile: Path) -> logging.Logger:
    logger = logging.getLogger("slim_extract")
    logger.setLevel(logging.INFO)
    # clear handlers if re-run in same session
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # console
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    # rotating file (5MB, keep last 3)
    fh = RotatingFileHandler(logfile, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)

    logger.info("=== New run ===")
    return logger


# ---------- per-file driver ----------
def process_file(html_path: Path, out_dir: Path, log: logging.Logger):
    per_file_errors = []
    created_articles = 0
    created_modals = 0
    created_modal_articles = 0

    try:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    except Exception as e:
        log.error(f"Failed to read/parse HTML: {html_path} | {e}")
        return {"file": html_path.name, "articles": 0, "modals": 0, "modal_articles": 0, "errors": [f"read_error: {e}"]}

    # 1) articole din .col-lg-12
    for item in extract_from_col_lg_12(soup, log, per_file_errors):
        try:
            entry = Entry(
                type="article",
                company_name=item.get("company"),
                article_id=item.get("article_id"),
                bulletin_id=item.get("bulletin_id"),
                list_parent_classes=item.get("list_parent_classes"),
                collapse_id=item.get("collapse_id"),
                source_href=item.get("source_href"),
                raw_text=item.get("text") or "",
                number=item.get("numar"),
                year=item.get("an"),
                meta=MetaInfo()  # gol, că nu extragem meta aici
            )
            comp = (entry.company_name or "unknown").lower().replace(" ", "")
            out = out_dir / f"{comp}.{entry.article_id}.{entry.bulletin_id}.json"
            out.write_text(json.dumps(entry.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            created_articles += 1
            log.info(f"[article] {html_path.name} -> {out.name}")
        except Exception as e:
            msg = f"write_article_error(articol{item.get('article_id')}): {e}"
            per_file_errors.append(msg)
            log.error(msg)

    # 2) articole din modale
    for modal in extract_from_modals(soup, log):
        try:
            numar = modal.get("numar")
            an = modal.get("an")

            for it in modal.get("items", []):
                if it.get("type") != "modal_article":
                    continue

                entry = Entry(
                    type="article",
                    company_name=it.get("company"),
                    article_id=it.get("id"),
                    bulletin_id=it.get("buletinid"),
                    raw_text=it.get("articol_text") or "",
                    number=numar,
                    year=an,
                    meta=MetaInfo()  # gol
                )

                slug = (entry.company_name or "unknown").lower().replace(" ", "")
                out = out_dir / f"{slug}.{entry.article_id}.{entry.bulletin_id}.json"
                out.write_text(json.dumps(entry.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
                created_modals += 1
                log.info(f"[modal_article] {html_path.name} -> {out.name}")

        except Exception as e:
            msg = f"write_modal_error(modal#{modal.get('modal_index')}): {e}"
            per_file_errors.append(msg)
            log.error(msg)

    return {
        "file": html_path.name,
        "articles": created_articles,
        "modals": created_modals,
        "modal_articles": created_modal_articles,
        "errors": per_file_errors
    }


# ---------- cli ----------
def main():
    ap = argparse.ArgumentParser(description="Extractor for .col-lg-12 articles and modal arrays (robust).")
    ap.add_argument("--in", dest="indir", default="iLegis/Batch 8", help="Input folder with .html files")
    ap.add_argument("--out", dest="outdir", default="iLegis/Batch_8_parsate", help="Output folder for JSON files")
    ap.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    ap.add_argument("--log", dest="logfile", default="extract.log", help="Path to the log file (default: extract.log)")
    ap.add_argument("--report", dest="report", default="run_report.json", help="Path to summary JSON report")
    args = ap.parse_args()

    in_dir = Path(args.indir)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logfile = Path(args.logfile)
    report_path = Path(args.report)

    logger = setup_logger(logfile)
    pattern = "**/*.html" if args.recursive else "*.html"
    files = list(in_dir.glob(pattern))
    if not files:
        logger.warning(f"No HTML files found in {in_dir} (recursive={args.recursive})")

    run_summary = {"total_files": len(files), "processed": 0, "files": []}

    for f in files:
        logger.info(f"Processing: {f}")
        result = process_file(f, out_dir, logger)
        run_summary["files"].append(result)
        run_summary["processed"] += 1

    # quick totals
    run_summary["total_articles"] = sum(x["articles"] for x in run_summary["files"])
    run_summary["total_modals"] = sum(x["modals"] for x in run_summary["files"])
    run_summary["total_modal_articles"] = sum(x.get("modal_articles", 0) for x in run_summary["files"])
    run_summary["total_errors"] = sum(len(x["errors"]) for x in run_summary["files"])

    report_path.write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Done. JSON in: {out_dir.resolve()}")
    logger.info(f"Log:  {logfile.resolve()}")
    logger.info(f"Report: {report_path.resolve()}")


if __name__ == "__main__":
    main()
