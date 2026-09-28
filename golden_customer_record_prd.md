# Product Requirements Document (PRD): Golden Customer Record ETL Engine

## 1. Product Overview
**Product Name:** Golden Customer Record Engine
**Problem Statement:** A bank’s customer data is heavily fragmented across distinct siloed systems (Core Banking, Credit Card, and Mortgage). Each system utilizes disparate field names, ID formats, and record structures. This fragmentation prevents Data Governance, KYC/AML, and Marketing teams from obtaining a singular, reliable view of a customer, leading to duplicate outreach, inaccurate risk aggregation, and compliance blind spots.
**Solution:** A lightweight, automated Extract, Transform, and Load (ETL) pipeline generated via IBM Bob. The solution will ingest mock data extracts from the three siloed systems, map them to a canonical schema, apply fuzzy matching and ID reconciliation to deduplicate records, and output a clean, unified "Golden Record" dataset.

---

## 2. Target Audience & User Personas
*   **Data Engineering Teams:** Seeking reusable blueprint pipelines that automate manual data mapping and schema consolidation.
*   **Data Governance & Compliance Teams:** Requiring a single source of truth to accurately conduct KYC/AML screening without duplicate-customer noise.
*   **Risk Assessment Officers:** Needing an aggregated view of a customer's total exposure across all banking products (checking, credit, mortgages).

---

## 3. Business Requirements
*   **Automated Schema Mapping:** Drastically reduce the weeks of manual engineering time typically required for Master Data Management (MDM) reconciliation by utilizing generative AI (IBM Bob) to build the data mappings.
*   **Improved Compliance Accuracy:** Generate a single, deduplicated profile per individual to reduce false positives/negatives in regulatory and security screenings.
*   **Enterprise Viability (NoSlop):** The solution must directly address a high-stakes, real-world corporate challenge (data fragmentation), demonstrating clear sustainability and potential adoption. 
*   **Rapid Prototyping:** The end-to-end prototype must be built, tested, and pushed to a public GitHub repository within a strict 40-minute timeframe.

---

## 4. Functional Requirements
*   **Data Ingestion:** The script must successfully read data from three distinct CSV files representing Core Banking, Credit Card, and Mortgage systems.
*   **Data Normalization:** The system must standardize formatting variations (e.g., converting all text to title case, stripping dashes from SSNs/IDs, standardizing phone number formats).
*   **Fuzzy Matching & Deduplication:** 
    *   The system must match records based on a primary identifier (e.g., National ID or normalized SSN).
    *   Where primary IDs are missing or mismatched, the system must employ a fuzzy matching fallback using a combination of `Name`, `Date of Birth (DOB)`, and `Contact Information` (email/phone) to confidently link records.
*   **Data Merging:** Upon identifying a match across systems, the pipeline must merge the active products and risk profiles into a single comprehensive row rather than overwriting data.
*   **Output Generation:** The script must export a final, consolidated `.csv` or `.json` file representing the canonical "Golden Records."

---

## 5. Technical Requirements
*   **Core Technology Stack:** Python 3.x, utilizing standard data manipulation libraries (e.g., `pandas` for tabular data, `fuzzywuzzy` or `thefuzz` for string matching).
*   **AI Integration:** IBM Bob must be actively utilized in the development process to generate the ETL code, schema models, and fuzzy matching logic. The methodology of this integration must be thoroughly documented in the project's GitHub README.
*   **Version Control & Submission:** All application code, mock datasets, and documentation must be pushed to a public GitHub repository.
*   **Test Data Specifications:**
    *   Three mock `.csv` files (20-50 rows each).
    *   Data must be deliberately seeded with formatting inconsistencies, missing fields, and slight typographical errors in names to validate the fuzzy matching logic.
*   **Performance:** The ETL script must execute and process the mock datasets in under 10 seconds locally to ensure a smooth, live demonstration.

---

## 6. Data Architecture & Canonical Schema

**Input Sources (Mock Data):**
1.  `core_banking_extract.csv` (Keys: Acct_Num, Cust_Name, Email)
2.  `credit_card_extract.csv` (Keys: Card_ID, Full_Name, Phone_Num)
3.  `mortgage_extract.csv` (Keys: Loan_ID, First_Name, Last_Name, SSN)

**Target Canonical Model (The Golden Record):**

| Field Name | Data Type | Description / Transformation Rule |
| :--- | :--- | :--- |
| `Golden_ID` | String (UUID) | Unique identifier generated for the merged profile. |
| `Legal_Name` | String | Standardized Title Case name. |
| `Master_Email` | String | Primary email address (prioritized from Core Banking). |
| `Master_Phone` | String | Standardized E.164 phone number. |
| `National_ID` | String | Normalized identification number (dashes removed). |
| `Active_Products` | Array/List | Combined list of products (e.g., ["Checking", "Visa", "Mortgage"]). |
| `Source_Systems` | Array/List | Lineage tracking showing where the data originated. |

---

## 7. Out of Scope
*   Live API connections to real banking mainframes or CRM systems.
*   Handling of massive, production-scale datasets (millions of rows).
*   A graphical user interface (GUI) or web frontend; this is strictly a backend data pipeline demonstrated via a Command Line Interface (CLI) and file outputs.