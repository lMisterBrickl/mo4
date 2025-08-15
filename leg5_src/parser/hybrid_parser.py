# leg_hybrid_parser.py (modular)
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, sys, logging, re
from pathlib import Path
from typing import Dict, Any, Optional

from parser import extract_structured_company
from llm_agent import run_llm

# Logger
log_file_path = Path("../leg5_parser_logger.log")
logging.basicConfig(
    filename=log_file_path,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("leg_hybrid_parser")


def _safe_slug(name: str, max_len: int = 64) -> str:
    base = re.sub(r'[^A-Za-z0-9\\-_.\\s]', '', name or "entry").strip().replace(' ', '_')
    return (base[:max_len] or 'entry').strip('_')


def _iter_segments(indir: Path, recursive: bool):
    base = indir / "SRL"
    if not base.exists():
        return
    pattern = "**/*.json" if recursive else "*.json"
    for jp in sorted(base.glob(pattern)):
        try:
            seg = json.loads(jp.read_text(encoding="utf-8"))
            yield jp, seg
        except Exception as e:
            logger.exception(f"Failed reading {jp}: {e}")


def _merge_segment_meta(seg: Dict[str, Any], obj: Dict[str, Any]) -> Dict[str, Any]:
    meta = seg.get("meta") or {}
    mi = obj.setdefault("mainInfo", {})
    if meta.get("cui") and not mi.get("cui"):
        mcui = str(meta["cui"])
        mi["cui"] = f"RO{mcui}" if not mcui.startswith("RO") else mcui
    if meta.get("reg_number") and not mi.get("registrationNumber"):
        mi["registrationNumber"] = meta["reg_number"]
    obj["legalForm"] = "SRL"
    return obj


def main():
    ap = argparse.ArgumentParser(description="Hybrid parser (SRL-only) using modular schema & LLM agent")
    ap.add_argument("--indir", default="../leg5/extractor", help="Input base (expects SRL subfolder)")
    ap.add_argument("--outdir", default="../leg5/parsed", help="Output base (SRL subfolder will be used)")
    ap.add_argument("--ndjson", default="companies.ndjson", help="Aggregated NDJSON filename")
    ap.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    ap.add_argument("--model", default=None, help="LLM model name (overrides PYA_MODEL)")
    ap.add_argument("--force-llm", default=False, action="store_true", help="Always call LLM (expensive)")
    args = ap.parse_args()

    in_dir = Path(args.indir)
    out_dir = Path(args.outdir)
    out_srl = out_dir / "SRL"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_srl.mkdir(parents=True, exist_ok=True)

    if not in_dir.is_dir():
        logger.error(f"indir must be a directory, got {in_dir}")
        print(f"ERROR: indir must be a directory, got {in_dir}", file=sys.stderr)
        sys.exit(1)

    n_in = n_ok = n_llm = n_llm_used = 0
    nd_path = out_dir / args.ndjson
    with nd_path.open("w", encoding="utf-8") as nd:
        for jp, seg in _iter_segments(in_dir, args.recursive) or []:
            n_in += 1
            raw = seg.get("raw_text") or ""

            # 1) fast heuristic
            comp = extract_structured_company(raw, data_source="Official Gazette - MoF IV")
            comp = _merge_segment_meta(seg, comp)
            if args.force_llm:
                need = True

            # 2) LLM fallback
            if need:
                n_llm += 1
                llm_comp = run_llm(raw, model_name=args.model)
                if llm_comp:
                    llm_comp = _merge_segment_meta(seg, llm_comp)
                    comp = llm_comp
                    n_llm_used += 1

            # 3) write
            name = comp.get("name") or seg.get("company_name") or "entry"
            safe = _safe_slug(name)
            entry_no = seg.get("entry_number") or "nr"
            entry_year = seg.get("entry_year") or "yyyy"
            fname = f"{safe}__{entry_no}-{entry_year}.json"

            with (out_srl / fname).open("w", encoding="utf-8") as f:
                json.dump(comp, f, ensure_ascii=False, indent=2)
            nd.write(json.dumps(comp, ensure_ascii=False) + "\\n")
            n_ok += 1

    summary = (
        f"HYBRID(modular) DONE. read={n_in}, written={n_ok} | requested LLM on {n_llm} "
        f"({(n_llm / n_in * 100 if n_in else 0):.1f}%), used LLM results {n_llm_used} "
        f"({(n_llm_used / max(n_llm, 1) * 100):.1f}%). outdir={out_dir} ndjson={nd_path}"
    )
    logger.info(summary)
    print(summary)
    print(f"Logs: {log_file_path}")


if __name__ == "__main__":
    main()
