#!/usr/bin/env python3
"""Index field references in existing-audience definitions against profile/dictionary fields.
Read-only: prints TSV to stdout and does not modify any supplied path.
"""
import argparse, csv, re, sys
import pyarrow.parquet as pq

IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
KEYWORDS = {"and", "or", "not", "in", "is", "null", "true", "false", "like", "between"}

def refs(expr):
    # Quoted content is a literal, not a field reference.
    scrubbed = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", " ", expr)
    return sorted({x for x in IDENT.findall(scrubbed) if x.lower() not in KEYWORDS})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles_parquet")
    ap.add_argument("existing_audiences_csv")
    ap.add_argument("data_dictionary_tsv")
    a = ap.parse_args()
    profile_fields = set(pq.read_schema(a.profiles_parquet).names)
    with open(a.data_dictionary_tsv, newline="", encoding="utf-8") as f:
        dictionary_fields = {r["field_name"] for r in csv.DictReader(f, delimiter="\t")}
    out = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    out.writerow(["existing_audience_id", "existing_audience_name", "referenced_field", "in_profile_schema", "in_data_dictionary"])
    with open(a.existing_audiences_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for field in refs(r["definition"]):
                out.writerow([r["audience_id"], r["name"], field,
                              int(field in profile_fields), int(field in dictionary_fields)])
if __name__ == "__main__":
    main()
