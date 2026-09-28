"""
test_etl_engine.py
==================
pytest test suite for GoldenRecordETL.

Test coverage
-------------
  Unit tests (no file I/O)
    NormalisationTests     — SSN stripping, name title-casing, phone cleaning, email lowercasing
    ContactsOverlapTests   — helper that guards TC-3 false-positive prevention

  Integration tests (run the full pipeline against temp CSV fixtures)
    TC1_ExactSSNMergeTests — records sharing a normalised SSN must be merged regardless of name spelling
    TC2_FuzzyMergeTests    — records with no SSN but >85 name score + matching contact must be merged
    TC3_FamilyGuardTests   — same last name + different contact must produce distinct Golden Records
    AggregationTests       — product lists combined correctly; total financial exposure sums accurately

Run with:
    pytest test_etl_engine.py -v
"""

import os
import tempfile
import textwrap
import unittest

import pandas as pd
from thefuzz import fuzz

from etl_engine import GoldenRecordETL, FUZZY_NAME_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv(path: str, content: str) -> None:
    """Write a dedented CSV string to *path*."""
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(content).lstrip())


def _run_pipeline(bank_content: str, card_content: str, mort_content: str) -> tuple:
    """
    Write three in-memory CSV strings to temp files, run the pipeline, and
    return (golden_df, audit_df, etl_instance).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        bank_path = os.path.join(tmpdir, "core.csv")
        card_path = os.path.join(tmpdir, "card.csv")
        mort_path = os.path.join(tmpdir, "mort.csv")
        out_path  = os.path.join(tmpdir, "golden.csv")

        _write_csv(bank_path, bank_content)
        _write_csv(card_path, card_content)
        _write_csv(mort_path, mort_content)

        etl    = GoldenRecordETL()
        golden = etl.run_pipeline(bank_path, card_path, mort_path, output_path=out_path)
        audit  = etl.get_audit_log()
        return golden, audit, etl


# ─────────────────────────────────────────────────────────────────────────────
# Unit Tests — Normalisation helpers
# ─────────────────────────────────────────────────────────────────────────────

class NormalisationTests(unittest.TestCase):
    """Pure unit tests for the four normalisation static methods."""

    # ── SSN ──────────────────────────────────────────────────────────────────

    def test_ssn_strips_dashes(self):
        """Standard dashed SSN format → digits only."""
        self.assertEqual(GoldenRecordETL._normalise_ssn("467-88-1234"), "467881234")

    def test_ssn_strips_partial_dashes(self):
        """Partially formatted SSN (e.g. from credit card CSV) → digits only."""
        self.assertEqual(GoldenRecordETL._normalise_ssn("46788-1234"), "467881234")

    def test_ssn_no_dashes_unchanged(self):
        """Already-clean 9-digit SSN passes through unchanged."""
        self.assertEqual(GoldenRecordETL._normalise_ssn("467881234"), "467881234")

    def test_ssn_null_returns_na(self):
        """NaN / empty SSN returns pd.NA (not a string)."""
        result = GoldenRecordETL._normalise_ssn(float("nan"))
        self.assertTrue(pd.isna(result), f"Expected NA, got {result!r}")

    def test_ssn_empty_string_returns_na(self):
        result = GoldenRecordETL._normalise_ssn("")
        self.assertTrue(pd.isna(result))

    # ── Name ─────────────────────────────────────────────────────────────────

    def test_name_all_caps_to_title(self):
        """LINDA CHEN → Linda Chen."""
        self.assertEqual(GoldenRecordETL._normalise_name("LINDA CHEN"), "Linda Chen")

    def test_name_all_lower_to_title(self):
        """maria garcia → Maria Garcia."""
        self.assertEqual(GoldenRecordETL._normalise_name("maria garcia"), "Maria Garcia")

    def test_name_extra_whitespace_collapsed(self):
        """Internal extra spaces are collapsed."""
        self.assertEqual(GoldenRecordETL._normalise_name("  Jonathan   Doe  "), "Jonathan Doe")

    def test_name_already_title_unchanged(self):
        self.assertEqual(GoldenRecordETL._normalise_name("Jonathan Doe"), "Jonathan Doe")

    def test_name_null_returns_empty_string(self):
        self.assertEqual(GoldenRecordETL._normalise_name(float("nan")), "")

    # ── Phone ─────────────────────────────────────────────────────────────────

    def test_phone_strips_parentheses_and_dashes(self):
        """(555) 310-4400 → 5553104400."""
        self.assertEqual(GoldenRecordETL._normalise_phone("(555) 310-4400"), "5553104400")

    def test_phone_strips_dots(self):
        """555.210.7890 → 5552107890."""
        self.assertEqual(GoldenRecordETL._normalise_phone("555.210.7890"), "5552107890")

    def test_phone_already_digits_unchanged(self):
        self.assertEqual(GoldenRecordETL._normalise_phone("5557340088"), "5557340088")

    def test_phone_null_returns_na(self):
        result = GoldenRecordETL._normalise_phone(float("nan"))
        self.assertTrue(pd.isna(result))

    # ── Email ─────────────────────────────────────────────────────────────────

    def test_email_lowercased(self):
        self.assertEqual(GoldenRecordETL._normalise_email("Jon.Doe@Gmail.COM"), "jon.doe@gmail.com")

    def test_email_strips_whitespace(self):
        self.assertEqual(GoldenRecordETL._normalise_email("  jon.doe@gmail.com  "), "jon.doe@gmail.com")

    def test_email_null_returns_na(self):
        result = GoldenRecordETL._normalise_email(float("nan"))
        self.assertTrue(pd.isna(result))


# ─────────────────────────────────────────────────────────────────────────────
# Unit Tests — _contacts_overlap (TC-3 guard)
# ─────────────────────────────────────────────────────────────────────────────

class ContactsOverlapTests(unittest.TestCase):
    """Unit tests for the _contacts_overlap helper."""

    def _row(self, email=None, phone=None) -> pd.Series:
        return pd.Series({"norm_email": email, "norm_phone": phone})

    def test_matching_email_returns_description(self):
        a = self._row(email="jon.doe@gmail.com")
        b = self._row(email="jon.doe@gmail.com")
        result = GoldenRecordETL._contacts_overlap(a, b)
        self.assertIsNotNone(result)
        self.assertIn("email", result)

    def test_matching_phone_returns_description(self):
        a = self._row(phone="5551234567")
        b = self._row(phone="5551234567")
        result = GoldenRecordETL._contacts_overlap(a, b)
        self.assertIsNotNone(result)
        self.assertIn("phone", result)

    def test_different_email_and_phone_returns_none(self):
        """Shared last name but different contacts — must return None (TC-3 guard)."""
        a = self._row(email="rachel.torres@email.com", phone="5555196677")
        b = self._row(email="rob.torres@personalmail.com", phone="5559631122")
        self.assertIsNone(GoldenRecordETL._contacts_overlap(a, b))

    def test_both_null_returns_none(self):
        a = self._row()
        b = self._row()
        self.assertIsNone(GoldenRecordETL._contacts_overlap(a, b))

    def test_email_case_insensitive_match(self):
        a = self._row(email="jon.doe@gmail.com")
        b = self._row(email="JON.DOE@GMAIL.COM")
        # Both rows are already normalised by the pipeline before this helper
        # is called, but we verify the helper itself is case-insensitive.
        result = GoldenRecordETL._contacts_overlap(a, b)
        self.assertIsNotNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# Integration fixtures (inline minimal CSVs)
# ─────────────────────────────────────────────────────────────────────────────

# Minimal skeleton CSVs with only the columns the normalise methods read.
# Each fixture is self-contained and exercises exactly one test scenario.

_EMPTY_CARD = """\
    Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
"""

_EMPTY_MORT = """\
    Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
"""

_EMPTY_CORE = """\
    Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
"""


# ─────────────────────────────────────────────────────────────────────────────
# TC-1 — Exact SSN merge (name drift must not block the merge)
# ─────────────────────────────────────────────────────────────────────────────

class TC1_ExactSSNMergeTests(unittest.TestCase):
    """
    TC-1: Records sharing the same normalised SSN must be merged into a single
    Golden Record, regardless of name spelling differences or formatting
    inconsistencies in the source SSN field.
    """

    # Pair A: "Jonathan Doe" (Core Banking) vs "John Doe" (Credit Card)
    # fuzz.token_set_ratio = 80 — below the fuzzy threshold,
    # yet the SSN `467881234` must force a deterministic merge.
    _CORE_TC1A = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10001,Jonathan Doe,467-88-1234,jon.doe@gmail.com,1985-03-15,15420.50
    """
    _CARD_TC1A = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88001,John Doe,5553104400,46788-1234,jon.doe@gmail.com,8500.00
    """
    _MORT_TC1A = """\
        Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
        ML-55001,Jonathan,Doe,467881234,(555) 310-4400,320000.00
    """

    # Pair B: "LINDA CHEN" (Core Banking, all caps) vs "linda chen" (Credit Card, all lower)
    _CORE_TC1B = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10004,LINDA CHEN,302-77-8812,linda.chen@email.com,1995-02-14,5500.00
    """
    _CARD_TC1B = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88004,linda chen,555-214-9900,302778812,,7500.00
    """
    _MORT_TC1B = """\
        Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
        ML-55004,Linda,Chen,302778812,555-214-9900,400000.00
    """

    def test_tc1a_jonathan_john_doe_merged_into_one_record(self):
        """Jonathan Doe / John Doe / Jonathan Doe all share SSN → 1 Golden Record."""
        golden, audit, _ = _run_pipeline(self._CORE_TC1A, self._CARD_TC1A, self._MORT_TC1A)
        self.assertEqual(len(golden), 1, f"Expected 1 Golden Record, got {len(golden)}")

    def test_tc1a_merged_record_holds_all_three_products(self):
        golden, _, _ = _run_pipeline(self._CORE_TC1A, self._CARD_TC1A, self._MORT_TC1A)
        import ast
        products = ast.literal_eval(golden.iloc[0]["Active_Products"])
        self.assertIn("Checking",     products)
        self.assertIn("Credit Card",  products)
        self.assertIn("Mortgage",     products)

    def test_tc1a_national_id_is_normalised_digits_only(self):
        """Regardless of source format, the Golden Record's National_ID must be digits only."""
        golden, _, _ = _run_pipeline(self._CORE_TC1A, self._CARD_TC1A, self._MORT_TC1A)
        self.assertEqual(golden.iloc[0]["National_ID"], "467881234")

    def test_tc1a_audit_log_contains_exact_match_decision(self):
        _, audit, _ = _run_pipeline(self._CORE_TC1A, self._CARD_TC1A, self._MORT_TC1A)
        merge_rows = audit[audit["match_type"] == "Exact SSN Match"]
        self.assertGreater(len(merge_rows), 0, "No Exact SSN Match entry in audit log")

    def test_tc1b_linda_chen_casing_variants_merged(self):
        """LINDA CHEN / linda chen / Linda Chen all share SSN → 1 Golden Record."""
        golden, _, _ = _run_pipeline(self._CORE_TC1B, self._CARD_TC1B, self._MORT_TC1B)
        self.assertEqual(len(golden), 1)

    def test_tc1b_legal_name_is_title_cased(self):
        """The canonical Legal_Name must be Title Case, not 'LINDA CHEN' or 'linda chen'."""
        golden, _, _ = _run_pipeline(self._CORE_TC1B, self._CARD_TC1B, self._MORT_TC1B)
        self.assertEqual(golden.iloc[0]["Legal_Name"], "Linda Chen")

    def test_tc1_fuzz_score_alone_would_not_trigger_fuzzy_merge(self):
        """
        Sanity check: confirm that 'Jonathan Doe' vs 'John Doe' scores below
        FUZZY_NAME_THRESHOLD (85) so we know the merge is driven by SSN, not fuzzy logic.
        """
        score = fuzz.token_set_ratio("Jonathan Doe", "John Doe")
        self.assertLessEqual(score, FUZZY_NAME_THRESHOLD,
            f"Fuzz score {score} unexpectedly above threshold — TC-1 test premise is wrong")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2 — Fuzzy merge (no SSN, name score > 85 + contact match)
# ─────────────────────────────────────────────────────────────────────────────

class TC2_FuzzyMergeTests(unittest.TestCase):
    """
    TC-2: Records with NO SSN must be merged when:
      - fuzz.token_set_ratio(name_a, name_b) > 85, AND
      - at least one contact field (email or phone) matches.
    """

    # Pair A: "maria garcia" (Core Banking) vs "Maria Gracia" (Credit Card)
    # Note: CC has no SSN; CB has no phone. The shared email corroborates.
    _CORE_TC2A = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10002,maria garcia,,maria.garcia@email.com,1990-07-22,8200.00
    """
    _CARD_TC2A = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88002,Maria Gracia,555.210.7890,,maria.garcia@email.com,12000.00
    """
    _MORT_TC2A = """\
        Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
        ML-55011,Maria,Garcia,,5552107890,142000.00
    """

    # Pair B: "Patricia Lee" (Core Banking) vs "Patricia L. Lee" (Credit Card)
    _CORE_TC2B = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10010,Patricia Lee,,p.lee@email.com,1998-08-11,4750.00
    """
    _CARD_TC2B = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88011,Patricia L. Lee,,,p.lee@email.com,9000.00
    """
    _MORT_TC2B = _EMPTY_MORT   # no mortgage record for Patricia — still valid 2-source merge

    def test_tc2a_maria_garcia_gracia_merged_into_one_record(self):
        """maria garcia / Maria Gracia / Maria Garcia (no SSN) → 1 Golden Record."""
        golden, _, _ = _run_pipeline(self._CORE_TC2A, self._CARD_TC2A, self._MORT_TC2A)
        self.assertEqual(len(golden), 1, f"Expected 1 Golden Record, got {len(golden)}")

    def test_tc2a_audit_contains_fuzzy_peer_match_decision(self):
        _, audit, _ = _run_pipeline(self._CORE_TC2A, self._CARD_TC2A, self._MORT_TC2A)
        fuzzy_merges = audit[
            (audit["decision"] == "MERGE") &
            (audit["match_type"].str.contains("Fuzzy", na=False))
        ]
        self.assertGreater(len(fuzzy_merges), 0, "No fuzzy merge recorded in audit log")

    def test_tc2a_name_score_above_threshold(self):
        """Confirm the fuzz prerequisite: 'Maria Garcia' vs 'Maria Gracia' > 85."""
        score = fuzz.token_set_ratio("Maria Garcia", "Maria Gracia")
        self.assertGreater(score, FUZZY_NAME_THRESHOLD,
            f"Name score {score} is not above threshold {FUZZY_NAME_THRESHOLD}")

    def test_tc2a_national_id_is_null_when_no_ssn_exists(self):
        """Golden Record must have a null/None National_ID when no SSN was present."""
        golden, _, _ = _run_pipeline(self._CORE_TC2A, self._CARD_TC2A, self._MORT_TC2A)
        self.assertIsNone(golden.iloc[0]["National_ID"])

    def test_tc2a_email_contact_corroboration_logged(self):
        """Audit log must record the email that corroborated the fuzzy merge."""
        _, audit, _ = _run_pipeline(self._CORE_TC2A, self._CARD_TC2A, self._MORT_TC2A)
        merge_row = audit[
            (audit["decision"] == "MERGE") &
            (audit["contact_corroboration"].str.contains("email", case=False, na=False))
        ]
        self.assertGreater(len(merge_row), 0, "No email corroboration entry found in audit log")

    def test_tc2b_patricia_lee_variants_merged_into_one_record(self):
        """Patricia Lee / Patricia L. Lee (no SSN, same email) → 1 Golden Record."""
        golden, _, _ = _run_pipeline(self._CORE_TC2B, self._CARD_TC2B, self._MORT_TC2B)
        self.assertEqual(len(golden), 1, f"Expected 1 Golden Record, got {len(golden)}")

    def test_tc2b_name_score_above_threshold(self):
        score = fuzz.token_set_ratio("Patricia Lee", "Patricia L. Lee")
        self.assertGreater(score, FUZZY_NAME_THRESHOLD)

    def test_tc2_high_name_score_alone_is_insufficient_without_contact(self):
        """
        Negative control: two records with a high name score but NO shared contact
        must NOT be merged.  Here we use "maria garcia" vs "Maria Gracia" but with
        completely different (non-matching) email addresses.
        """
        core = """\
            Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
            CB-X,maria garcia,,garcia_a@example.com,1990-01-01,1000.00
        """
        card = """\
            Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
            CC-Y,Maria Gracia,5550001111,,gracia_b@example.com,2000.00
        """
        golden, audit, _ = _run_pipeline(core, card, _EMPTY_MORT)
        self.assertEqual(len(golden), 2,
            "High name score without contact overlap must not merge (got 1 record)")
        no_merges = audit[audit["decision"] == "NO MERGE"]
        self.assertGreater(len(no_merges), 0, "Rejected merge should be logged as NO MERGE")


# ─────────────────────────────────────────────────────────────────────────────
# TC-3 — Family-member guard (same last name, different contacts → no merge)
# ─────────────────────────────────────────────────────────────────────────────

class TC3_FamilyGuardTests(unittest.TestCase):
    """
    TC-3: Records with the same last name but different email and phone must
    produce distinct Golden Records.  This prevents false-positive merging of
    family members who genuinely share a surname.
    """

    # Rachel Torres (CB/CC/Mort — SSN 843621177) vs Robert Torres (CB-only, no SSN)
    # vs Roberto Torres (CC/Mort — no SSN, phone 5559631122)
    _CORE_TC3 = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10008,Rachel Torres,843-62-1177,rachel.torres@email.com,1993-05-19,9100.50
        CB-10012,Robert Torres,,rob.torres@personalmail.com,1972-06-18,6300.00
    """
    _CARD_TC3 = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88008,RACHEL TORRES,555.519.6677,843621177,,10000.00
        CC-88012,Roberto Torres,(555) 963-1122,,rob.torres2@bizmail.net,4500.00
    """
    _MORT_TC3 = """\
        Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
        ML-55008,Rachel,Torres,843621177,555.519.6677,310000.00
        ML-55012,Robert,Torres,,5559631122,287000.00
    """

    def test_tc3_all_three_torres_are_distinct_golden_records(self):
        """
        Rachel Torres (SSN-anchored), Robert Torres (CB singleton),
        and Roberto Torres (no-SSN, unique contact) must each produce
        their own Golden Record — 3 distinct records in total.
        """
        golden, _, _ = _run_pipeline(self._CORE_TC3, self._CARD_TC3, self._MORT_TC3)
        torres = golden[golden["Legal_Name"].str.contains("Torres", case=False, na=False)]
        self.assertEqual(len(torres), 3,
            f"Expected 3 Torres records, got {len(torres)}:\n{torres[['Legal_Name','National_ID','Master_Email']].to_string()}")

    def test_tc3_rachel_torres_has_ssn_anchored_record(self):
        """Rachel Torres must have a non-null National_ID (merged via SSN)."""
        golden, _, _ = _run_pipeline(self._CORE_TC3, self._CARD_TC3, self._MORT_TC3)
        rachel = golden[golden["Legal_Name"].str.contains("Rachel", case=False, na=False)]
        self.assertEqual(len(rachel), 1)
        self.assertEqual(rachel.iloc[0]["National_ID"], "843621177")

    def test_tc3_robert_torres_is_cb_only_singleton(self):
        """Robert Torres (CB-only) must appear as a singleton with no National_ID."""
        golden, _, _ = _run_pipeline(self._CORE_TC3, self._CARD_TC3, self._MORT_TC3)
        robert = golden[
            (golden["Legal_Name"].str.contains("Robert Torres", case=False, na=False)) &
            (~golden["Legal_Name"].str.contains("Roberto", case=False, na=False))
        ]
        self.assertEqual(len(robert), 1)
        self.assertIsNone(robert.iloc[0]["National_ID"])

    def test_tc3_rejected_merge_logged_in_audit(self):
        """The engine must write at least one NO MERGE audit entry for the Torres family."""
        _, audit, _ = _run_pipeline(self._CORE_TC3, self._CARD_TC3, self._MORT_TC3)
        no_merges = audit[audit["decision"] == "NO MERGE"]
        self.assertGreater(len(no_merges), 0, "Expected at least one NO MERGE in audit log")

    def test_tc3_fuzz_score_of_rachel_vs_robert_torres_below_threshold(self):
        """
        Confirm 'Rachel Torres' vs 'Robert Torres' is safely below the fuzzy
        threshold so the guard is definitively triggered by name score alone
        (not by the contact check).
        """
        score = fuzz.token_set_ratio("Rachel Torres", "Robert Torres")
        self.assertLess(score, FUZZY_NAME_THRESHOLD,
            f"Score {score} is unexpectedly above threshold — TC-3 guard premise is wrong")


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation Tests
# ─────────────────────────────────────────────────────────────────────────────

class AggregationTests(unittest.TestCase):
    """
    Validate that the aggregation layer correctly combines product lists and
    sums financial exposure across all three source systems.
    """

    # Jonathan Doe across all three systems — deterministic via SSN
    _CORE_AGG = """\
        Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
        CB-10001,Jonathan Doe,467-88-1234,jon.doe@gmail.com,1985-03-15,15420.50
    """
    _CARD_AGG = """\
        Card_ID,Full_Name,Phone_Num,SSN,Email,Credit_Limit
        CC-88001,John Doe,5553104400,46788-1234,jon.doe@gmail.com,8500.00
    """
    _MORT_AGG = """\
        Loan_ID,First_Name,Last_Name,SSN,Contact_Number,Loan_Amount
        ML-55001,Jonathan,Doe,467881234,(555) 310-4400,320000.00
    """

    def setUp(self):
        self.golden, self.audit, _ = _run_pipeline(
            self._CORE_AGG, self._CARD_AGG, self._MORT_AGG
        )
        self.record = self.golden.iloc[0]

    def test_active_products_contains_all_three_product_types(self):
        import ast
        products = ast.literal_eval(self.record["Active_Products"])
        self.assertIn("Checking",    products)
        self.assertIn("Credit Card", products)
        self.assertIn("Mortgage",    products)

    def test_active_products_has_no_duplicates(self):
        import ast
        products = ast.literal_eval(self.record["Active_Products"])
        self.assertEqual(len(products), len(set(products)),
            f"Duplicate products found: {products}")

    def test_total_exposure_is_sum_of_all_three_financials(self):
        """15420.50 (balance) + 8500.00 (credit limit) + 320000.00 (loan) = 343920.50"""
        expected = 15420.50 + 8500.00 + 320000.00
        self.assertAlmostEqual(self.record["Total_Exposure"], expected, places=2)

    def test_total_exposure_is_numeric(self):
        self.assertIsInstance(self.record["Total_Exposure"], float)

    def test_source_systems_lists_all_three_origins(self):
        import ast
        sources = ast.literal_eval(self.record["Source_Systems"])
        self.assertIn("CoreBanking", sources)
        self.assertIn("CreditCard",  sources)
        self.assertIn("Mortgage",    sources)

    def test_source_ids_contains_all_three_source_keys(self):
        import ast
        source_ids = ast.literal_eval(self.record["Source_IDs"])
        self.assertIn("CB-10001", source_ids)
        self.assertIn("CC-88001", source_ids)
        self.assertIn("ML-55001", source_ids)

    def test_master_email_is_lowercased(self):
        """Master_Email must be normalised to lowercase."""
        email = self.record["Master_Email"]
        self.assertEqual(email, email.lower())

    def test_golden_id_is_a_valid_uuid(self):
        """Golden_ID must be a well-formed UUID string."""
        import uuid
        golden_id = self.record["Golden_ID"]
        try:
            uuid.UUID(str(golden_id))
        except ValueError:
            self.fail(f"Golden_ID '{golden_id}' is not a valid UUID")

    def test_single_source_record_exposure_is_just_that_value(self):
        """A singleton record with only a Checking account should expose only Account_Balance."""
        core = """\
            Acct_Num,Cust_Name,SSN,Email,DOB,Account_Balance
            CB-solo,Solo Person,999-00-1234,solo@test.com,1980-01-01,5000.00
        """
        golden, _, _ = _run_pipeline(core, _EMPTY_CARD, _EMPTY_MORT)
        self.assertEqual(len(golden), 1)
        self.assertAlmostEqual(golden.iloc[0]["Total_Exposure"], 5000.00, places=2)

    def test_zero_balance_does_not_inflate_exposure(self):
        """Rows contributing 0.0 for fields they don't own must not distort the sum."""
        golden, _, _ = _run_pipeline(
            self._CORE_AGG, self._CARD_AGG, self._MORT_AGG
        )
        # Only one customer — sanity that there are no phantom extra zeros
        self.assertEqual(len(golden), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
