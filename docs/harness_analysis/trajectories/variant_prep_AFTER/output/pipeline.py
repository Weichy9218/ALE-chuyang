#!/usr/bin/env python3
"""Annotate the staged variants from the pinned Ensembl VEP JSONL snapshot.

The pipeline is deliberately offline and deterministic.  Input TSV order is
preserved in both output tables.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "input"
OUTPUT = BASE / "output"
VARIANTS = INPUT / "variants_to_annotate.tsv"
SNAPSHOTS = INPUT / "annotation_snapshots" / "vep_batch_responses.jsonl"
MANIFEST = INPUT / "source_manifest.json"

COLUMNS = [
    "variant_id", "chrom", "pos", "ref", "alt", "gene", "consequence",
    "max_population_af", "clinvar_significance", "is_reportable",
]

# Ensembl's published consequence order, most to least severe.  The expanded
# list makes the selection routine valid beyond just the terms in this batch.
CONSEQUENCE_ORDER = [
    "transcript_ablation", "splice_acceptor_variant", "splice_donor_variant",
    "stop_gained", "frameshift_variant", "stop_lost", "start_lost",
    "transcript_amplification", "feature_elongation", "feature_truncation",
    "inframe_insertion", "inframe_deletion", "missense_variant",
    "protein_altering_variant", "splice_donor_5th_base_variant",
    "splice_region_variant", "splice_donor_region_variant",
    "splice_polypyrimidine_tract_variant", "incomplete_terminal_codon_variant",
    "start_retained_variant", "stop_retained_variant", "synonymous_variant",
    "coding_sequence_variant", "mature_miRNA_variant", "5_prime_UTR_variant",
    "3_prime_UTR_variant", "non_coding_transcript_exon_variant",
    "intron_variant", "NMD_transcript_variant", "non_coding_transcript_variant",
    "upstream_gene_variant", "downstream_gene_variant", "TFBS_ablation",
    "TFBS_amplification", "TF_binding_site_variant", "regulatory_region_ablation",
    "regulatory_region_amplification", "regulatory_region_variant",
    "intergenic_variant",
]
SEVERITY = {term: rank for rank, term in enumerate(CONSEQUENCE_ORDER)}

CLINVAR_ORDER = [
    "pathogenic", "likely_pathogenic", "uncertain_significance",
    "conflicting_classifications_of_pathogenicity", "drug_response",
    "risk_factor", "association", "likely_benign", "benign",
]
CLINVAR_RANK = {label: rank for rank, label in enumerate(CLINVAR_ORDER)}
REPORTABLE_CONSEQUENCES = {
    "frameshift_variant", "splice_acceptor_variant", "splice_donor_variant",
    "start_lost", "stop_gained", "stop_lost",
}
REPORTABLE_CLINVAR = {"pathogenic", "likely_pathogenic"}


def normalized_vep_alt(response: dict[str, Any]) -> str:
    """Return VEP's normalized alternate representation for transcript matching."""
    allele_string = response.get("allele_string", "")
    return allele_string.split("/", 1)[1] if "/" in allele_string else ""


def choose_gene_and_consequence(response: dict[str, Any]) -> tuple[str, str]:
    """Choose most severe protein-coding consequence, then prefer canonical."""
    vep_alt = normalized_vep_alt(response)
    candidates: list[tuple[int, int, int, dict[str, Any], str]] = []
    for transcript_index, tc in enumerate(response.get("transcript_consequences", [])):
        if tc.get("biotype") != "protein_coding":
            continue
        if vep_alt and tc.get("variant_allele") != vep_alt:
            continue
        for term in tc.get("consequence_terms", []):
            rank = SEVERITY.get(term, len(SEVERITY))
            canonical_rank = 0 if tc.get("canonical") == 1 else 1
            candidates.append((rank, canonical_rank, transcript_index, tc, term))
    if not candidates:
        return "NA", "NA"
    _, _, _, transcript, consequence = min(candidates, key=lambda item: item[:3])
    gene = transcript.get("gene_symbol") or transcript.get("gene_id") or "NA"
    return str(gene), consequence


def max_population_af(response: dict[str, Any], submitted_alt: str) -> float | None:
    """Maximum numeric frequency for the submitted (not VEP-normalized) ALT."""
    values: list[float] = []
    for colocated in response.get("colocated_variants", []):
        sources = colocated.get("frequencies", {}).get(submitted_alt, {})
        if not isinstance(sources, dict):
            continue
        for value in sources.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
    return max(values) if values else None


def _allele_specific_clinvar(colocated: dict[str, Any], submitted_alt: str) -> list[str]:
    """Return ClinVar labels associated with submitted_alt in one colocated site."""
    site_labels = [str(x).lower() for x in colocated.get("clin_sig", [])]
    mapping = colocated.get("clin_sig_allele")
    if not mapping:
        # Without a mapping, retain site labels only when the submitted allele is
        # explicitly represented at this colocated record.
        alleles = str(colocated.get("allele_string", "")).split("/")
        return site_labels if submitted_alt in alleles else []

    labels: list[str] = []
    # VEP encodes entries as ALT:label, separated by semicolons.  A label can
    # contain commas in other snapshots, so normalize comma-separated values too.
    for entry in str(mapping).split(";"):
        if ":" not in entry:
            continue
        allele, encoded = entry.split(":", 1)
        if allele == submitted_alt:
            for label in encoded.replace("&", ",").split(","):
                label = label.strip().lower()
                if label:
                    labels.append(label)
    # Intersect with clin_sig when available: the manifest names clin_sig as the
    # source, while clin_sig_allele supplies the required allele association.
    return [label for label in labels if not site_labels or label in site_labels]


def clinvar_significance(response: dict[str, Any], submitted_alt: str) -> str:
    labels: list[str] = []
    for colocated in response.get("colocated_variants", []):
        labels.extend(_allele_specific_clinvar(colocated, submitted_alt))
    known = [label for label in labels if label in CLINVAR_RANK]
    return min(known, key=CLINVAR_RANK.get) if known else "not_reported"


def annotate(variant: dict[str, str], response: dict[str, Any]) -> dict[str, Any]:
    gene, consequence = choose_gene_and_consequence(response)
    af = max_population_af(response, variant["alt"])
    clinvar = clinvar_significance(response, variant["alt"])
    qualifying_annotation = (
        consequence in REPORTABLE_CONSEQUENCES or clinvar in REPORTABLE_CLINVAR
    )
    reportable = qualifying_annotation and (af is None or af < 0.01)
    return {
        **variant,
        "gene": gene,
        "consequence": consequence,
        "max_population_af": "NA" if af is None else format(af, ".15g"),
        "clinvar_significance": clinvar,
        "is_reportable": "yes" if reportable else "no",
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: row[column] for column in COLUMNS} for row in rows)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Read the manifest as provenance and validate the staged contract counts.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with VARIANTS.open(encoding="utf-8", newline="") as handle:
        variants = list(csv.DictReader(handle, delimiter="\t"))
    snapshots: dict[str, dict[str, Any]] = {}
    with SNAPSHOTS.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            snapshots[record["variant_id"]] = record["vep_response"]

    missing = [v["variant_id"] for v in variants if v["variant_id"] not in snapshots]
    if missing:
        raise ValueError(f"Missing VEP snapshots for: {', '.join(missing)}")
    expected = manifest.get("counts", {}).get("annotated_variants")
    if expected is not None and len(variants) != expected:
        raise ValueError(f"Expected {expected} variants, found {len(variants)}")

    rows = [annotate(variant, snapshots[variant["variant_id"]]) for variant in variants]
    reportable = [row for row in rows if row["is_reportable"] == "yes"]
    write_tsv(OUTPUT / "annotated_variants.tsv", rows)
    write_tsv(OUTPUT / "reportable_variants.tsv", reportable)
    log = {
        "status": "success",
        "annotated_variants_written": len(rows),
        "reportable_variants_written": len(reportable),
    }
    (OUTPUT / "run_log.json").write_text(
        json.dumps(log, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
