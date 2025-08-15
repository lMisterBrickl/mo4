from __future__ import annotations
import argparse
import logging
import re
from pathlib import Path
from typing import List, Tuple, Optional
from bs4 import BeautifulSoup

from leg5_src.extractor.model import MetaInfo, Entry

# ---------------- Logging ----------------
LOG_FILE = Path("leg5_extractor_logger.log")
logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("leg5_extractor")

# ---------------- Regex constants ----------------
LEGAL_FORM_RX = re.compile(
    r'\b(S\.?\s*A\.?|S\.?\s*R\.?\s*L\.?|P\.?\s*F\.?\s*A\.?|S\.?\s*N\.?\s*C\.?)\b', re.I
)
END_MARK_RX = re.compile(r'\(\s*\d+\s*/\s*\d{1,3}(?:\.\d{3})+\s*\)')
RE_CUI = re.compile(r'\b(?:CUI|Cod(?:ul)?\s+unic(?:\s+de)?\s+înregistrare)\s*[:\-]?\s*(?:RO\s*)?(\d{6,10})\b', re.I)
RE_REGNO = re.compile(r'\b[JCF]\s*\d{1,2}/\d{1,6}/\d{4}\b', re.I)
RE_EUID = re.compile(r'\b(?:ROONRC\.[A-Z]\d+|[A-Z]{2,}\.?ONRC\.[A-Z]\d{1,2}/\d{3,8}/\d{4})\b', re.I)
RE_CAEN_LISTLINE = re.compile(r'(?m)^\s*(\d{4})\s*-\s+')
RE_CAEN_INLINE = re.compile(r'\b(?:CAEN|grupa\s+CAEN)\D+(\d{4})\b', re.I)
RE_CAPITAL = re.compile(r'\bcapital\s+social\s*:\s*([^;\n]+)', re.I)
STOP_WORDS = r"(?:înregistrată|având|reprezentând|la\s+data\s+de|domiciliat|identificat|deținând|cod\s+unic|CUI|am\s+decis|$)"

RE_SEDIU_COLON = re.compile(
    rf'\b(?:sediul\s+social|sediul)\s*:\s*([^;\n]+?)(?=,?\s*{STOP_WORDS})',
    re.I
)

RE_SEDIU_IN = re.compile(
    rf'\bcu\s+sediul\s+social\s+(?:în|in)\s+([^;\n]+?)(?=,?\s*{STOP_WORDS})',
    re.I
)

RE_ADDRESS_FALLBACK = re.compile(
    rf'\bîn\s+(satul|municipiul|orașul|mun\.?|jud\.?|com\.)\s+([^;\n]+?)(?=,?\s*{STOP_WORDS})',
    re.I
)
RE_BULLETIN_H1 = re.compile(
    r'Partea\s+a\s+IV-a\s+nr\.\s*(\d+)\s+din\s+(\d{2}\.\d{2}\.\d{4})',
    re.I
)

RE_DOC_TYPE = re.compile(r'\b(NOTIFICARE|HOT[ĂA]R[ÂA]RE|DECIZIE|ÎN[ȘS]TIIN[ȚT]ARE)\b', re.I)


# ---------------- Helpers ----------------
def _get_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _clean_text(s: str) -> str:
    s = s.replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()


def _full_text(soup: BeautifulSoup) -> str:
    return _clean_text(soup.get_text("\n"))


def _categorize_legal_form(text: str) -> str:
    t = (text or "").upper()
    if re.search(r'\bS\.?\s*A\.?\b', t): return "SA"
    if re.search(r'\bS\.?\s*R\.?\s*L\.?\b', t): return "SRL"
    if re.search(r'\bP\.?\s*F\.?\s*A\.?\b', t): return "PFA"
    if re.search(r'\bS\.?\s*N\.?\s*C\.?\b', t): return "SNC"
    return "OTHER"


def _bucket(legal_type: str | None) -> str:
    t = (legal_type or "OTHER").upper()
    return t if t in {"SRL", "SA", "PFA", "SNC"} else "OTHER"


def _find_segments_via_strong(html: str) -> List[Tuple[int, int, str]]:
    soup = _get_soup(html)
    full = _full_text(soup)
    segments: List[Tuple[int, int, str]] = []
    strongs = []
    for st in soup.find_all('strong'):
        st_text = _clean_text(st.get_text(" ").strip())
        if st_text and LEGAL_FORM_RX.search(st_text):
            sidx = full.find(st_text)
            if sidx != -1:
                strongs.append((sidx, st_text))
    strongs.sort(key=lambda x: x[0])
    for sidx, st_text in strongs:
        m = END_MARK_RX.search(full, pos=sidx)
        if m:
            segments.append((sidx, m.end(), st_text))
    return segments


def _extract_bulletin_meta(soup: BeautifulSoup):
    h1 = soup.find('h1')
    if not h1:
        return None, None, None
    text = _clean_text(h1.get_text(" "))
    m = RE_BULLETIN_H1.search(text)
    if not m:
        return None, None, None
    num = m.group(1)
    full_date = m.group(2)
    year = full_date[-4:]
    return num, full_date, year


def _extract_entry(chunk: str, name_hint: Optional[str], bulletin_info: tuple) -> Entry:
    cui = (RE_CUI.search(chunk).group(1) if RE_CUI.search(chunk) else None)
    regno = (RE_REGNO.search(chunk).group(0) if RE_REGNO.search(chunk) else None)
    euid = (RE_EUID.search(chunk).group(0) if RE_EUID.search(chunk) else None)

    caen_codes: list[str] = []
    for m in RE_CAEN_LISTLINE.finditer(chunk):
        caen_codes.append(m.group(1))
    for m in RE_CAEN_INLINE.finditer(chunk):
        caen_codes.append(m.group(1))
    caen_codes = list(dict.fromkeys(caen_codes))

    capital = None
    if m_cap := RE_CAPITAL.search(chunk):
        capital = m_cap.group(1).strip().rstrip(';.')

    address = None
    if m := RE_SEDIU_COLON.search(chunk):
        address = m.group(1).strip(' ,;.')
    elif m := RE_SEDIU_IN.search(chunk):
        address = m.group(1).strip(' ,;.')
    elif m := RE_ADDRESS_FALLBACK.search(chunk):
        address = m.group(0).strip(' ,;.')

    doc_type = None
    if m := RE_DOC_TYPE.search(chunk):
        doc_type = m.group(1).title()

    company_name = name_hint
    if not company_name:
        for line in chunk.splitlines():
            if LEGAL_FORM_RX.search(line):
                company_name = line.strip()
                break

    legal_type = _categorize_legal_form(company_name or chunk)

    meta = MetaInfo(
        cui=cui,
        legal_type=legal_type if legal_type in {"SRL", "SA", "PFA", "SNC"} else None,
        reg_number=regno,
        euid=euid,
        caen=caen_codes,
        capital=capital,
        address=address
    )

    return Entry(
        number=bulletin_info[0],
        date=bulletin_info[1],
        year=bulletin_info[2],
        company_name=company_name,
        meta=meta,
        raw_text=chunk,
        type=doc_type
    )


# ---------------- Main parser ----------------
def parse_file(path: Path):
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = _get_soup(html)
    bulletin_info = _extract_bulletin_meta(soup)

    full = _full_text(soup)
    segs = _find_segments_via_strong(html)
    out = []
    for sidx, eidx, st_text in segs:
        chunk = _clean_text(full[sidx:eidx])
        if len(chunk) < 80:
            continue
        out.append(_extract_entry(chunk, st_text, bulletin_info))
    return out


def main():
    ap = argparse.ArgumentParser(description="Lege5 structured extractor (no entry_number/year)")
    ap.add_argument("--indir", default="../leg5/Batch_8", help="Input folder")
    ap.add_argument("--outdir", default="../leg5/extracted", help="Output folder")
    ap.add_argument("--recursive", action="store_true")
    args = ap.parse_args()

    in_dir = Path(args.indir)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*.html" if args.recursive else "*.html"
    files = sorted(in_dir.glob(pattern))

    total = 0
    for html_file in files:
        try:
            entries = parse_file(html_file)
            logger.info(f"{html_file}: {len(entries)} segment(s)")
            for idx, entry in enumerate(entries, start=1):
                bucket = _bucket(entry.meta.legal_type)
                outp = out_dir / bucket
                outp.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r'[^A-Za-z0-9\-_\.\s]', '', (entry.company_name or "entry")).strip().replace(' ', '_')
                fname = f"{safe}__{idx:03d}.json"
                with (outp / fname).open("w", encoding="utf-8") as f:
                    f.write(entry.model_dump_json(indent=2))
                total += 1
        except Exception as e:
            logger.exception(f"Error on {html_file}: {e}")

    print(f"Done. Wrote {total} JSON files to {out_dir}")
    print(f"Logs: {LOG_FILE}")


if __name__ == "__main__":
    main()
