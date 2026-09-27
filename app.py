"""
Azure Partition Key Design Study
--------------------------------
A local, self-contained Streamlit dashboard that helps developers compare
candidate partition keys (for Azure Table Storage / Azure Cosmos DB style
designs) BEFORE committing to a schema.

This is a design-study / prototype tool only. It does not connect to Azure,
does not use the Azure SDK, and all thresholds used for risk analysis are
simple, transparent heuristics -- NOT official Microsoft/Azure guidance.
"""

import os

import pandas as pd
import plotly.express as px
import streamlit as st

# Azure Cosmos DB SDK is optional: the whole app must keep working, with the
# local analysis fully intact, even if this package is not installed or no
# Azure credentials are configured.
try:
    from azure.cosmos import CosmosClient, PartitionKey
    from azure.cosmos import exceptions as cosmos_exceptions

    AZURE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when azure-cosmos isn't installed
    AZURE_SDK_AVAILABLE = False

# --------------------------------------------------------------------------
# Page configuration
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="Azure Partition Key Design Study",
    page_icon="🗂️",
    layout="wide",
)

CANDIDATE_KEYS = ["CustomerID", "Region", "Category", "OrderID"]
DATA_PATH = "sample_data.csv"


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df


# --------------------------------------------------------------------------
# Core analysis functions (all values are calculated dynamically -- nothing
# below is hardcoded per-column; the same functions run for any key).
# --------------------------------------------------------------------------
def compute_partition_stats(df: pd.DataFrame, key: str) -> dict:
    counts = df[key].value_counts()

    total_records = int(len(df))
    unique_partitions = int(counts.shape[0])
    average_size = float(counts.mean())
    largest_partition = int(counts.max())
    smallest_partition = int(counts.min())
    median_size = float(counts.median())

    # Imbalance: how much bigger the largest partition is versus the average.
    imbalance_ratio = float(largest_partition / average_size) if average_size > 0 else 0.0

    # Share of records held by the top partition and top-3 partitions.
    top1_share = float(counts.iloc[0] / total_records) if total_records > 0 else 0.0
    top3_share = float(counts.iloc[:3].sum() / total_records) if total_records > 0 else 0.0

    # Share of partitions that contain exactly one record (a proxy for
    # "essentially unique" keys such as an order ID).
    singleton_share = float((counts == 1).sum() / unique_partitions) if unique_partitions > 0 else 0.0

    # Overall cardinality ratio: unique partitions relative to total records.
    cardinality_ratio = float(unique_partitions / total_records) if total_records > 0 else 0.0

    return {
        "key": key,
        "counts": counts,
        "total_records": total_records,
        "unique_partitions": unique_partitions,
        "average_size": average_size,
        "largest_partition": largest_partition,
        "smallest_partition": smallest_partition,
        "median_size": median_size,
        "imbalance_ratio": imbalance_ratio,
        "top1_share": top1_share,
        "top3_share": top3_share,
        "singleton_share": singleton_share,
        "cardinality_ratio": cardinality_ratio,
    }


def classify_status(stats: dict) -> dict:
    """
    Transparent heuristic classification. Every status below is derived
    directly from the statistics computed in compute_partition_stats() --
    nothing here is hardcoded per partition key.

    These thresholds are simple design-study heuristics chosen for this
    prototype -- they are NOT official Microsoft/Azure recommendations.
    """
    # ---- Cardinality status (single, unambiguous label) -------------------
    if stats["cardinality_ratio"] >= 0.9 or stats["singleton_share"] >= 0.9:
        cardinality_status = "Very High"
    elif stats["cardinality_ratio"] >= 0.3:
        cardinality_status = "High"
    elif stats["unique_partitions"] <= 10 or stats["cardinality_ratio"] <= 0.02:
        cardinality_status = "Low"
    else:
        cardinality_status = "Moderate"

    # ---- Distribution status (single, unambiguous label) -------------------
    # Driven by the same imbalance / concentration numbers shown on the
    # metric cards, so the summary can never disagree with the metrics.
    if stats["top1_share"] >= 0.30 or stats["imbalance_ratio"] >= 5:
        distribution_status = "Uneven"
    elif stats["top1_share"] >= 0.15 or stats["imbalance_ratio"] >= 2:
        distribution_status = "Moderately Uneven"
    else:
        distribution_status = "Balanced"

    # ---- Hot partition risk -------------------------------------------------
    # High risk: a small number of values absorb a large share of records,
    # or so few unique values exist that concentration is unavoidable.
    if stats["top1_share"] >= 0.30 or stats["top3_share"] >= 0.50 or cardinality_status == "Low":
        risk = "High"
    elif distribution_status == "Moderately Uneven" or cardinality_status == "Very High":
        risk = "Medium"
    else:
        risk = "Low"

    # ---- Human-readable flags (used for the short badges under the key) ---
    flags = []
    if cardinality_status in ("Very High", "Low"):
        flags.append(f"{cardinality_status} Cardinality")
    if distribution_status != "Balanced":
        flags.append(distribution_status + " Distribution")
    if stats["top1_share"] >= 0.30 or stats["top3_share"] >= 0.50:
        flags.append("Potential Hot Partition")
    if not flags:
        flags.append("Relatively Balanced Distribution")

    return {
        "flags": flags,
        "cardinality_status": cardinality_status,
        "distribution_status": distribution_status,
        "risk": risk,
    }


def explain_key_behavior(stats: dict, classification: dict, key: str) -> str:
    """
    Dynamically builds a 'why this key behaves this way' paragraph purely
    from the calculated statistics for the given key. No per-key text is
    hardcoded -- the same template runs for CustomerID, Region, Category,
    OrderID, or any future column.
    """
    cardinality_status = classification["cardinality_status"]
    distribution_status = classification["distribution_status"]

    cardinality_sentence = {
        "Very High": (
            f"`{key}` has very high cardinality: {stats['unique_partitions']:,} unique values "
            f"across {stats['total_records']:,} records, so most partitions hold only one "
            "or two records."
        ),
        "High": (
            f"`{key}` has high cardinality: {stats['unique_partitions']:,} unique values "
            f"across {stats['total_records']:,} records, giving a fairly fine-grained split "
            "of the data."
        ),
        "Moderate": (
            f"`{key}` has moderate cardinality: {stats['unique_partitions']:,} unique values "
            f"across {stats['total_records']:,} records."
        ),
        "Low": (
            f"`{key}` has low cardinality: only {stats['unique_partitions']:,} unique values "
            f"cover all {stats['total_records']:,} records."
        ),
    }[cardinality_status]

    distribution_sentence = {
        "Uneven": (
            f"The largest partition holds {stats['largest_partition']:,} records "
            f"({stats['top1_share'] * 100:.1f}% of the dataset), which is "
            f"{stats['imbalance_ratio']:.1f}x the average partition size "
            f"({stats['average_size']:.2f}). This is an uneven distribution."
        ),
        "Moderately Uneven": (
            f"The largest partition holds {stats['largest_partition']:,} records "
            f"({stats['top1_share'] * 100:.1f}% of the dataset), about "
            f"{stats['imbalance_ratio']:.1f}x the average partition size "
            f"({stats['average_size']:.2f}). This is a moderately uneven distribution."
        ),
        "Balanced": (
            f"The largest partition holds {stats['largest_partition']:,} records and the "
            f"smallest holds {stats['smallest_partition']:,}, close to the average of "
            f"{stats['average_size']:.2f}. This is a relatively balanced distribution."
        ),
    }[distribution_status]

    concentration_sentence = (
        f"The top 3 partitions together hold {stats['top3_share'] * 100:.1f}% of all records, "
        f"and {stats['smallest_partition']:,} record(s) is the smallest partition size observed."
    )

    risk_sentence = (
        f"Based on this concentration and distribution, this prototype flags a "
        f"**{classification['risk']}** potential hot-partition risk for `{key}`."
    )

    return " ".join([cardinality_sentence, distribution_sentence, concentration_sentence, risk_sentence])


def prototype_design_insight(stats: dict, classification: dict, key: str) -> str:
    """
    Dynamically generated 'Prototype Design Insight' paragraph -- an
    analytical observation, not an official Azure recommendation.
    """
    cardinality_status = classification["cardinality_status"]
    distribution_status = classification["distribution_status"]
    risk = classification["risk"]

    observations = [f"{cardinality_status} cardinality", f"{distribution_status.lower()} distribution"]
    if stats["top1_share"] >= 0.30 or stats["top3_share"] >= 0.50:
        observations.append("high concentration in a small number of partitions")
    elif distribution_status == "Balanced" and cardinality_status in ("Moderate", "High"):
        observations.append("low concentration")

    observation_text = ", ".join(observations)

    if risk == "High":
        suggestion = (
            "Consider whether a more distributed partition-key strategy, or a composite key, "
            "would better spread the workload before deploying."
        )
    elif risk == "Medium":
        suggestion = (
            "Consider validating this key against expected query and write patterns before "
            "relying on it in production."
        )
    else:
        suggestion = (
            "This key appears reasonable for this sample dataset, but should still be validated "
            "against real access patterns."
        )

    return (
        f"Prototype insight: `{key}` shows {observation_text}. {suggestion}"
    )


# --------------------------------------------------------------------------
# Azure Cosmos DB integration helpers (all OPTIONAL -- the local analysis
# above never depends on any of this). No Azure operation runs unless the
# user explicitly clicks a button in the "Cloud Validation" section below.
# --------------------------------------------------------------------------
COSMOS_ENV_VARS = {
    "endpoint": "COSMOS_ENDPOINT",
    "key": "COSMOS_KEY",
    "database": "COSMOS_DATABASE",
    "container": "COSMOS_CONTAINER",
}


def get_cosmos_config() -> dict:
    """Read Azure Cosmos DB settings from environment variables only.
    Never hardcode credentials here."""
    return {name: os.environ.get(env_var, "") for name, env_var in COSMOS_ENV_VARS.items()}


def cosmos_config_missing(config: dict) -> list:
    """Return the list of env var names that are not set."""
    return [env_var for name, env_var in COSMOS_ENV_VARS.items() if not config.get(name)]


def test_azure_connection(config: dict):
    """Lightweight connectivity check. Returns (success: bool, message: str)."""
    if not AZURE_SDK_AVAILABLE:
        return False, (
            "The `azure-cosmos` package is not installed. Run "
            "`py -m pip install -r requirements.txt` and try again."
        )
    missing = cosmos_config_missing(config)
    if missing:
        return False, f"Missing environment variable(s): {', '.join(missing)}."
    try:
        client = CosmosClient(config["endpoint"], credential=config["key"])
        # A single, bounded request just to confirm the account is reachable
        # and the key is valid -- no resources are created here.
        list(client.list_databases())
        return True, "Connected to the Azure Cosmos DB account successfully."
    except cosmos_exceptions.CosmosHttpResponseError as exc:
        return False, f"Azure rejected the request (HTTP {exc.status_code}). Check COSMOS_ENDPOINT and COSMOS_KEY."
    except Exception as exc:  # network errors, timeouts, DNS failures, etc.
        return False, f"Could not reach Azure Cosmos DB: {exc}"


def create_or_verify_container(config: dict, partition_key_field: str):
    """Create the database/container only if they don't already exist.
    Does not set or change throughput -- uses the account's own defaults."""
    if not AZURE_SDK_AVAILABLE:
        return False, "The `azure-cosmos` package is not installed."
    missing = cosmos_config_missing(config)
    if missing:
        return False, f"Missing environment variable(s): {', '.join(missing)}."
    try:
        client = CosmosClient(config["endpoint"], credential=config["key"])
        database = client.create_database_if_not_exists(id=config["database"])
        database.create_container_if_not_exists(
            id=config["container"],
            partition_key=PartitionKey(path=f"/{partition_key_field}"),
        )
        return True, (
            f"Database `{config['database']}` and container `{config['container']}` are ready "
            f"(partition key path `/{partition_key_field}`). If the container already existed with "
            "a different partition key, its partition key was NOT changed -- Cosmos DB partition "
            "keys are immutable after creation."
        )
    except cosmos_exceptions.CosmosHttpResponseError as exc:
        return False, f"Azure rejected the request while creating/verifying the container (HTTP {exc.status_code})."
    except Exception as exc:
        return False, f"Could not create or verify the container: {exc}"


def upload_dataframe_to_cosmos(config: dict, df: pd.DataFrame, partition_key_field: str) -> dict:
    """Uploads each CSV row as one Cosmos DB document (upsert, so duplicate
    ids overwrite instead of erroring). Never raises -- always returns a
    result dict so the app cannot crash if Azure is unavailable mid-upload."""
    result = {"attempted": 0, "succeeded": 0, "errors": []}

    if not AZURE_SDK_AVAILABLE:
        result["errors"].append("The `azure-cosmos` package is not installed.")
        return result

    missing = cosmos_config_missing(config)
    if missing:
        result["errors"].append(f"Missing environment variable(s): {', '.join(missing)}.")
        return result

    try:
        client = CosmosClient(config["endpoint"], credential=config["key"])
        container = client.get_database_client(config["database"]).get_container_client(config["container"])
    except Exception as exc:
        result["errors"].append(f"Could not access container '{config['container']}': {exc}")
        return result

    records = df.to_dict(orient="records")
    result["attempted"] = len(records)
    seen_ids = set()

    for i, record in enumerate(records):
        # Preserve existing CSV columns, converting numpy scalars to plain
        # Python types so the document is JSON-serializable.
        doc = {str(k): (v.item() if hasattr(v, "item") else v) for k, v in record.items()}

        # Ensure a unique "id" field. OrderID is unique in this dataset, but
        # fall back to the row index and de-duplicate defensively.
        doc_id = str(record.get("OrderID", i))
        if doc_id in seen_ids:
            doc_id = f"{doc_id}-{i}"
        seen_ids.add(doc_id)
        doc["id"] = doc_id

        # The Cosmos partition key field must be present and match the
        # container's partition key path chosen by the user.
        doc[partition_key_field] = str(record.get(partition_key_field, ""))

        try:
            container.upsert_item(doc)
            result["succeeded"] += 1
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            result["errors"].append(f"{doc_id}: HTTP {exc.status_code}")
        except Exception as exc:
            result["errors"].append(f"{doc_id}: {exc}")

    return result


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
st.sidebar.header("Dataset")
st.sidebar.write("Sample E-Commerce Orders")

df = load_data(DATA_PATH)
st.sidebar.caption(f"{len(df):,} records loaded from `{DATA_PATH}`")

st.sidebar.header("Select Partition Key")
selected_key = st.sidebar.selectbox(
    "Candidate partition key",
    CANDIDATE_KEYS,
    label_visibility="collapsed",
)

analyze_clicked = st.sidebar.button("Analyze Partition Key", type="primary", use_container_width=True)

st.sidebar.divider()
st.sidebar.caption(
    "Local design-study prototype. No connection to Azure or any cloud service."
)


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("Azure Partition Key Design Study")
st.markdown(
    "##### Compare partition-key choices before deploying data to Azure Table "
    "Storage or Azure Cosmos DB."
)
st.info(
    "This is a local design-study prototype. Results are calculated from the "
    "sample dataset and are not official Azure recommendations.",
    icon="ℹ️",
)

st.divider()

# --------------------------------------------------------------------------
# Selected partition key analysis
# --------------------------------------------------------------------------
st.header(f"Selected Partition Key: `{selected_key}`")

stats = compute_partition_stats(df, selected_key)
classification = classify_status(stats)

row1 = st.columns(3)
row1[0].metric(
    "Total Records",
    f"{stats['total_records']:,}",
    help="Total number of rows in the sample dataset.",
)
row1[1].metric(
    "Unique Partitions",
    f"{stats['unique_partitions']:,}",
    help="Cardinality: number of unique partition-key values.",
)
row1[2].metric(
    "Average Records per Partition",
    f"{stats['average_size']:.2f}",
    help="Total records divided by the number of unique partitions.",
)

row2 = st.columns(3)
row2[0].metric(
    "Largest Partition",
    f"{stats['largest_partition']:,}",
    help="Record count of the single largest partition value.",
)
row2[1].metric(
    "Smallest Partition",
    f"{stats['smallest_partition']:,}",
    help="Record count of the single smallest partition value.",
)
row2[2].metric(
    "Median Partition Size",
    f"{stats['median_size']:.2f}",
    help="Middle value of all partition sizes, less skewed by outliers than the average.",
)

row3 = st.columns(2)
row3[0].metric(
    "Partition Imbalance",
    f"{stats['imbalance_ratio']:.2f}x",
    help="Largest partition size divided by average partition size.",
)
row3[1].metric(
    "Hot Partition Risk",
    classification["risk"],
    help="Prototype heuristic indicating whether records are concentrated in a "
    "small number of partitions. Not an official Microsoft/Azure threshold.",
)

st.divider()

# --------------------------------------------------------------------------
# Why this key behaves this way
# --------------------------------------------------------------------------
st.subheader("Why this key behaves this way")
st.write(explain_key_behavior(stats, classification, selected_key))

st.divider()

# --------------------------------------------------------------------------
# Visualizations
# --------------------------------------------------------------------------
st.header("Visualizations")

HIGH_CARDINALITY_THRESHOLD = 40  # beyond this many partitions, aggregate instead of a full bar chart

viz_col1, viz_col2 = st.columns(2)

with viz_col1:
    st.subheader("Partition Size Distribution")
    counts = stats["counts"]
    if stats["unique_partitions"] > HIGH_CARDINALITY_THRESHOLD:
        # For very high-cardinality keys, show a histogram of partition sizes
        # instead of one bar per partition (which would be unreadable).
        hist_df = counts.reset_index()
        hist_df.columns = [selected_key, "Records"]
        fig_hist = px.histogram(
            hist_df,
            x="Records",
            nbins=min(20, int(counts.max())) or 1,
            title=f"Distribution of Partition Sizes for {selected_key}",
            labels={"Records": "Number of Records", "count": "Number of Partitions"},
        )
        fig_hist.update_layout(
            xaxis_title="Number of Records",
            yaxis_title="Number of Partitions",
            bargap=0.1,
        )
        st.plotly_chart(fig_hist, use_container_width=True)
        st.caption(
            f"`{selected_key}` has {stats['unique_partitions']:,} unique partitions, "
            "so sizes are aggregated into a histogram rather than plotted individually."
        )
    else:
        bar_df = counts.reset_index()
        bar_df.columns = [selected_key, "Records"]
        fig_bar = px.bar(
            bar_df,
            x=selected_key,
            y="Records",
            title=f"Records per Partition for {selected_key}",
        )
        fig_bar.update_layout(
            xaxis_title="Partition Key Value",
            yaxis_title="Number of Records",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with viz_col2:
    n_top = min(10, stats["unique_partitions"])
    st.subheader(f"Top {n_top} Largest Partitions" if n_top < 10 else "Top 10 Largest Partitions")
    top_n = stats["counts"].head(10).reset_index()
    top_n.columns = [selected_key, "Records"]
    top_n[selected_key] = top_n[selected_key].astype(str)
    fig_top = px.bar(
        top_n,
        x="Records",
        y=selected_key,
        orientation="h",
        title=f"Largest Partitions ({selected_key})",
        labels={"Records": "Number of Records", selected_key: "Partition Key Value"},
    )
    fig_top.update_layout(
        xaxis_title="Number of Records",
        yaxis_title="Partition Key Value",
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig_top, use_container_width=True)

st.divider()

# --------------------------------------------------------------------------
# Prototype Design Insight
# --------------------------------------------------------------------------
st.header("Prototype Design Insight")
st.write(prototype_design_insight(stats, classification, selected_key))
st.caption(
    "This is an analytical observation generated from the sample dataset, "
    "not an official Azure recommendation."
)

st.divider()

# --------------------------------------------------------------------------
# Good Partition-Key Characteristics vs Warning Signs
# --------------------------------------------------------------------------
st.header("Good Partition-Key Characteristics vs Warning Signs")

char_col1, char_col2 = st.columns(2)
with char_col1:
    st.subheader("Good Partition-Key Characteristics")
    st.markdown(
        "- Sufficient cardinality\n"
        "- Relatively distributed data\n"
        "- Avoids excessive concentration\n"
        "- Matches common access / query patterns\n"
        "- Supports expected workload growth"
    )
with char_col2:
    st.subheader("Warning Signs")
    st.markdown(
        "- Very few unique values\n"
        "- One value contains most records\n"
        "- Highly uneven partition sizes\n"
        "- Access concentrated on one value"
    )
st.caption("These are general design concepts, not official numerical thresholds.")

st.divider()

# --------------------------------------------------------------------------
# Comparison table across all candidate keys
# --------------------------------------------------------------------------
st.header("Partition Key Comparison")

RISK_INDICATOR = {"Low": "🟢 Low", "Medium": "🟡 Medium", "High": "🔴 High"}

comparison_rows = []
all_stats = {}
for key in CANDIDATE_KEYS:
    s = compute_partition_stats(df, key)
    c = classify_status(s)
    all_stats[key] = (s, c)
    comparison_rows.append(
        {
            "Partition Key": key,
            "Unique Values": s["unique_partitions"],
            "Avg Records": round(s["average_size"], 2),
            "Largest Partition": s["largest_partition"],
            "Smallest Partition": s["smallest_partition"],
            "Imbalance": f"{s['imbalance_ratio']:.2f}x",
            "Risk": RISK_INDICATOR[c["risk"]],
        }
    )

comparison_df = pd.DataFrame(comparison_rows)
st.dataframe(comparison_df, use_container_width=True, hide_index=True)

st.divider()

# --------------------------------------------------------------------------
# Azure connection explanation
# --------------------------------------------------------------------------
st.header("How This Relates to Azure")

azure_col1, azure_col2 = st.columns(2)

with azure_col1:
    st.subheader("Azure Table Storage")
    st.markdown(
        "- Entities are organized using a **PartitionKey** and a **RowKey**.\n"
        "- Entities that share the same `PartitionKey` belong to the same "
        "logical partition.\n"
        "- Choosing a partition key with an appropriate distribution matters "
        "for scalability and performance, since a partition that grows too "
        "large or receives too much traffic can become a bottleneck."
    )

with azure_col2:
    st.subheader("Azure Cosmos DB")
    st.markdown(
        "- Cosmos DB uses a partition key to distribute data across logical "
        "partitions, which map onto underlying physical resources.\n"
        "- A poor partition-key choice can create uneven workloads or "
        "concentrated access patterns, sometimes called 'hot partitions'.\n"
        "- A well-distributed key helps spread both storage and throughput "
        "evenly."
    )

st.warning(
    "This local prototype illustrates the *concepts* behind partition-key "
    "design. It does not exactly simulate Azure's internal partitioning "
    "behavior and does not connect to any Azure service."
)

st.divider()

# --------------------------------------------------------------------------
# OPTIONAL Azure Cosmos DB cloud validation
# --------------------------------------------------------------------------
st.header("Azure Cosmos DB — Cloud Validation")
st.caption(
    "Optional. Push the sample dataset into your own Azure Cosmos DB account to "
    "confirm a candidate partition key can be represented and stored in the "
    "cloud. Nothing here runs automatically -- every action requires a button "
    "click, and the rest of this dashboard works fully without Azure."
)

for _key in ("cosmos_status", "cosmos_container_status", "cosmos_upload_result"):
    if _key not in st.session_state:
        st.session_state[_key] = None

cosmos_config = get_cosmos_config()
missing_env_vars = cosmos_config_missing(cosmos_config)

info_col1, info_col2, info_col3 = st.columns(3)
info_col1.markdown(f"**Cosmos Database:** `{cosmos_config['database'] or '(not set)'}`")
info_col2.markdown(f"**Cosmos Container:** `{cosmos_config['container'] or '(not set)'}`")
with info_col3:
    azure_selected_key = st.selectbox(
        "Selected partition key",
        CANDIDATE_KEYS,
        key="azure_partition_key_select",
    )
st.caption(f"Creating/verifying the container will use Cosmos DB partition key path `/{azure_selected_key}`.")

if not AZURE_SDK_AVAILABLE:
    st.error(
        "The `azure-cosmos` package is not installed, so this section is disabled. "
        "Run `py -m pip install -r requirements.txt` to enable it. The local "
        "analysis above is unaffected."
    )
elif missing_env_vars:
    st.warning(
        "Azure connection status: **Not configured**. Set the following environment "
        f"variable(s) to enable cloud validation: {', '.join(missing_env_vars)}. "
        "The rest of this dashboard works fully without them."
    )
elif st.session_state["cosmos_status"] is None:
    st.info("Azure connection status: **Not tested yet.** Click \"Connect / Test Azure\" below.")

azure_btn_col1, azure_btn_col2, azure_btn_col3 = st.columns(3)
connect_clicked = azure_btn_col1.button("Connect / Test Azure", use_container_width=True)
verify_clicked = azure_btn_col2.button("Create / Verify Container", use_container_width=True)
upload_clicked = azure_btn_col3.button("Upload Sample Data", use_container_width=True)

if connect_clicked:
    with st.spinner("Testing connection to Azure Cosmos DB..."):
        st.session_state["cosmos_status"] = test_azure_connection(cosmos_config)

if verify_clicked:
    with st.spinner("Creating/verifying Cosmos DB database and container..."):
        st.session_state["cosmos_container_status"] = create_or_verify_container(cosmos_config, azure_selected_key)

if upload_clicked:
    with st.spinner(f"Uploading {len(df):,} records to Azure Cosmos DB..."):
        st.session_state["cosmos_upload_result"] = upload_dataframe_to_cosmos(cosmos_config, df, azure_selected_key)

if st.session_state["cosmos_status"] is not None:
    success, message = st.session_state["cosmos_status"]
    (st.success if success else st.error)(f"Azure connection status: {message}")

if st.session_state["cosmos_container_status"] is not None:
    success, message = st.session_state["cosmos_container_status"]
    (st.success if success else st.error)(message)

if st.session_state["cosmos_upload_result"] is not None:
    upload_result = st.session_state["cosmos_upload_result"]
    st.markdown(
        f"**Records attempted:** {upload_result['attempted']:,} &nbsp;|&nbsp; "
        f"**Successfully uploaded:** {upload_result['succeeded']:,} &nbsp;|&nbsp; "
        f"**Errors:** {len(upload_result['errors']):,}"
    )
    if upload_result["errors"]:
        with st.expander(f"View {len(upload_result['errors'])} upload error(s)"):
            st.code("\n".join(upload_result["errors"][:50]))
            if len(upload_result["errors"]) > 50:
                st.caption(f"...and {len(upload_result['errors']) - 50} more.")

st.info(
    "Cloud validation confirms that the selected partition-key design can be "
    "represented and tested in Azure Cosmos DB. It does not guarantee production "
    "performance."
)

st.divider()

# --------------------------------------------------------------------------
# Final summary
# --------------------------------------------------------------------------
st.header("Partition Key Design Summary")

summary_stats, summary_classification = all_stats[selected_key]

summary_col1, summary_col2 = st.columns(2)
with summary_col1:
    st.markdown(f"**Selected Key:** `{selected_key}`")
    st.markdown(f"**Cardinality:** `{summary_classification['cardinality_status']}`")
    st.markdown(f"**Distribution:** `{summary_classification['distribution_status']}`")
with summary_col2:
    st.markdown(f"**Hot Partition Risk:** `{summary_classification['risk']}`")
    st.markdown(
        f"**Prototype Insight:** {prototype_design_insight(summary_stats, summary_classification, selected_key)}"
    )

st.divider()

# --------------------------------------------------------------------------
# Architecture section
# --------------------------------------------------------------------------
st.header("How the Prototype Works")

st.code(
    "Sample Dataset\n"
    "      ↓\n"
    "Candidate Partition Keys\n"
    "      ↓\n"
    "Partition Analyzer\n"
    "      ↓\n"
    "Cardinality Analysis\n"
    "      ↓\n"
    "Distribution Analysis\n"
    "      ↓\n"
    "Partition Size Analysis\n"
    "      ↓\n"
    "Hot Partition Risk\n"
    "      ↓\n"
    "Comparison Dashboard",
    language="text",
)

st.markdown(
    "- **Sample Dataset** &mdash; `sample_data.csv` provides ~1,000 realistic e-commerce orders.\n"
    "- **Candidate Partition Keys** &mdash; `CustomerID`, `Region`, `Category`, and `OrderID` are "
    "considered as possible partition keys.\n"
    "- **Partition Analyzer** &mdash; groups the dataset by the chosen key and counts records per value.\n"
    "- **Cardinality Analysis** &mdash; measures how many unique partition values exist relative to "
    "total records.\n"
    "- **Distribution Analysis** &mdash; measures how evenly records are spread across those values.\n"
    "- **Partition Size Analysis** &mdash; computes average, median, largest, and smallest partition sizes.\n"
    "- **Hot Partition Risk** &mdash; combines cardinality and distribution into a single heuristic risk label.\n"
    "- **Comparison Dashboard** &mdash; presents all of the above for every candidate key side by side."
)

st.caption(
    "Azure Partition Key Design Study &mdash; a local prototype for exploring "
    "partition-key trade-offs. Not an official Azure recommendation engine."
)
