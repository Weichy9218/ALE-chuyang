#!/usr/bin/env python3
"""Build a deterministic AE/SUPPAE metadata-to-aCRF occurrence index.
Read-only on SOURCE_DIR; writes one TSV to OUTPUT_TSV.
Usage: python3 build_ae_source_index.py SOURCE_DIR OUTPUT_TSV
Requires the Linux `pdftotext` command and Python 3 standard library.
"""
import argparse, csv, re, subprocess, sys
from pathlib import Path
import xml.etree.ElementTree as ET

ODM = "http://www.cdisc.org/ns/odm/v1.3"
DEF = "http://www.cdisc.org/ns/def/v2.0"
XLINK = "http://www.w3.org/1999/xlink"
q = lambda ns, tag: "{%s}%s" % (ns, tag)

def text_of(el):
    if el is None: return ""
    return " ".join(" ".join(el.itertext()).split())

def attr(el, local):
    if el is None: return ""
    return el.get(local, el.get(q(DEF, local), ""))

def load_define(path):
    root = ET.parse(path).getroot()
    by_oid = {e.get("OID"): e for e in root.iter() if e.get("OID")}
    return root, by_oid

def item_metadata(item):
    desc = text_of(item.find("./"+q(ODM,"Description"))) if item is not None else ""
    origin = item.find("./"+q(DEF,"Origin")) if item is not None else None
    codelist = item.find("./"+q(ODM,"CodeListRef")) if item is not None else None
    return {
        "label": desc,
        "datatype": attr(item,"DataType"),
        "length": attr(item,"Length"),
        "codelist_oid": codelist.get("CodeListOID","") if codelist is not None else "",
        "origin_type": origin.get("Type","") if origin is not None else "",
        "origin_detail": text_of(origin),
    }

def acrf_pages(pdf):
    proc = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.decode("utf-8", "replace").split("\f")

def occurrences(pages, token):
    rx = re.compile(r"(?<![A-Z0-9_])" + re.escape(token) + r"(?![A-Z0-9_])")
    found=[]
    for page_no, page in enumerate(pages, 1):
        for line in page.splitlines():
            if rx.search(line.upper()):
                snippet=" ".join(line.split())
                if snippet and (page_no, snippet) not in found:
                    found.append((page_no, snippet))
    return found

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("source_dir", type=Path)
    ap.add_argument("output_tsv", type=Path)
    a=ap.parse_args()
    src=a.source_dir.resolve(); out=a.output_tsv.resolve()
    if src == out or src in out.parents:
        raise SystemExit("Refusing to write inside source_dir")
    define=src/"sdtm_define.xml"; pdf=src/"annotated_crf.pdf"
    for p in (define,pdf):
        if not p.is_file(): raise SystemExit("Missing: "+str(p))
    root, by_oid=load_define(define)
    pages=acrf_pages(pdf)
    rows=[]
    # AE ItemRefs, preserving define.xml order.
    groups=[g for g in root.iter(q(ODM,"ItemGroupDef")) if g.get("SASDatasetName")=="AE"]
    if len(groups)!=1: raise SystemExit(f"Expected one AE ItemGroupDef, found {len(groups)}")
    for ref in groups[0].findall("./"+q(ODM,"ItemRef")):
        item=by_oid.get(ref.get("ItemOID")); target=(item.get("Name","") if item is not None else "")
        m=item_metadata(item); occ=occurrences(pages,target) if target else []
        rows.append({"dataset":"AE","target":target,"define_order":ref.get("OrderNumber",""),
          "role":ref.get("Role",""),"mandatory":ref.get("Mandatory",""),"method_oid":ref.get("MethodOID",""),
          **m,"acrf_pages":";".join(map(str,sorted({x[0] for x in occ}))),
          "acrf_exact_lines":" || ".join(f"p{n}: {s}" for n,s in occ)})
    # SUPPAE QNAMs are the CheckValue values reached from VL.SUPPAE.QVAL.
    vls=[v for v in root.iter(q(DEF,"ValueListDef")) if v.get("OID")=="VL.SUPPAE.QVAL"]
    if len(vls)!=1: raise SystemExit(f"Expected VL.SUPPAE.QVAL once, found {len(vls)}")
    for ref in vls[0].findall("./"+q(ODM,"ItemRef")):
        wref=ref.find("./"+q(DEF,"WhereClauseRef")); w=by_oid.get(wref.get("WhereClauseOID")) if wref is not None else None
        vals=[] if w is None else [text_of(x) for x in w.iter(q(ODM,"CheckValue"))]
        item=by_oid.get(ref.get("ItemOID")); m=item_metadata(item)
        for target in vals:
            occ=occurrences(pages,target)
            rows.append({"dataset":"SUPPAE","target":target,"define_order":ref.get("OrderNumber",""),
              "role":ref.get("Role",""),"mandatory":ref.get("Mandatory",""),"method_oid":ref.get("MethodOID",""),
              **m,"acrf_pages":";".join(map(str,sorted({x[0] for x in occ}))),
              "acrf_exact_lines":" || ".join(f"p{n}: {s}" for n,s in occ)})
    fields=["dataset","target","define_order","role","mandatory","method_oid","label","datatype","length",
            "codelist_oid","origin_type","origin_detail","acrf_pages","acrf_exact_lines"]
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)
    print(f"indexed_rows={len(rows)} ae_rows={sum(r['dataset']=='AE' for r in rows)} suppae_qnams={sum(r['dataset']=='SUPPAE' for r in rows)} output={out}")

if __name__=="__main__": main()
