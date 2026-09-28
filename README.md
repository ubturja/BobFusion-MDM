# 🏦 Golden Customer Record Engine

> **Master Data Management powered by AI-assisted engineering — resolving fragmented customer identities across siloed banking systems into a single, authoritative source of truth.**

---

## The Problem

Large financial institutions operate multiple product lines — Core Banking, Credit Cards, Mortgages — each backed by a separate legacy system with its own data model, key scheme, and formatting conventions. The same customer exists across all three, but with subtle differences: a nickname here, a missing SSN there, a phone number formatted differently. The result is thousands of duplicate records, bloated risk exposure calculations, failed KYC checks, and regulatory blind spots.

## The Solution

The **Golden Customer Record Engine** is an enterprise-grade ETL pipeline that ingests customer extracts from three siloed banking systems, normalises and deduplicates them using a two-pass resolution strategy — deterministic SSN matching followed by fuzzy-logic fallback — and outputs a canonical **Golden Record** per unique real-world customer. The accompanying Streamlit dashboard surfaces the results, visualisations, and a full compliance-grade audit trail explaining every merge decision.

---

## Architecture Overview

```mermaid
graph TD
    subgraph Data Sources
        A[Core Banking CSV]
        B[Credit Card CSV]
        C[Mortgage CSV]
    end

    subgraph ETL Pipeline — etl_engine.py
        D[Stage 1: Extract<br/>Pandas DataFrames]
        E[Stage 2: Normalise<br/>RegEx · Title Case · Digit Strip]
        F[Stage 3a: Exact Resolution<br/>Deterministic SSN Match]
        G[Stage 3b: Fuzzy Resolution<br/>thefuzz token_set_ratio · Union-Find]
        H[Stage 3c: Aggregate<br/>Coalesce · UUID · Total Exposure]
    end

    subgraph Output
        I[(Golden Records CSV)]
        J[Streamlit Dashboard — app.py]
    end

    A -->|Read| D
    B -->|Read| D
    C -->|Read| D
    D --> E
    E --> F
    F -->|SSN match found| H
    F -->|No SSN| G
    G -->|Score > 85 + contact match| H
    G -->|Score > 90 name-only stitch| H
    G -->|No match| H
    H -->|Export| I
    I --> J
```

### Resolution Logic

| Pass | Strategy | Threshold |
|------|-----------|-----------|
| 1 — Exact | Normalised SSN equality | Deterministic |
| 2A — Fuzzy Stitch (Tier 1) | Name similarity **+ contact overlap** | `token_set_ratio > 85` |
| 2A — Fuzzy Stitch (Tier 2) | Name similarity only (cross-system, no shared contact field) | `token_set_ratio ≥ 90` |
| 2B — Fuzzy Peer Match | Unresolved rows matched against each other | `token_set_ratio > 85` + contact |
| 3 — Singleton | Every remaining unmatched row becomes its own Golden Record | — |

**TC-3 Guard:** Records sharing only a last name (e.g., family members) are never merged without corroborating contact-field evidence, preventing false-positive identity conflation.

---

## How IBM Bob Was Utilized

This project was built end-to-end using **IBM Bob** as the primary AI engineering partner throughout every phase of the Bob-a-thon hackathon.

### 1. Architecture & Schema Design
Bob was used to design the system architecture and data schemas from the ground up. Given a plain-English description of the problem (three siloed banking CSVs with inconsistent identifiers), Bob generated the full **System Architecture diagram** (`System_Architecture.md`), the **Entity Relationship Diagram** (`ERD.md`) mapping source schemas to the target Golden Record schema, and the **Technical Requirements Document** (`TRD.md`) specifying the ETL execution flow and test cases. This gave the team a rigorous, agreed-upon blueprint before a single line of production code was written.

### 2. Python OOP ETL Engine
Bob authored the entire `etl_engine.py` module — a production-structured Python class (`GoldenRecordETL`) implementing the full Extract → Normalise → Resolve → Aggregate → Load pipeline. Bob designed the OOP structure, wrote each private stage method, implemented normalisation helpers (name title-casing, phone/SSN digit-stripping via `re`), the `_coalesce` utility, and the structured `_audit_log` mechanism that records every resolution decision as a typed dict for downstream UI consumption.

### 3. Fuzzy Matching Algorithms
The core intelligence of the engine — the two-pass resolution system — was designed and implemented by Bob. This includes:
- **Exact SSN resolution** using `groupby` on normalised SSNs with UUID group assignment.
- **Union-Find (disjoint set)** peer-matching algorithm with path compression for efficient O(α(n)) lookups across unresolved rows.
- **Tiered fuzzy stitch logic** that joins unresolved rows into existing resolved groups using `thefuzz.fuzz.token_set_ratio`, with separate thresholds for name+contact (>85) and name-only cross-system stitching (≥90).
- The **TC-3 false-positive guard** that rejects same-last-name merges without contact corroboration, preventing family-member conflation — a critical correctness requirement Bob identified from the test cases.

### 4. Streamlit Dashboard UI
Bob built the complete `app.py` Streamlit dashboard, including:
- A **KPI metrics row** showing total input rows, golden records produced, duplicates eliminated, merge decisions, and TC-3 rejections.
- **Pipeline Insights charts** — active products per customer and data lineage by source system — using `st.bar_chart`.
- A **Golden Records tab** with rich `st.dataframe` column configuration and a total exposure summary.
- A **Raw Source Data tab** with side-by-side source previews and a CSV download button.
- A **Compliance & Audit Logs tab** with expandable per-decision cards showing match type, name similarity score, contact corroboration, and rationale — designed to satisfy GDPR Article 30 and AML audit trail requirements.

### 5. Mock Data Generation
Bob generated the three source CSV files (`core_banking_extract.csv`, `credit_card_extract.csv`, `mortgage_extract.csv`) with deliberate real-world imperfections: inconsistent name capitalisations, differently formatted SSNs (with and without dashes), mixed phone formats, and strategically placed cross-system duplicates to exercise all three test cases.

---

## Running the App Locally

### Prerequisites

- Python **3.10** or higher
- `pip` package manager

### 1. Clone the repository

```bash
git clone https://github.com/ubturja/BobFusion-MDM.git
cd BobFusion-MDM
```

### 2. (Recommended) Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Launch the Streamlit dashboard

```bash
streamlit run app.py
```

The app will open automatically at `http://localhost:8501`.

### 5. (Optional) Run the ETL engine from the CLI

```bash
python etl_engine.py
```

This writes `golden_records_output.csv` to the project root and prints a Golden Records preview to stdout.

---

## Project Structure

```
.
├── app.py                        # Streamlit dashboard
├── etl_engine.py                 # GoldenRecordETL pipeline class
├── core_banking_extract.csv      # Source: Core Banking system
├── credit_card_extract.csv       # Source: Credit Card system
├── mortgage_extract.csv          # Source: Mortgage system
├── golden_records_output.csv     # Output: canonical Golden Records
├── System_Architecture.md        # Architecture diagram & component breakdown
├── ERD.md                        # Entity Relationship Diagram
├── TRD.md                        # Technical Requirements Document
├── golden_customer_record_prd.md # Product Requirements Document
└── requirements.txt              # Python dependencies
```

---

## Requirements

```text
pandas>=2.0.0
thefuzz>=0.22.1
python-Levenshtein>=0.25.0
streamlit>=1.35.0
```

> `python-Levenshtein` is an optional but strongly recommended C extension that makes `thefuzz` 4–10× faster. Remove it if your environment cannot compile C extensions.

---

## Test Cases

| # | Name | Scenario | Expected Result |
|---|------|----------|-----------------|
| TC-1 | Exact SSN Match | Two records share a normalised SSN but have different name spellings | **Merged** into one Golden Record |
| TC-2 | Fuzzy Match | Two records have no SSN, identical email, and >85% name similarity | **Merged** into one Golden Record |
| TC-3 | Negative Match | Two records share only a last name (e.g., same family), different contact fields | **Not merged** — kept as separate Golden Records |

---

## Built With

| Technology | Role |
|------------|------|
| [Python 3.10+](https://python.org) | Core language |
| [pandas](https://pandas.pydata.org) | Data ingestion, transformation, aggregation |
| [thefuzz](https://github.com/seatgeek/thefuzz) | Fuzzy string matching (Levenshtein distance) |
| [Streamlit](https://streamlit.io) | Interactive dashboard UI |
| [IBM Bob](https://www.ibm.com/bob) | AI engineering assistant — architecture, code, algorithms, UI |

---

*Built at the IBM Bob-a-thon 2025 · Powered by IBM Bob*
