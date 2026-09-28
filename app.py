"""
Golden Customer Record — Streamlit Dashboard
=============================================
Enterprise-grade UI for the GoldenRecordETL pipeline.

Tabs
----
1. Golden Records   — canonical output table + key metrics + data visualisations
2. Raw Source Data  — side-by-side view of the three source extracts + CSV export
3. Compliance & Audit Logs — full merge-decision audit trail for regulatory explainability
"""

import ast
from pathlib import Path

import pandas as pd
import streamlit as st

from etl_engine import GoldenRecordETL

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Golden Customer Record Engine",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BANK_CSV = "core_banking_extract.csv"
CARD_CSV = "credit_card_extract.csv"
MORT_CSV = "mortgage_extract.csv"
OUTPUT_CSV = "golden_records_output.csv"

SOURCE_COLORS = {
    "CoreBanking": "#3b82d4",
    "CreditCard":  "#7c5cd8",
    "Mortgage":    "#16a34a",
}

# ---------------------------------------------------------------------------
# Pipeline runner — cached so it only re-runs on file change
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def run_pipeline() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the ETL pipeline and return (golden_df, audit_df)."""
    etl = GoldenRecordETL()
    golden_df = etl.run_pipeline(
        bank_csv=BANK_CSV,
        card_csv=CARD_CSV,
        mort_csv=MORT_CSV,
        output_path=OUTPUT_CSV,
    )
    audit_df = etl.get_audit_log()
    return golden_df, audit_df


@st.cache_data(show_spinner=False)
def load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the three raw source CSVs."""
    return (
        pd.read_csv(BANK_CSV, dtype=str),
        pd.read_csv(CARD_CSV, dtype=str),
        pd.read_csv(MORT_CSV, dtype=str),
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/5/51/IBM_logo.svg",
        width=80,
    )
    st.title("Golden Customer\nRecord Engine")
    st.caption("Built with IBM Bob · Bob-a-thon 2025")
    st.divider()
    st.markdown(
        """
        **Pipeline**
        - Extract → 3 source CSVs
        - Normalise → regex + title case
        - Resolve → exact SSN + fuzzy match
        - Load → canonical golden records

        **Match Thresholds**
        | Rule | Score |
        |------|-------|
        | Fuzzy name + contact | > 85 |
        | Name-only stitch | ≥ 90 |
        """
    )
    st.divider()
    if st.button("🔄 Re-run Pipeline", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
missing = [f for f in [BANK_CSV, CARD_CSV, MORT_CSV] if not Path(f).exists()]
if missing:
    st.error(
        f"Missing source file(s): **{', '.join(missing)}**. "
        "Ensure all three CSV extracts are in the same directory as `app.py`."
    )
    st.stop()

with st.spinner("Running ETL pipeline…"):
    golden_df, audit_df = run_pipeline()
    core_df, card_df, mort_df = load_sources()

total_input_rows = len(core_df) + len(card_df) + len(mort_df)
merge_events     = len(audit_df[audit_df["decision"] == "MERGE"]) if not audit_df.empty else 0
rejected_events  = len(audit_df[audit_df["decision"] == "NO MERGE"]) if not audit_df.empty else 0

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🏦 Golden Customer Record Engine")
st.caption(
    "Master Data Management pipeline — deduplicates fragmented customer records "
    "from Core Banking, Credit Card, and Mortgage systems into a single source of truth."
)

# ---------------------------------------------------------------------------
# KPI Metrics row
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Input Rows",    total_input_rows)
c2.metric("Golden Records",      len(golden_df))
c3.metric("Records Merged",      total_input_rows - len(golden_df),
          delta=f"-{total_input_rows - len(golden_df)} duplicates eliminated",
          delta_color="inverse")
c4.metric("Merge Decisions",     merge_events)
c5.metric("Rejections (TC-3)",   rejected_events)

st.divider()

# ---------------------------------------------------------------------------
# Visualisations (below metrics, above tabs)
# ---------------------------------------------------------------------------
st.subheader("📊 Pipeline Insights")

viz_col1, viz_col2 = st.columns(2, gap="large")

# --- Chart 1: Active Products per Customer ---
with viz_col1:
    st.markdown("**Active Products per Customer**")

    def _count_products(val: str) -> int:
        try:
            return len(ast.literal_eval(val))
        except Exception:
            return 0

    product_counts = golden_df["Active_Products"].apply(_count_products)
    dist = product_counts.value_counts().sort_index().reset_index()
    dist.columns = ["Products Held", "# Customers"]
    dist["Products Held"] = dist["Products Held"].apply(
        lambda n: f"{n} Product{'s' if n != 1 else ''}"
    )
    st.bar_chart(dist.set_index("Products Held"), color="#3b82d4")

# --- Chart 2: Data Lineage — records originating per source system ---
with viz_col2:
    st.markdown("**Data Lineage — Records per Source System**")

    source_counts: dict[str, int] = {"CoreBanking": 0, "CreditCard": 0, "Mortgage": 0}
    for val in golden_df["Source_Systems"]:
        try:
            systems = ast.literal_eval(val)
            for s in systems:
                if s in source_counts:
                    source_counts[s] += 1
        except Exception:
            pass

    lineage_df = pd.DataFrame(
        list(source_counts.items()), columns=["Source System", "# Golden Records"]
    )
    st.bar_chart(lineage_df.set_index("Source System"), color="#7c5cd8")

st.divider()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(
    ["🥇 Golden Records", "📂 Raw Source Data", "🔍 Compliance & Audit Logs"]
)

# ============================================================
# TAB 1 — Golden Records
# ============================================================
with tab1:
    st.subheader("Canonical Golden Customer Records")
    st.caption(
        f"{len(golden_df)} unique customers resolved from "
        f"{total_input_rows} source rows across 3 siloed systems."
    )

    # Colour-code the Active_Products column width for readability
    st.dataframe(
        golden_df,
        use_container_width=True,
        column_config={
            "Golden_ID":       st.column_config.TextColumn("Golden ID", width="medium"),
            "Legal_Name":      st.column_config.TextColumn("Legal Name", width="medium"),
            "National_ID":     st.column_config.TextColumn("National ID"),
            "Master_Email":    st.column_config.TextColumn("Email"),
            "Master_Phone":    st.column_config.TextColumn("Phone"),
            "Active_Products": st.column_config.TextColumn("Products", width="medium"),
            "Source_Systems":  st.column_config.TextColumn("Sources", width="medium"),
            "Source_IDs":      st.column_config.TextColumn("Source IDs", width="large"),
            "Total_Exposure":  st.column_config.NumberColumn(
                "Total Exposure ($)", format="$%,.2f"
            ),
        },
        hide_index=True,
    )

    # Total exposure summary
    total_exposure = golden_df["Total_Exposure"].sum()
    st.info(f"**Total Aggregated Exposure across all customers: ${total_exposure:,.2f}**")

# ============================================================
# TAB 2 — Raw Source Data + Download
# ============================================================
with tab2:
    st.subheader("Raw Source Extracts")
    st.caption(
        "The three siloed source CSVs ingested by the pipeline — exactly as received, "
        "before any normalisation."
    )

    src_col1, src_col2, src_col3 = st.columns(3, gap="medium")

    with src_col1:
        st.markdown("**🏛️ Core Banking**")
        st.dataframe(core_df, use_container_width=True, hide_index=True)
        st.caption(f"{len(core_df)} rows · Keys: Acct_Num, Cust_Name, Email")

    with src_col2:
        st.markdown("**💳 Credit Card**")
        st.dataframe(card_df, use_container_width=True, hide_index=True)
        st.caption(f"{len(card_df)} rows · Keys: Card_ID, Full_Name, SSN")

    with src_col3:
        st.markdown("**🏠 Mortgage**")
        st.dataframe(mort_df, use_container_width=True, hide_index=True)
        st.caption(f"{len(mort_df)} rows · Keys: Loan_ID, First/Last_Name, SSN")

    st.divider()

    # --- Export feature ---
    st.subheader("⬇️ Export Golden Records")
    st.caption(
        "Download the final canonical dataset as a CSV file for downstream "
        "use in KYC/AML screening, risk aggregation, or MDM platform ingestion."
    )

    csv_bytes = golden_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download golden_records_output.csv",
        data=csv_bytes,
        file_name="golden_records_output.csv",
        mime="text/csv",
        use_container_width=True,
        type="primary",
    )

# ============================================================
# TAB 3 — Compliance & Audit Logs
# ============================================================
with tab3:
    st.subheader("Compliance & Audit Logs")
    st.caption(
        "Every merge decision made by the resolution engine is recorded here. "
        "In a production environment this log would feed directly into a "
        "regulatory audit trail (e.g., GDPR Article 30 processing records, "
        "AML suspicious-activity justifications)."
    )

    if audit_df.empty:
        st.info("No merge decisions were logged. Run the pipeline with data containing duplicates.")
    else:
        merges   = audit_df[audit_df["decision"] == "MERGE"]
        rejects  = audit_df[audit_df["decision"] == "NO MERGE"]

        # Summary badges
        badge_col1, badge_col2, badge_col3 = st.columns(3)
        badge_col1.metric("Total Decisions Logged", len(audit_df))
        badge_col2.metric("✅ Merges Approved",      len(merges))
        badge_col3.metric("🚫 Merges Rejected",      len(rejects))

        st.divider()

        # --- Approved Merges ---
        st.markdown("### ✅ Approved Merge Decisions")
        st.caption(
            "Records where the engine determined two or more source rows represent "
            "the same real-world customer."
        )

        if merges.empty:
            st.info("No merge decisions recorded.")
        else:
            for _, row in merges.iterrows():
                label = (
                    f"**{row['golden_name']}** — {row['match_type']} "
                    f"(Name Score: {row['name_score']})"
                )
                with st.expander(label):
                    detail_col1, detail_col2 = st.columns(2)
                    detail_col1.markdown(f"**Decision:** `{row['decision']}`")
                    detail_col1.markdown(f"**Match Type:** {row['match_type']}")
                    detail_col1.markdown(f"**Name Similarity Score:** `{row['name_score']}`")
                    detail_col2.markdown(f"**Source IDs Merged:** `{row['source_ids']}`")
                    detail_col2.markdown(f"**Contact Corroboration:** `{row['contact_corroboration']}`")
                    st.markdown(f"**Rationale:** {row['match_detail']}")

        st.divider()

        # --- Rejected Merges (TC-3 guard) ---
        st.markdown("### 🚫 Rejected Merge Decisions")
        st.caption(
            "Records where the name similarity score exceeded the threshold but "
            "contact-field corroboration was absent. These are kept as separate "
            "Golden Records to prevent false-positive family-member conflation."
        )

        if rejects.empty:
            st.success("No merge rejections — no TC-3 false-positive candidates found.")
        else:
            for _, row in rejects.iterrows():
                label = (
                    f"**{row['golden_name']}** — Name Score: {row['name_score']}% "
                    f"· {row['match_type']}"
                )
                with st.expander(label):
                    detail_col1, detail_col2 = st.columns(2)
                    detail_col1.markdown(f"**Decision:** `{row['decision']}`")
                    detail_col1.markdown(f"**Match Type:** {row['match_type']}")
                    detail_col1.markdown(f"**Name Similarity Score:** `{row['name_score']}%`")
                    detail_col2.markdown(f"**Source IDs Compared:** `{row['source_ids']}`")
                    detail_col2.markdown(f"**Contact Result:** `{row['contact_corroboration']}`")
                    st.markdown(f"**Rationale:** {row['match_detail']}")

        st.divider()

        # Full raw audit log for power users / regulators
        with st.expander("📋 Full Raw Audit Log (all decisions)"):
            st.dataframe(
                audit_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "decision":              st.column_config.TextColumn("Decision"),
                    "golden_name":           st.column_config.TextColumn("Customer"),
                    "source_ids":            st.column_config.TextColumn("Source IDs"),
                    "match_type":            st.column_config.TextColumn("Match Type"),
                    "match_detail":          st.column_config.TextColumn("Detail", width="large"),
                    "name_score":            st.column_config.TextColumn("Name Score"),
                    "contact_corroboration": st.column_config.TextColumn("Contact Corroboration"),
                },
            )
