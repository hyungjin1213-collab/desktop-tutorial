"""Research keywords and techniques per professor.

Sources, from the works already fetched for the collaboration graph:
- MeSH descriptors (assigned by PubMed indexers; most precise for bio/med),
  with major topics counting more;
- OpenAlex keywords (scored per paper).

Weighting: the professor's role on the paper (last > first > middle author),
recency (halves every 6 years) and, across professors, TF-IDF so that a
term shared by everyone (Signal Transduction) ranks below one that sets a
lab apart (CAR-T). Demographic / study-design MeSH "check tags" are dropped.
"""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

ROLE_WEIGHT = {"last": 1.0, "first": 0.8, "middle": 0.25}
MAJOR_MESH_BONUS = 1.5
HALF_LIFE_YEARS = 6.0
TOP_KEYWORDS = 12
TOP_TECHNIQUES = 6

# MeSH check tags and study-design terms: true for most papers, say nothing about a lab.
GENERIC_TERMS = {t.casefold() for t in [
    "Humans", "Animals", "Mice", "Rats", "Male", "Female", "Adult", "Middle Aged", "Aged",
    "Aged, 80 and over", "Young Adult", "Adolescent", "Child", "Child, Preschool", "Infant",
    "Infant, Newborn", "Pregnancy", "Republic of Korea", "Korea", "Retrospective Studies",
    "Prospective Studies", "Cohort Studies", "Cross-Sectional Studies", "Case-Control Studies",
    "Follow-Up Studies", "Treatment Outcome", "Risk Factors", "Time Factors", "Incidence",
    "Prevalence", "Prognosis", "Surveys and Questionnaires", "Reproducibility of Results",
    "Sensitivity and Specificity", "Logistic Models", "Multivariate Analysis", "Odds Ratio",
    "Kaplan-Meier Estimate", "Survival Rate", "ROC Curve", "Cells, Cultured", "Cell Line",
    "Cell Line, Tumor", "In Vitro Techniques", "Mice, Inbred C57BL", "Mice, Inbred BALB C",
    "Rats, Sprague-Dawley", "Mice, Nude", "Disease Models, Animal", "Dose-Response Relationship, Drug",
    "Models, Biological", "Medicine", "Biology", "Chemistry",
    "Internal medicine", "Computer science", "Materials science", "Pathology",
]}

# Experimental / computational techniques, reported separately ("주요 기술").
TECHNIQUES = {t.casefold(): t for t in [
    "Flow Cytometry", "CRISPR-Cas Systems", "Gene Editing", "Single-Cell Analysis",
    "Single-Cell Gene Expression Analysis", "Sequence Analysis, RNA", "RNA-Seq",
    "High-Throughput Nucleotide Sequencing", "Whole Genome Sequencing", "Exome Sequencing",
    "Chromatin Immunoprecipitation Sequencing", "Mass Spectrometry", "Tandem Mass Spectrometry",
    "Chromatography, Liquid", "Proteomics", "Metabolomics", "Lipidomics", "Microscopy, Confocal",
    "Microscopy, Electron", "Cryoelectron Microscopy", "Crystallography, X-Ray",
    "Magnetic Resonance Imaging", "Positron-Emission Tomography", "Patch-Clamp Techniques",
    "Optogenetics", "Organoids", "Induced Pluripotent Stem Cells", "Xenograft Model Antitumor Assays",
    "Real-Time Polymerase Chain Reaction", "Immunohistochemistry", "Blotting, Western",
    "Enzyme-Linked Immunosorbent Assay", "Molecular Docking Simulation",
    "Molecular Dynamics Simulation", "Machine Learning", "Deep Learning", "Nanoparticles",
    "Liposomes", "Drug Delivery Systems", "Mice, Transgenic", "Mice, Knockout", "Zebrafish",
    "Drosophila melanogaster", "Caenorhabditis elegans", "Arabidopsis", "Microfluidics",
    "Tissue Engineering", "Bioprinting", "Electrophysiology", "Calcium Signaling",
    "Genome-Wide Association Study", "Computational Biology", "Immunotherapy, Adoptive",
    "Receptors, Chimeric Antigen", "Antibodies, Monoclonal", "Hydrogels", "Tissue Scaffolds",
    "Exosomes", "Extracellular Vesicles", "RNA, Small Interfering", "Mendelian Randomization Analysis",
]}


class KeywordCollector:
    def __init__(self, now_year: int):
        self.now = now_year
        self.weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.display: dict[str, str] = {}

    def add_work(self, professor_id: str, position: str, work: dict) -> None:
        role = ROLE_WEIGHT.get(position, ROLE_WEIGHT["middle"])
        year = int(work.get("publication_year") or 0)
        age = max(self.now - year, 0) if year else 2 * HALF_LIFE_YEARS
        base = role * 0.5 ** (age / HALF_LIFE_YEARS)
        seen: set[str] = set()
        for mesh in work.get("mesh") or []:
            name = str(mesh.get("descriptor_name", "")).strip()
            key = name.casefold()
            if not name or key in GENERIC_TERMS or key in seen:
                continue
            seen.add(key)
            self.display.setdefault(key, name)
            self.weights[professor_id][key] += base * (MAJOR_MESH_BONUS if mesh.get("is_major_topic") else 1.0)
        for kw in work.get("keywords") or []:
            name = str(kw.get("display_name", "")).strip()
            key = name.casefold()
            if not name or key in GENERIC_TERMS or key in seen:
                continue
            seen.add(key)
            self.display.setdefault(key, name)
            self.weights[professor_id][key] += base * float(kw.get("score") or 0.5)

    def top_terms(self) -> dict[str, dict[str, list[tuple[str, float]]]]:
        """{professor_id: {"keywords": [(term, score)], "techniques": [...]}} after TF-IDF."""
        n = max(len(self.weights), 1)
        df: dict[str, int] = defaultdict(int)
        for terms in self.weights.values():
            for key in terms:
                df[key] += 1
        out = {}
        for pid, terms in self.weights.items():
            scored = sorted(((key, w * math.log(1 + n / df[key])) for key, w in terms.items()),
                            key=lambda kv: -kv[1])
            tech = [(TECHNIQUES[k], round(v, 3)) for k, v in scored if k in TECHNIQUES][:TOP_TECHNIQUES]
            kws = [(self.display[k], round(v, 3)) for k, v in scored if k not in TECHNIQUES][:TOP_KEYWORDS]
            out[pid] = {"keywords": kws, "techniques": tech}
        return out

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for pid, groups in self.top_terms().items():
            for kind, items in groups.items():
                for rank, (term, score) in enumerate(items, start=1):
                    rows.append({"professor_id": pid, "kind": kind[:-1], "rank": rank, "term": term, "score": score})
        return pd.DataFrame(rows, columns=["professor_id", "kind", "rank", "term", "score"])
