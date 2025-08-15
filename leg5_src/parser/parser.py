# source2_structured_extractor.py (refined, rebuilt)
# -*- coding: utf-8 -*-
from __future__ import annotations
import re, uuid
from typing import Dict, Any, List, Optional

INCLUDE_SENSITIVE_IDS = False

RE_CUI = re.compile(r'\b(?:CUI|Cod(?:ul)?\s+unic(?:\s+de)?\s+înregistrare)\s*[:\-]?\s*(?:RO\s*)?(\d{3,10})\b', re.I)
RE_EUID = re.compile(r'\bEUID\s*[:\-]?\s*([A-Z]{2,}\.ONRC\.[A-Z]\d{1,2}/\d{3,8}/\d{4}|ROONRC\.[A-Z]\d{6,})\b', re.I)
RE_REG = re.compile(r'\b([JFC]\s*\d{1,2}/\d{1,6}/\d{4})\b', re.I)
RE_CAEN = re.compile(r'\b(\d{4})\s*-\s*([A-ZĂÂÎȘȚa-zăâîșț ,\-/]+)')
RE_CAEN_GROUP = re.compile(r'\bgrupa\s*CAEN\s*[:\-]?\s*(\d{3})\b', re.I)
RE_CAPITAL = re.compile(r'\bcapital\s+social\s*[:\-]?\s*([0-9\.\s]+)\s*lei\b', re.I)

RE_ADDRESS = re.compile(
    r'\bsediul\s+social\s*[:\-]?\s*(.+?)(?:(?:[;,\.])\s*(?:identificator unic|\bEUID\b|număr de ordine|\bJ\d|\bF\d|\bCUI\b|domeniul principal|activitate principală|capital social|fondator|administrator|durata de func|înregistrat[ăa] la O\.?R\.?C|înmatriculat[ăa])\b|$)',
    re.I | re.S
)
RE_COUNTY = re.compile(r'\bjud\.\s*([A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț \-]+)', re.I)
RE_CITY = re.compile(r'\b(?:municipiul|ora[șs]ul|mun\.)\s*([A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț \-]+)', re.I)
RE_NAME_LINE = re.compile(r'^\s*-\s*denumire\s+și\s+form[ăa]\s+juridic[ăa]\s*[:\-]?\s*(.+?)\s*;?\s*$', re.I | re.M)
RE_NAME_STRONG = re.compile(r'^\s*([A-Z0-9 \-\.„”"\'&]+(?:S\.?R\.?L\.?|S\.?A\.?|P\.?F\.?A\.?))\s*$', re.M)

RE_ADMIN_BLOCK = re.compile(r'\badministrator[i]?\s*[:\-]\s*(?:\d+\.\s*)?(.+?)(?:;|\.?\s*$|\n-|\n\d+\.)', re.I | re.S)
RE_FOUNDER_BLOCK = re.compile(r'\bfondator[i]?\s*[:\-]\s*(?:\d+\.\s*)?(.+?)(?:;|\.?\s*$|\n-|\n\d+\.)', re.I | re.S)
RE_SPLIT_NAMES = re.compile(r'\s*,\s*|\s*;\s*|\s+\bși\b\s+|\s+si\s+', re.I)
RE_PERSON_LIKE = re.compile(
    r'^\s*(?:\d+\.\s*)?([A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț\'\-]+(?:\s+[A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț\'\-]+)+)\s*$')

DROP_TOKENS = {
    "puteri conferite: depline", "exercitate separat", "exercitate împreună", "exercitate impreuna",
    "cu domiciliul în", "domiciliul în", "domiciliat în", "sectorul", "strada", "str.", "scara", "etaj", "ap."
}

RE_DATE_OF_CREATION = re.compile(r'înmatriculat[ăa]\s*(?:la|în)\s*data\s+de\s+(\d{2}\.\d{2}\.\d{4})', re.I)
RE_EXTRAS_NO_DATE = re.compile(r'EXTRAS\s+AL\s+ÎNCHEIERII\s+NR\.\s*([0-9]+)\/(\d{2}\.\d{2}\.\d{4})', re.I)


def _clean(s: str) -> str:
    s = s.replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()


def _parse_addresses(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    m = RE_ADDRESS.search(text)
    if m:
        full = m.group(1).strip().rstrip('.').rstrip(',')
        county = None
        city = None
        mc = RE_COUNTY.search(full)
        if mc: county = mc.group(1).strip()
        mcity = RE_CITY.search(full)
        if mcity: city = mcity.group(1).strip()
        out.append({
            "fullAddress": full,
            "country": "Romania",
            "county": county,
            "city": city
        })
    return out


def _find_company_name(text: str) -> Optional[str]:
    m = RE_NAME_LINE.search(text)
    if m:
        return m.group(1).strip()
    m2 = RE_NAME_STRONG.search(text)
    if m2:
        return m2.group(1).strip()
    for line in text.splitlines():
        L = line.strip()
        if re.search(r'\b(S\.?\s*R\.?\s*L\.?|S\.?\s*A\.?|P\.?\s*F\.?\s*A\.?)\b', L):
            return L
    return None


def _legal_form_from_name(name: Optional[str]) -> Optional[str]:
    if not name: return None
    t = name.upper()
    if 'S.A' in t or ' S. A' in t: return 'SA'
    if 'S.R.L' in t or ' S. R. L' in t: return 'SRL'
    if 'P.F.A' in t or ' P F A' in t: return 'PFA'
    return None


def _split_people(raw: str) -> List[str]:
    parts = RE_SPLIT_NAMES.split(raw)
    cleaned = []
    for p in parts:
        p = p.strip().strip(';.,')
        if not p:
            continue
        low = p.lower()
        if any(tok in low for tok in DROP_TOKENS):
            continue
        m = RE_PERSON_LIKE.match(p)
        if m:
            name = m.group(1)
            name = re.sub(r'^\d+\.\s*', '', name).strip()
            cleaned.append(name)
    seen = set();
    out = []
    for n in cleaned:
        key = n.lower()
        if key in seen: continue
        seen.add(key);
        out.append(n)
    return out


def _extract_people_block(text: str, kind: str) -> List[Dict[str, Any]]:
    rx = RE_ADMIN_BLOCK if kind == "admin" else RE_FOUNDER_BLOCK
    m = rx.search(text)
    if not m:
        return []
    raw = m.group(1)
    names = _split_people(raw)
    return [{"name": nm} for nm in names]


def _norm_date(d: str) -> Optional[str]:
    if not d: return None
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', d)
    if not m: return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def extract_structured_company(raw_text: str, data_source: Optional[str] = None) -> Dict[str, Any]:
    text = _clean(raw_text)
    name = _find_company_name(text)

    cui = (RE_CUI.search(text).group(1) if RE_CUI.search(text) else None)
    euid = (RE_EUID.search(text).group(1) if RE_EUID.search(text) else None)
    regno = (RE_REG.search(text).group(1) if RE_REG.search(text) else None)

    caen_code = None
    caen_desc = None
    ma = RE_CAEN.search(text)
    if ma:
        caen_code, caen_desc = ma.group(1), ma.group(2).strip()
    else:
        mg = RE_CAEN_GROUP.search(text)
        if mg: caen_code = mg.group(1)

    capital = (RE_CAPITAL.search(text).group(1).replace(' ', '') + " lei capital social"
               if RE_CAPITAL.search(text) else None)
    addresses = _parse_addresses(text)

    admins = _extract_people_block(text, "admin")
    founders = _extract_people_block(text, "founder")

    created = None
    mdate = RE_DATE_OF_CREATION.search(text)
    if mdate:
        created = _norm_date(mdate.group(1))
    else:
        mex = RE_EXTRAS_NO_DATE.search(text)
        if mex: created = _norm_date(mex.group(2))

    legal_form = _legal_form_from_name(name) or None

    data = {
        "id": str(uuid.uuid4()),
        "type": "company",
        "name": name,
        "mainInfo": {
            "addresses": addresses,
            "caen": caen_code,
            "cui": (f"RO{cui}" if cui and not str(cui).startswith("RO") else cui) if cui else None,
            "dateOfCreation": created,
            "euid": euid,
            "capital": capital,
            "ownership": [
                {
                    "administrators": admins,
                    "associates": founders
                }
            ],
            "activityFieldDescription": caen_desc,
            "fieldOfActivity": None,
            "country": "Romania",
            "dataSource": [data_source] if data_source else ["Official Gazette"],
            "otherName": None,
            "registrationNumber": regno
        },
        "legalForm": legal_form
    }
    if INCLUDE_SENSITIVE_IDS:
        data["mainInfo"]["ownership"][0]["administrators"] = admins
        data["mainInfo"]["ownership"][0]["associates"] = founders

    return data
