# Technical Requirements Document (TRD)

## 1. Environment & Tech Stack
* **Language:** Python 3.10+
* **Core Libraries:**
  * `pandas`: For ingesting CSVs, DataFrame manipulation, and data exporting.
  * `thefuzz` (or `fuzzywuzzy`): For string comparison and Levenshtein distance calculations (Name matching).
  * `uuid`: For generating unique Golden IDs.
  * `re` (Standard Regex Library): For cleaning and normalizing phone numbers and SSNs.
* **Execution Environment:** Local Command Line Interface (CLI).

## 2. IBM Bob Integration Strategy
To fulfill the hackathon judging criteria, IBM Bob will be used for the following technical tasks:
1. **Mock Data Generation:** Prompting Bob to generate the 3 distinct CSV files with deliberate errors (e.g., "Generate 20 rows of credit card data with 3 rows representing the same person as the core banking data, but with a slight typo in the name").
2. **Algorithm Generation:** Prompting Bob to write the specific Python function that calculates fuzzy match scores between two pandas DataFrame rows.
3. **Refactoring:** Passing the initial working script back to Bob to optimize Pandas `.apply()` functions for better performance.

## 3. Execution Flow (The ETL Pipeline)
1. **Extract:** 
   * Load `core.csv`, `credit.csv`, and `mortgage.csv` into three separate Pandas DataFrames.
2. **Transform (Phase 1 - Normalize):**
   * Convert all names to lowercase/title case.
   * Strip all non-numeric characters from SSNs and Phone Numbers using RegEx.
3. **Transform (Phase 2 - Deduplicate):**
   * Combine all records into a single staging DataFrame.
   * Group by `Normalized_SSN`. 
   * For records without an SSN, run a cross-join or paired comparison using `thefuzz.ratio()` on the Name field. If the score is > 85 AND the phone/email matches, assign them the same temporary grouping ID.
4. **Transform (Phase 3 - Merge/Aggregate):**
   * Aggregate the grouped records. Create a new UUID for each unique group.
   * Consolidate emails/phones (take the first non-null value).
   * Append product names into a Python list `['Checking', 'Mortgage']`.
5. **Load:**
   * Write the resulting DataFrame to `golden_records_output.csv`.

## 4. Testing Criteria
* **Test Case 1 (Exact Match):** Two records with identical SSNs but different name spellings must merge.
* **Test Case 2 (Fuzzy Match):** Two records with NO SSN, but identical emails and >85% name match must merge.
* **Test Case 3 (Negative Match):** Two records with the same last name but different emails/phones must NOT merge (avoids family member false-positives).
* **Performance:** The script must run in under 5 seconds for a dataset of 100 mock rows.