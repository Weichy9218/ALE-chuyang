#!/usr/bin/env python3
"""Deterministic concordance over staged extracted_text, resolved through document_manifest.json.
Read-only: emits TSV to stdout. Python 3 stdlib only.
"""
import argparse, csv, hashlib, json, re, sys
from pathlib import Path

NUMERAL_RE = re.compile(r"[0-9０-９一二三四五六七八九十百千万亿两零〇]+(?:[.,，．][0-9０-９]+)?\s*(?:元|分|角|%|％|笔|次|万|亿)?")
WS_RE = re.compile(r"\s+")

def norm_path(s):
    return str(s).replace("\\", "/").lstrip("./")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", help="task input directory containing document_manifest.json and extracted_text/")
    ap.add_argument("terms", nargs="+", help="literal UTF-8 search terms (OR semantics)")
    ap.add_argument("--context", type=int, default=120, help="characters on each side (default 120)")
    args = ap.parse_args()
    if args.context < 0 or args.context > 2000:
        ap.error("--context must be between 0 and 2000")
    root = Path(args.input_dir)
    manifest_path = root / "document_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_extract = {norm_path(x["staged_extract_path"]): x for x in manifest}
    files = sorted((root / "extracted_text").glob("*.txt"), key=lambda p: p.name)
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["term","doc_id","extract_path","original_filename","citation_aliases_json","line","char_start","context","numerals_in_context","extract_sha256"])
    for p in files:
        rel = norm_path(p.relative_to(root))
        meta = by_extract.get(rel)
        if meta is None:
            raise SystemExit(f"unresolved extract (not in manifest): {rel}")
        raw = p.read_bytes()
        text = raw.decode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        for term in args.terms:
            start = 0
            while True:
                pos = text.find(term, start)
                if pos < 0: break
                lo, hi = max(0, pos-args.context), min(len(text), pos+len(term)+args.context)
                context = WS_RE.sub(" ", text[lo:hi]).strip()
                nums = NUMERAL_RE.findall(context)
                w.writerow([term, meta.get("doc_id",""), rel, meta.get("original_filename",""),
                            json.dumps(meta.get("citation_aliases",[]), ensure_ascii=False, separators=(",",":")),
                            text.count("\n", 0, pos)+1, pos, context,
                            json.dumps(nums, ensure_ascii=False, separators=(",",":")), digest])
                start = pos + max(1, len(term))

if __name__ == "__main__":
    main()
