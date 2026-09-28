"""
Golden Customer Record ETL Engine
==================================
Ingests fragmented customer data from three siloed banking systems (Core Banking,
Credit Card, Mortgage), normalises the records, resolves duplicates via exact SSN
matching and fuzzy-logic fallback, and outputs a canonical "Golden Record" dataset.

Architecture: Extract → Normalise → Resolve (Exact) → Resolve (Fuzzy) → Aggregate → Load
"""

import logging
import re
import uuid
from typing import Optional

import pandas as pd
from thefuzz import fuzz

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FUZZY_NAME_THRESHOLD: int = 85   # minimum token_set_ratio score to consider a name match
PRODUCT_CORE: str = "Checking"
PRODUCT_CARD: str = "Credit Card"
PRODUCT_MORT: str = "Mortgage"


# ---------------------------------------------------------------------------
# GoldenRecordETL
# ---------------------------------------------------------------------------
class GoldenRecordETL:
    """
    Orchestrates the full ETL pipeline for producing canonical Golden Customer Records.

    Usage
    -----
    etl = GoldenRecordETL()
    golden_df = etl.run_pipeline("core_banking_extract.csv",
                                  "credit_card_extract.csv",
                                  "mortgage_extract.csv")
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._audit_log: list[dict] = []

    def get_audit_log(self) -> pd.DataFrame:
        """Return the structured audit log as a DataFrame for UI consumption."""
        if not self._audit_log:
            return pd.DataFrame(columns=[
                "decision", "golden_name", "source_ids",
                "match_type", "match_detail", "name_score", "contact_corroboration",
            ])
        return pd.DataFrame(self._audit_log)

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        bank_csv: str,
        card_csv: str,
        mort_csv: str,
        output_path: str = "golden_records_output.csv",
    ) -> pd.DataFrame:
        """
        Execute the end-to-end ETL pipeline.

        Parameters
        ----------
        bank_csv : str   Path to core_banking_extract.csv
        card_csv : str   Path to credit_card_extract.csv
        mort_csv : str   Path to mortgage_extract.csv
        output_path : str  Destination file for the Golden Records CSV

        Returns
        -------
        pd.DataFrame  The final Golden Records DataFrame
        """
        self._audit_log = []   # reset on each run
        self.logger.info("=" * 60)
        self.logger.info("Golden Customer Record ETL Pipeline — START")
        self.logger.info("=" * 60)

        # Stage 1 — Extract
        core_df, card_df, mort_df = self._extract(bank_csv, card_csv, mort_csv)

        # Stage 2 — Normalise
        core_norm = self._normalise_core(core_df)
        card_norm = self._normalise_card(card_df)
        mort_norm = self._normalise_mort(mort_df)

        # Stage 3 — Resolve & Aggregate
        golden_df = self._resolve_and_aggregate(core_norm, card_norm, mort_norm)

        # Stage 4 — Load
        self._load(golden_df, output_path)

        self.logger.info("=" * 60)
        self.logger.info("Pipeline complete. %d Golden Records produced.", len(golden_df))
        self.logger.info("=" * 60)
        return golden_df

    # ------------------------------------------------------------------
    # Stage 1: Extract
    # ------------------------------------------------------------------

    def _extract(
        self, bank_csv: str, card_csv: str, mort_csv: str
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Read the three source CSVs into DataFrames."""
        self.logger.info("--- STAGE 1: EXTRACT ---")

        core_df = pd.read_csv(bank_csv, dtype=str)
        self.logger.info("Ingested Core Banking: %d rows from '%s'", len(core_df), bank_csv)

        card_df = pd.read_csv(card_csv, dtype=str)
        self.logger.info("Ingested Credit Card:  %d rows from '%s'", len(card_df), card_csv)

        mort_df = pd.read_csv(mort_csv, dtype=str)
        self.logger.info("Ingested Mortgage:     %d rows from '%s'", len(mort_df), mort_csv)

        return core_df, card_df, mort_df

    # ------------------------------------------------------------------
    # Stage 2: Normalise (per source)
    # ------------------------------------------------------------------

    def _normalise_core(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalise Core Banking extract into the staging schema.

        Staging columns produced
        ------------------------
        norm_name, norm_email, norm_phone, norm_ssn,
        account_balance, source_system, product, source_id
        """
        self.logger.info("--- STAGE 2: NORMALISE — Core Banking ---")
        out = pd.DataFrame()
        out["source_id"]       = df["Acct_Num"]
        out["norm_name"]       = df["Cust_Name"].apply(self._normalise_name)
        out["norm_email"]      = df["Email"].apply(self._normalise_email)
        out["norm_phone"]      = pd.NA   # Core Banking has no phone column
        out["norm_ssn"]        = df["SSN"].apply(self._normalise_ssn) if "SSN" in df.columns else pd.NA
        out["account_balance"] = pd.to_numeric(df["Account_Balance"], errors="coerce").fillna(0.0)
        out["credit_limit"]    = 0.0
        out["loan_amount"]     = 0.0
        out["source_system"]   = "CoreBanking"
        out["product"]         = PRODUCT_CORE
        self.logger.info("Core Banking normalised: %d rows", len(out))
        return out

    def _normalise_card(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise Credit Card extract into the staging schema."""
        self.logger.info("--- STAGE 2: NORMALISE — Credit Card ---")
        out = pd.DataFrame()
        out["source_id"]       = df["Card_ID"]
        out["norm_name"]       = df["Full_Name"].apply(self._normalise_name)
        out["norm_email"]      = df["Email"].apply(self._normalise_email) if "Email" in df.columns else pd.NA
        out["norm_phone"]      = df["Phone_Num"].apply(self._normalise_phone)
        out["norm_ssn"]        = df["SSN"].apply(self._normalise_ssn)
        out["account_balance"] = 0.0
        out["credit_limit"]    = pd.to_numeric(df["Credit_Limit"], errors="coerce").fillna(0.0)
        out["loan_amount"]     = 0.0
        out["source_system"]   = "CreditCard"
        out["product"]         = PRODUCT_CARD
        self.logger.info("Credit Card normalised: %d rows", len(out))
        return out

    def _normalise_mort(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise Mortgage extract into the staging schema."""
        self.logger.info("--- STAGE 2: NORMALISE — Mortgage ---")
        out = pd.DataFrame()
        out["source_id"]       = df["Loan_ID"]
        out["norm_name"]       = (
            df["First_Name"].fillna("") + " " + df["Last_Name"].fillna("")
        ).apply(self._normalise_name)
        out["norm_email"]      = pd.NA   # Mortgage has no email column
        out["norm_phone"]      = df["Contact_Number"].apply(self._normalise_phone)
        out["norm_ssn"]        = df["SSN"].apply(self._normalise_ssn)
        out["account_balance"] = 0.0
        out["credit_limit"]    = 0.0
        out["loan_amount"]     = pd.to_numeric(df["Loan_Amount"], errors="coerce").fillna(0.0)
        out["source_system"]   = "Mortgage"
        out["product"]         = PRODUCT_MORT
        self.logger.info("Mortgage normalised: %d rows", len(out))
        return out

    # ------------------------------------------------------------------
    # Stage 3: Resolve & Aggregate
    # ------------------------------------------------------------------

    def _resolve_and_aggregate(
        self,
        core: pd.DataFrame,
        card: pd.DataFrame,
        mort: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Assign a shared `group_id` to every staging row that belongs to the
        same real-world customer, then aggregate each group into one Golden Record.

        Resolution order
        ----------------
        1. Exact SSN match — deterministic; groups any rows sharing a normalised SSN.
        2. Unified fuzzy pass — for every still-unresolved row, tries to join an
           existing resolved group OR match peer unresolved rows via name+contact
           or high-confidence name-only (≥ STITCH_NAME_ONLY_THRESHOLD).
           Only rows that are actually matched get a group_id here.
        3. Singleton assignment — any row still unresolved becomes its own group.
        """
        self.logger.info("--- STAGE 3: RESOLVE & AGGREGATE ---")

        staging = pd.concat([core, card, mort], ignore_index=True)
        staging["group_id"] = pd.NA  # will be filled by resolution logic

        # Pass 1 – deterministic SSN match
        staging = self._resolve_exact(staging)

        # Pass 2 – unified fuzzy + stitch (only commits group_id for matched rows)
        staging = self._resolve_fuzzy_and_stitch(staging)

        # Pass 3 – singletons: every remaining unresolved row becomes its own group
        mask_no_group = staging["group_id"].isna()
        singleton_count = mask_no_group.sum()
        staging.loc[mask_no_group, "group_id"] = [
            str(uuid.uuid4()) for _ in range(singleton_count)
        ]
        self.logger.info(
            "Singleton assignment: %d unmatched rows given individual groups.",
            singleton_count,
        )

        return self._aggregate(staging)

    def _resolve_exact(self, staging: pd.DataFrame) -> pd.DataFrame:
        """
        TC-1: Assign shared group_id to all rows sharing the same non-null
        normalised SSN.
        """
        self.logger.info("Running Exact SSN Resolution …")
        has_ssn = staging["norm_ssn"].notna() & (staging["norm_ssn"] != "")
        ssn_groups = staging[has_ssn].groupby("norm_ssn")

        merge_count = 0
        for ssn, group in ssn_groups:
            gid = str(uuid.uuid4())
            staging.loc[group.index, "group_id"] = gid
            if len(group) > 1:
                names = group["norm_name"].tolist()
                source_ids = group["source_id"].tolist()
                self.logger.info(
                    "[EXACT MATCH] SSN='%s' → merged %d records %s into group %s",
                    ssn, len(group), names, gid[:8],
                )
                self._audit_log.append({
                    "decision":              "MERGE",
                    "golden_name":           names[0],
                    "source_ids":            ", ".join(str(s) for s in source_ids),
                    "match_type":            "Exact SSN Match",
                    "match_detail":          f"Normalised SSN: {ssn}",
                    "name_score":            "N/A",
                    "contact_corroboration": "N/A",
                })
                merge_count += 1

        self.logger.info("Exact resolution: %d SSN-based merge groups created.", merge_count)
        return staging

    # Minimum name score to attempt any fuzzy merge (name + contact required).
    # Used in the main fuzzy pass.
    # TC-3 guard: "James Wilson" vs "John Wilson" = 71, safely below this floor.

    # Minimum name score for a name-only merge (no contact field required).
    # Used when two rows are from different source systems that carry different
    # contact fields (e.g. Core Banking has email; CC/Mortgage have phone only).
    # "Robert Smith" vs "Robert Smyth" = 92 → passes.
    # "Rob Smith" vs "Robert Smyth" = 86 → fails (intentional — only the highest
    #  variant in the group reaches 92 when compared to the CB row).
    STITCH_NAME_ONLY_THRESHOLD: int = 90

    def _resolve_fuzzy_and_stitch(self, staging: pd.DataFrame) -> pd.DataFrame:
        """
        Unified fuzzy resolution pass for all rows that are still unresolved
        after exact SSN matching.

        For each unresolved row we attempt to find a home in two ways:

        A. Join an already-resolved group (stitch):
           Tier A-1 — name_score > FUZZY_NAME_THRESHOLD  AND  contact overlap
           Tier A-2 — name_score >= STITCH_NAME_ONLY_THRESHOLD (name-only, ≥ 90)

        B. Peer-match with another unresolved row (union-find):
           name_score > FUZZY_NAME_THRESHOLD  AND  contact overlap (TC-2)

        IMPORTANT: only rows that were actually matched get a group_id assigned.
        Singletons (no match found) remain group_id=NA so the caller can assign
        them individual groups.  This prevents the stitch from being skipped
        because the fuzzy pass pre-consumed all unresolved rows.

        TC-3 safety: "James Wilson" vs "John Wilson" = 71 → never reaches threshold.
        """
        self.logger.info("Running Unified Fuzzy + Stitch Resolution …")

        unresolved_mask = staging["group_id"].isna()
        if not unresolved_mask.any():
            self.logger.info("No unresolved rows — pass skipped.")
            return staging

        # ---- Build resolved-group representatives ----
        resolved = staging[~unresolved_mask]
        group_reps: list[dict] = []
        for gid, grp in resolved.groupby("group_id"):
            names = [n for n in grp["norm_name"].dropna().tolist() if n]
            group_reps.append({
                "group_id":   gid,
                "names":      names,
                "norm_email": self._coalesce(grp["norm_email"]),
                "norm_phone": self._coalesce(grp["norm_phone"]),
            })

        # ---- Union-Find for peer unresolved rows ----
        unresolved_indices = list(staging[unresolved_mask].index)
        parent: dict[int, int] = {idx: idx for idx in unresolved_indices}
        merged_pairs: set[int] = set()  # track which indices actually found a partner

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)
            merged_pairs.add(x)
            merged_pairs.add(y)

        # ---- Pass A: stitch unresolved rows into existing resolved groups ----
        stitched: dict[int, str] = {}   # idx → group_id
        for idx in unresolved_indices:
            row = staging.loc[idx]
            best_gid:    Optional[str] = None
            best_score:  int = 0
            best_reason: str = ""

            for rep in group_reps:
                top_name_score = max(
                    (fuzz.token_set_ratio(str(row["norm_name"]), n) for n in rep["names"]),
                    default=0,
                )
                if top_name_score <= FUZZY_NAME_THRESHOLD:
                    continue

                contact_match = self._contacts_overlap(row, pd.Series(rep))

                # Tier A-1: name > 85 AND contact
                if contact_match and top_name_score > best_score:
                    best_score    = top_name_score
                    best_gid      = rep["group_id"]
                    best_reason   = f"name_score={top_name_score}, contact={contact_match} [Tier A-1]"
                    best_tier     = "Fuzzy Stitch — Name + Contact"
                    best_contact  = contact_match
                    continue

                # Tier A-2: name-only ≥ 90
                if (
                    not contact_match
                    and top_name_score >= self.STITCH_NAME_ONLY_THRESHOLD
                    and top_name_score > best_score
                ):
                    best_score    = top_name_score
                    best_gid      = rep["group_id"]
                    best_reason   = f"name_score={top_name_score} [Tier A-2, name-only]"
                    best_tier     = "Fuzzy Stitch — High-Confidence Name Only (≥90)"
                    best_contact  = "None required"

            if best_gid:
                stitched[idx] = best_gid
                # Resolve names of the target group for the audit entry
                target_names = next(
                    (r["names"] for r in group_reps if r["group_id"] == best_gid), []
                )
                self.logger.info(
                    "[STITCH] '%s' → group %s | %s",
                    row["norm_name"], best_gid[:8], best_reason,
                )
                self._audit_log.append({
                    "decision":              "MERGE",
                    "golden_name":           row["norm_name"],
                    "source_ids":            str(row["source_id"]),
                    "match_type":            best_tier,
                    "match_detail":          (
                        f"'{row['norm_name']}' joined group containing "
                        f"{target_names}"
                    ),
                    "name_score":            best_score,
                    "contact_corroboration": best_contact,
                })
            else:
                self.logger.debug(
                    "[STITCH SKIP] '%s' — no existing group match.", row["norm_name"]
                )

        # ---- Pass B: peer-match remaining unresolved rows (TC-2) ----
        # Only consider rows NOT already stitched in Pass A.
        still_unresolved = [i for i in unresolved_indices if i not in stitched]
        for i in range(len(still_unresolved)):
            for j in range(i + 1, len(still_unresolved)):
                idx_a, idx_b = still_unresolved[i], still_unresolved[j]
                row_a = staging.loc[idx_a]
                row_b = staging.loc[idx_b]

                name_score = fuzz.token_set_ratio(
                    str(row_a["norm_name"]), str(row_b["norm_name"])
                )
                if name_score <= FUZZY_NAME_THRESHOLD:
                    continue  # TC-3 guard

                contact_match = self._contacts_overlap(row_a, row_b)
                if contact_match:
                    self.logger.info(
                        "[FUZZY MATCH] '%s' ↔ '%s' | name_score=%d | contact=%s → MERGE",
                        row_a["norm_name"], row_b["norm_name"], name_score, contact_match,
                    )
                    union(idx_a, idx_b)
                    self._audit_log.append({
                        "decision":              "MERGE",
                        "golden_name":           row_a["norm_name"],
                        "source_ids":            f"{row_a['source_id']} + {row_b['source_id']}",
                        "match_type":            "Fuzzy Peer Match — Name + Contact",
                        "match_detail":          (
                            f"'{row_a['norm_name']}' ↔ '{row_b['norm_name']}'"
                        ),
                        "name_score":            name_score,
                        "contact_corroboration": contact_match,
                    })
                else:
                    self.logger.info(
                        "[FUZZY NO-MATCH] '%s' ↔ '%s' | name_score=%d | no shared contact → SKIP",
                        row_a["norm_name"], row_b["norm_name"], name_score,
                    )
                    self._audit_log.append({
                        "decision":              "NO MERGE",
                        "golden_name":           f"{row_a['norm_name']} / {row_b['norm_name']}",
                        "source_ids":            f"{row_a['source_id']} vs {row_b['source_id']}",
                        "match_type":            "Fuzzy — Name Only (Rejected)",
                        "match_detail":          (
                            f"'{row_a['norm_name']}' ↔ '{row_b['norm_name']}' — "
                            f"name score {name_score}% but no shared contact field"
                        ),
                        "name_score":            name_score,
                        "contact_corroboration": "None — REJECTED",
                    })

        # ---- Commit group IDs ----
        # Stitch results
        for idx, gid in stitched.items():
            staging.at[idx, "group_id"] = gid

        # Peer-match results: only assign a group_id if the row was actually merged
        root_to_gid: dict[int, str] = {}
        for idx in still_unresolved:
            if idx in merged_pairs:
                root = find(idx)
                if root not in root_to_gid:
                    root_to_gid[root] = str(uuid.uuid4())
                staging.at[idx, "group_id"] = root_to_gid[root]
            # else: leave as NA — will become a singleton in the next pass

        self.logger.info(
            "Unified fuzzy pass complete: %d stitched into existing groups, "
            "%d peer-matched into new groups.",
            len(stitched), len(root_to_gid),
        )
        return staging

    def _aggregate(self, staging: pd.DataFrame) -> pd.DataFrame:
        """
        Collapse each group into a single Golden Record row.
        """
        self.logger.info("Aggregating groups into Golden Records …")
        records = []

        for gid, group in staging.groupby("group_id"):
            name       = self._coalesce(group["norm_name"])
            email      = self._coalesce(group["norm_email"])
            phone      = self._coalesce(group["norm_phone"])
            ssn        = self._coalesce(group["norm_ssn"])
            products   = sorted(group["product"].dropna().unique().tolist())
            sources    = sorted(group["source_system"].dropna().unique().tolist())
            source_ids = group["source_id"].dropna().tolist()
            total_exp  = (
                group["account_balance"].sum()
                + group["credit_limit"].sum()
                + group["loan_amount"].sum()
            )

            records.append({
                "Golden_ID":       str(uuid.uuid4()),
                "Legal_Name":      name,
                "National_ID":     ssn,
                "Master_Email":    email,
                "Master_Phone":    phone,
                "Active_Products": str(products),
                "Source_Systems":  str(sources),
                "Source_IDs":      str(source_ids),
                "Total_Exposure":  round(total_exp, 2),
            })

        golden_df = pd.DataFrame(records)
        self.logger.info("Aggregation complete: %d Golden Records.", len(golden_df))
        return golden_df

    # ------------------------------------------------------------------
    # Stage 4: Load
    # ------------------------------------------------------------------

    def _load(self, golden_df: pd.DataFrame, output_path: str) -> None:
        """Write the Golden Records DataFrame to CSV."""
        self.logger.info("--- STAGE 4: LOAD ---")
        golden_df.to_csv(output_path, index=False)
        self.logger.info("Golden Records written to '%s'", output_path)

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_name(value: Optional[str]) -> str:
        """Convert to Title Case and strip excess whitespace."""
        if pd.isna(value) or str(value).strip() == "":
            return ""
        return " ".join(str(value).strip().title().split())

    @staticmethod
    def _normalise_email(value: Optional[str]) -> Optional[str]:
        """Lowercase and strip whitespace."""
        if pd.isna(value) or str(value).strip() == "":
            return pd.NA
        return str(value).strip().lower()

    @staticmethod
    def _normalise_phone(value: Optional[str]) -> Optional[str]:
        """Strip all non-numeric characters, return digits-only string."""
        if pd.isna(value) or str(value).strip() == "":
            return pd.NA
        digits = re.sub(r"\D", "", str(value))
        return digits if digits else pd.NA

    @staticmethod
    def _normalise_ssn(value: Optional[str]) -> Optional[str]:
        """Strip all non-numeric characters from SSN."""
        if pd.isna(value) or str(value).strip() == "":
            return pd.NA
        digits = re.sub(r"\D", "", str(value))
        return digits if digits else pd.NA

    # ------------------------------------------------------------------
    # Merge helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coalesce(series: pd.Series) -> Optional[str]:
        """Return the first non-null, non-empty value in a Series."""
        for val in series:
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                s = str(val).strip()
                if s and s.lower() not in ("nan", "none", "<na>"):
                    return s
        return None

    @staticmethod
    def _contacts_overlap(row_a: pd.Series, row_b: pd.Series) -> Optional[str]:
        """
        Return a description of the shared contact field if either email or
        phone matches between two rows, otherwise return None.

        This is the TC-3 guard: same last name alone will not trigger a merge
        unless a contact field corroborates the identity.
        """
        # Email check
        email_a = row_a.get("norm_email")
        email_b = row_b.get("norm_email")
        if (
            email_a and email_b
            and not (isinstance(email_a, float) and pd.isna(email_a))
            and not (isinstance(email_b, float) and pd.isna(email_b))
            and str(email_a).strip().lower() == str(email_b).strip().lower()
        ):
            return f"email={email_a}"

        # Phone check
        phone_a = row_a.get("norm_phone")
        phone_b = row_b.get("norm_phone")
        if (
            phone_a and phone_b
            and not (isinstance(phone_a, float) and pd.isna(phone_a))
            and not (isinstance(phone_b, float) and pd.isna(phone_b))
            and str(phone_a).strip() == str(phone_b).strip()
        ):
            return f"phone={phone_a}"

        return None


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    etl = GoldenRecordETL()
    result = etl.run_pipeline(
        bank_csv="core_banking_extract.csv",
        card_csv="credit_card_extract.csv",
        mort_csv="mortgage_extract.csv",
        output_path="golden_records_output.csv",
    )
    print("\n--- Golden Records Preview ---")
    print(result.to_string(index=False))
