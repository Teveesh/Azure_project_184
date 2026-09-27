# Azure Partition Key Design Study

A local, self-contained Streamlit dashboard for exploring and comparing
candidate **partition keys** before designing a table in **Azure Table
Storage** or a container in **Azure Cosmos DB**.

> **Note:** This is a design-study / prototype tool built for learning and
> demonstration purposes. It is **not** an official Azure recommendation
> engine. The local analysis works completely offline. An **optional**
> Azure Cosmos DB "Cloud Validation" section can push the sample data to
> your own Cosmos DB account, but only if you configure credentials and
> click the buttons yourself — nothing connects to Azure automatically.

---

## 1. Problem Statement

Choosing a partition key is one of the most important — and hardest to
reverse — decisions when designing a table in Azure Table Storage or a
container in Azure Cosmos DB. A poorly chosen partition key can lead to:

- **Hot partitions**, where a small number of partition values absorb most
  of the read/write traffic.
- **Uneven data distribution**, where a few partitions grow far larger than
  the rest.
- **Excessive fragmentation**, where nearly every record lives in its own
  tiny partition, hurting query efficiency.

Developers often have to make this decision *before* they have real
production data to test against, which makes it easy to get wrong.

## 2. Objective

Give developers a simple, local tool to load a representative dataset,
try out several candidate partition keys, and immediately see:

- How many unique partitions each key would create.
- How records would be distributed across those partitions.
- Whether the key shows signs of low cardinality, uneven distribution, or
  potential hot-partition behavior — using transparent, explainable
  heuristics rather than a black-box score.

## 3. Technologies Used

- **Python 3**
- **Streamlit** — interactive dashboard UI
- **pandas** — data loading and partition statistics
- **Plotly** — bar charts and histograms
- **azure-cosmos** (optional) — only used by the "Cloud Validation" section
  to talk to your own Azure Cosmos DB account, and only when you click one
  of its buttons

No `.NET`, no `C#`, and no automatic Azure resource creation or deployment
are used anywhere in this project. The core dashboard needs no Azure
account at all.

## 4. How the System Works

1. `sample_data.csv` contains ~1,000 synthetic e-commerce orders with
   columns intentionally designed to show different partitioning behavior
   (`CustomerID`, `Region`, `Category`, `OrderID`).
2. `app.py` loads the CSV with pandas and, for a selected column, computes:
   - Total records, unique partition count, average / median / largest /
     smallest partition size.
   - A partition imbalance ratio (largest partition vs. average).
   - The share of records held by the single largest partition and the
     top 3 partitions.
   - The share of partitions that contain only a single record.
3. These numbers are run through a small set of transparent heuristic
   rules (see below) to flag cardinality, distribution, and hot-partition
   risk — all computed live from the data, nothing is hardcoded.
4. Results are shown as metric cards, bar charts / histograms, a full
   comparison table across all four candidate keys, and a written design
   summary.

### Risk Heuristics (design-study only, not official Azure guidance)

| Flag | Trigger (approximate) |
|---|---|
| Very High Cardinality | Nearly every record has its own partition value |
| Low Cardinality | Very few unique partition values exist overall |
| Uneven Distribution | Largest partition is much bigger than the average |
| Potential Hot Partition | A small number of values hold a large share of all records |
| Relatively Balanced Distribution | None of the above conditions are triggered |

## 5. Features

- Sidebar dataset selector and partition-key dropdown (`CustomerID`,
  `Region`, `Category`, `OrderID`).
- "Analyze Partition Key" action button.
- Live-calculated metric cards (no hardcoded numbers).
- Adaptive visualizations: a per-partition bar chart for low/moderate
  cardinality keys, and an aggregated histogram for very high-cardinality
  keys (e.g. `OrderID`) so the chart stays readable.
- Top 10 largest partitions chart.
- Full **Partition Key Comparison** table across all four candidate keys.
- Written **Design Analysis** section per selected key.
- Expandable **How This Relates to Azure** section covering Azure Table
  Storage and Azure Cosmos DB concepts.
- **Partition Key Design Summary** section at the bottom of the page.
- Optional **Azure Cosmos DB — Cloud Validation** section (see below) to
  test a selected key against a real Cosmos DB account, entirely opt-in.

## 6. Azure Table Storage Relationship

- `PartitionKey` groups entities together within the same partition.
- `RowKey` uniquely identifies an entity *within* a partition.
- The partition-key choice directly affects data organization and query
  efficiency — queries that specify both `PartitionKey` and `RowKey` are
  the most efficient.
- Good design considers both data distribution and expected query
  patterns.

## 7. Azure Cosmos DB Relationship

- The partition key determines how items are logically grouped and
  physically distributed across the underlying infrastructure.
- A good partition key should provide useful, even distribution of
  storage and throughput.
- Query patterns should also be considered when choosing a partition key,
  since cross-partition queries are more expensive.
- Poor distribution — a few values holding most of the data or traffic —
  can contribute to hot partitions.

## 8. Azure Cosmos DB Integration (Optional Cloud Validation)

The dashboard includes an **optional** "Azure Cosmos DB — Cloud Validation"
section. It lets you push the sample dataset into your own Azure Cosmos DB
account to confirm that a candidate partition key can actually be
represented and stored in the cloud.

**This is entirely opt-in:**

- The app starts and works fully without any Azure account, credentials,
  or the `azure-cosmos` package installed.
- No Azure resource (database, container, or item) is ever created
  automatically. Every Azure operation only runs when you click one of
  the three buttons in that section.
- No throughput/RU settings are changed automatically — the container is
  created using your Cosmos account's own defaults.

### Required environment variables

| Variable | Purpose |
|---|---|
| `COSMOS_ENDPOINT` | Your Cosmos DB account URI, e.g. `https://<account>.documents.azure.com:443/` |
| `COSMOS_KEY` | Your Cosmos DB primary or secondary key |
| `COSMOS_DATABASE` | Name of the database to create/use, e.g. `OrdersDB` |
| `COSMOS_CONTAINER` | Name of the container to create/use, e.g. `Orders` |

A template is provided in `.env.example` (placeholder values only — **never
commit real credentials**). Either:

- Copy it to `.env` and load the values into your shell yourself, or
- Set the four variables directly as real environment variables before
  running Streamlit, e.g. in PowerShell:

```powershell
$env:COSMOS_ENDPOINT = "https://<your-account>.documents.azure.com:443/"
$env:COSMOS_KEY = "<your-key>"
$env:COSMOS_DATABASE = "OrdersDB"
$env:COSMOS_CONTAINER = "Orders"
```

`.env` is already listed in `.gitignore`, so it will not be committed if
you choose that approach.

### How to install the Azure dependency

`azure-cosmos` is already listed in `requirements.txt`. Installing the
project's normal requirements (see "How to Install" below) installs it too:

```powershell
py -m pip install -r requirements.txt
```

### Using the Cloud Validation section

1. Open the app and scroll to **"Azure Cosmos DB — Cloud Validation"**.
2. Choose one of the four candidate keys (`CustomerID`, `Region`,
   `Category`, `OrderID`) — this determines the Cosmos DB partition key
   path (e.g. `/CustomerID`).
3. Click **"Connect / Test Azure"** to verify your credentials can reach
   the Cosmos DB account (no data is written).
4. Click **"Create / Verify Container"** to create the database/container
   if they don't already exist, using the selected key as the partition
   key path. Cosmos DB partition keys are immutable — if the container
   already exists with a different partition key, it is left unchanged.
5. Click **"Upload Sample Data"** to upload every row of `sample_data.csv`
   as a Cosmos DB document (each row becomes one document with a unique
   `id`, and the selected column as its Cosmos partition key value). The
   app reports records attempted, records successfully uploaded, and any
   errors.
6. Open **Azure Cosmos DB Data Explorer** in the Azure Portal to inspect
   the uploaded documents.

### Cloud validation limitations

> Cloud validation confirms that the selected partition-key design can be
> represented and tested in Azure Cosmos DB. It does not guarantee
> production performance.

- It does not measure real request-unit (RU) cost, latency, or throughput
  under load.
- It uses the sample dataset only (~1,000 rows), not production-scale data
  or traffic.
- The local heuristic analysis earlier in the dashboard remains the
  primary design-study tool; the cloud step is a secondary, hands-on check.

### Security notes

- **Never commit real Azure credentials.** `.env` is git-ignored;
  `.env.example` contains placeholder values only.
- Credentials are read from environment variables at runtime and are
  never hardcoded in `app.py`.
- If credentials are missing, invalid, or Azure is unreachable, the app
  shows a clear Streamlit message instead of crashing or showing a raw
  traceback.

## 9. How to Install

```powershell
py -m pip install -r requirements.txt
```

## 10. How to Run

```powershell
py -m streamlit run app.py
```

Then open the local URL Streamlit prints in your terminal (typically
`http://localhost:8501`). The dashboard works immediately with no Azure
setup; the Cloud Validation section simply stays informational until you
configure the environment variables in section 8.

## 11. Example Output

For the sample dataset (~1,000 orders):

| Partition Key | Unique Partitions | Average Size | Largest Partition | Status |
|---|---:|---:|---:|---|
| CustomerID | ~500+ | ~2 | ~9 | Very High Cardinality |
| Region | 4 | 250 | ~540 | Low Cardinality, Potential Hot Partition |
| Category | 8 | 125 | ~230 | Moderate, generally balanced |
| OrderID | 1000 | 1 | 1 | Very High Cardinality |

*(Exact numbers depend on the randomly generated sample data and will be
recalculated live when you run the app.)*

## 12. Limitations

- Uses a single synthetic sample dataset, not real production traffic.
- Risk thresholds are simple, fixed heuristics chosen for teaching
  purposes — they are **not** official Microsoft/Azure recommendations
  and do not model request-unit (RU) cost, storage limits, or real
  request patterns.
- Does not account for query patterns, only static data distribution.
- The local analysis does not connect to, provision, or measure any real
  Azure resource. The separate, optional Cloud Validation section does
  connect to Azure, but only when you supply your own credentials and
  click its buttons — see section 8 for its own limitations.

## 13. Future Improvements

- Allow uploading a custom CSV to analyze real or anonymized datasets.
- Support composite/synthetic partition keys (e.g. combining two columns).
- Model estimated Request Unit (RU) cost implications for Cosmos DB.
- Add time-based analysis (e.g. partition growth over time).
- Export the comparison table and charts as a shareable report.
- Surface basic Cosmos DB RU consumption after an upload, for a rough
  cost-awareness signal (still not a guarantee of production cost).

---

*Azure Partition Key Design Study — a local prototype for exploring
partition-key trade-offs. Not an official Azure recommendation engine.*
