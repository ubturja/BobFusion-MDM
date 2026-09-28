# System Architecture

Because this is a rapid hackathon prototype, the architecture relies on local file processing and a monolithic Python script. However, it is designed to mimic the data flow of a production-grade enterprise ETL pipeline.

## Architecture Flow Diagram

```mermaid
graph TD
    subgraph Data Sources (Mock Systems)
        A[Core Banking CSV]
        B[Credit Card CSV]
        C[Mortgage CSV]
    end

    subgraph Data Processing Pipeline (Python Engine)
        D[Ingestion Layer <br> Pandas DataFrames]
        E[Normalization Layer <br> RegEx & Formatting]
        F[Resolution Engine <br> Exact Match on ID]
        G[Fuzzy Logic Engine <br> thefuzz String Matching]
        H[Aggregation Layer <br> Merge & UUID Generation]
    end

    subgraph Output
        I[(Golden Record Dataset <br> Output CSV/JSON)]
    end

    A -->|Read| D
    B -->|Read| D
    C -->|Read| D
    D --> E
    E --> F
    F -->|SSN Found| H
    F -->|SSN Missing/Null| G
    G -->|Match > 85%| H
    G -->|Match < 85%| H
    H -->|Export| I
```

## Component Breakdown

1. **Data Sources (Siloed Context):** Represents legacy systems. In a production environment, these would be direct API endpoints or connections to SQL Server/Oracle databases. For the prototype, these are local static files.
2. **Ingestion Layer:** The entry point of the Python script. Handles file I/O operations and initial data type casting (e.g., ensuring dates are treated as dates, not strings).
3. **Normalization Layer:** Cleanses the data to ensure apples-to-apples comparisons. (e.g., standardizing `(555) 123-4567` and `555.123.4567` to `5551234567`).
4. **Resolution & Fuzzy Logic Engines:** The core intelligence of the application. It acts as a routing system: if a hard identifier (SSN) exists, it routes to Exact Match. If not, it routes to the NLP/Fuzzy logic layer to make a probabilistic match.
5. **Output (The Single Source of Truth):** The finalized dataset. In a real-world scenario, this would be pushed to a Master Data Management (MDM) platform or a Cloud Data Warehouse (like Snowflake) for downstream consumption by marketing and compliance teams.