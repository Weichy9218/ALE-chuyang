#!/usr/bin/env python3
"""Build the clinical-variant annotation tables from the staged VEP snapshot."""

import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "input"
OUTPUT = BASE / "output"

# Ensembl consequence terms, most to least severe (Ensembl release 113).
CONSEQUENCE_ORDER = """transcript_ablation
splice_acceptor_variant
splice_donor_variant
stop_gained
frameshift_variant
stop_lost
start_lost
transcript_amplification
feature_elongation
feature_truncation
inframe_insertion
inframe_deletion
missense_variant
protein_altering_variant
splice_donor_5th_base_variant
splice_region_variant
splice_donor_region_variant
splice_polypyrimidine_tract_variant
incomplete_terminal_codon_variant
start_retained_variant
stop_retained_variant
synonymous_variant
coding_sequence_variant
mature_miRNA_variant
5_prime_UTR_variant
3_prime_UTR_variant
non_coding_transcript_exon_variant
intron_variant
NMD_transcript_variant
non_coding_transcript_variant
upstream_gene_variant
downstream_gene_variant
TFBS_ablation
TFBS_amplification
TF_binding_site_variant
regulatory_region_ablation
regulatory_region_amplification
regulatory_region_variant
intergenic_variant
sequence_variant""".splitlines()
RANK = {term: rank for rank, term in enumerate(CONSEQUENCE_ORDER)}
CLINVAR_ORDER = [
    "pathogenic", "likely_pathogenic", "uncertain_significance",
    "conflicting_classifications_of_pathogenicity", "drug_response",
    "risk_factor", "association", "likely_benign", "benign",
]
REPORTABLE_CONSEQUENCES = {
    "frameshift_variant", "splice_acceptor_variant", "splice_donor_variant",
    "start_lost", "stop_gained", "stop_lost",
}
HEADER = [
    "variant_id", "chrom", "pos", "ref", "alt", "gene", "consequence",
    "max_population_af", "clinvar_significance", "is_reportable",
]


def normalized_alt(response):
    """Return VEP's representation of the submitted alternate allele."""
    # The response is for one staged biallelic variant. VEP trims shared sequence,
    # so an indel can be represented as '-' or just its inserted sequence.
    return response["allele_string"].split("/")[-1]


def select_transcript(response, allele):
    candidates = []
    for ordinal, transcript in enumerate(response.get("transcript_consequences", [])):
        if transcript.get("biotype") != "protein_coding":
            continue
        if transcript.get("variant_allele") != allele:
            continue
        for term_ordinal, term in enumerate(transcript.get("consequence_terms", [])):
            candidates.append((
                RANK.get(term, len(RANK)),
                -int(bool(transcript.get("canonical"))),
                ordinal,
                term_ordinal,
                transcript,
                term,
            ))
    if not candidates:
        raise ValueError("No allele-specific protein-coding transcript consequence")
    chosen = min(candidates)
    transcript, term = chosen[-2], chosen[-1]
    return transcript.get("gene_symbol") or transcript.get("gene_id") or "NA", term


def matching_colocated(response, allele):
    """Yield colocated records that represent the normalized submitted allele."""
    for colocated in response.get("colocated_variants", []):
        frequencies = colocated.get("frequencies") or {}
        alleles = (colocated.get("allele_string") or "").split("/")
        if allele in frequencies or allele in alleles:
            yield colocated


def population_af(response, allele):
    values = []
    for colocated in matching_colocated(response, allele):
        sources = (colocated.get("frequencies") or {}).get(allele, {})
        for value in sources.values():
            # bool is technically numeric in Python, but not a valid frequency.
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
    return max(values) if values else None


def clinvar(response, allele):
    labels = set()
    for colocated in matching_colocated(response, allele):
        labels.update(colocated.get("clin_sig") or [])
    return next((label for label in CLINVAR_ORDER if label in labels), "not_reported")


def format_af(value):
    return "NA" if value is None else format(value, ".15g")


def main():
    with (INPUT / "source_manifest.json").open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    with (INPUT / "variants_to_annotate.tsv").open(encoding="utf-8", newline="") as handle:
        variants = list(csv.DictReader(handle, delimiter="\t"))

    snapshots = {}
    with (INPUT / "annotation_snapshots" / "vep_batch_responses.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            snapshots[item["variant_id"]] = item["vep_response"]

    rows = []
    for variant in variants:
        response = snapshots[variant["variant_id"]]
        allele = normalized_alt(response)
        gene, consequence = select_transcript(response, allele)
        af = population_af(response, allele)
        significance = clinvar(response, allele)
        rare = af is None or af < 0.01
        # The manifest's expression is read with normal boolean precedence:
        # consequence criterion OR (ClinVar criterion AND frequency criterion).
        reportable = (consequence in REPORTABLE_CONSEQUENCES) or (
            significance in {"pathogenic", "likely_pathogenic"} and rare
        )
        rows.append({
            **variant,
            "gene": gene,
            "consequence": consequence,
            "max_population_af": format_af(af),
            "clinvar_significance": significance,
            "is_reportable": "yes" if reportable else "no",
        })

    reportable_rows = [row for row in rows if row["is_reportable"] == "yes"]
    expected = manifest.get("counts", {})
    if len(rows) != expected.get("annotated_variants", len(rows)):
        raise ValueError("Annotated count differs from source manifest")
    if len(reportable_rows) != expected.get("reportable_variants", len(reportable_rows)):
        raise ValueError("Reportable count differs from source manifest")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("annotated_variants.tsv", rows), ("reportable_variants.tsv", reportable_rows)):
        with (OUTPUT / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADER, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row[key] for key in HEADER} for row in data)

    log = {
        "status": "completed",
        "annotated_variants_written": len(rows),
        "reportable_variants_written": len(reportable_rows),
    }
    with (OUTPUT / "run_log.json").open("w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
