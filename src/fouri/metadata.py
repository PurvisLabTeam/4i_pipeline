"""Per-well metadata: well names, CSV import, generated sample_IDs and checks.

Standard metadata CSV (one row per well; only ``well`` is required)::

    well,treatment,dose,treatment_time,sample_ID
    B02,control,0,96h,
    B03,abema_fulv,100nM,96h,

- wells may be written B2 or B02
- sample_ID is optional; if the column is missing or empty, IDs are generated
  so that wells with the same condition share an ID, numbered in plate order
- any other columns are kept as extra metadata
"""

import os
import re

import pandas as pd

STANDARD_COLUMNS = ["sample_ID", "treatment", "dose", "treatment_time"]

# accepted spellings (compared lower-case, spaces/dashes as underscores)
_COLUMN_ALIASES = {
    "well": "well",
    "sample_id": "sample_ID",
    "sampleid": "sample_ID",
    "treatment": "treatment",
    "dose": "dose",
    "treatment_time": "treatment_time",
    "time": "treatment_time",
}

_WELL_RE = re.compile(r"^([A-Pa-p])0*([1-9]|1[0-9]|2[0-4])$")
_ND2_WELL_RE = re.compile(r"Well([A-P]\d{1,2})_Channel")


def normalize_well(well):
    """'b2' / 'B2' / 'B02' -> 'B02'. Raises ValueError for anything else."""
    m = _WELL_RE.match(str(well).strip())
    if not m:
        raise ValueError(f"Not a well name: {well!r}")
    return f"{m.group(1).upper()}{int(m.group(2)):02d}"


def plate_sort_key(well):
    """Sort wells in plate order: A01, A02, ... B01, ..."""
    w = normalize_well(well)
    return (w[0], int(w[1:]))


def to_sample_id(value):
    """Sample IDs are ints when they look like ints (Lauryn's configs store '1')."""
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _clean(value):
    """Blank/NaN -> '' ; everything else as a stripped string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def read_metadata_table(source):
    """Read per-well metadata from a CSV/TSV path or a DataFrame.

    Returns a DataFrame with a normalized ``well`` column (one row per well,
    plate order) and standard column names; values are strings ('' if blank).
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        path = os.path.expanduser(str(source))
        sep = "\t" if path.lower().endswith((".tsv", ".txt")) else ","
        df = pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False)

    renamed = {}
    for col in df.columns:
        key = re.sub(r"[\s\-]+", "_", str(col).strip().lower())
        renamed[col] = _COLUMN_ALIASES.get(key, str(col).strip())
    df = df.rename(columns=renamed)
    if "well" not in df.columns:
        raise ValueError(f"Metadata table needs a 'well' column (found: {list(df.columns)})")

    df = df.loc[df["well"].map(_clean) != ""].copy()
    bad = [w for w in df["well"] if not _WELL_RE.match(str(w).strip())]
    if bad:
        raise ValueError(f"Unrecognized well names: {bad}")
    df["well"] = df["well"].map(normalize_well)
    for col in df.columns:
        if col != "well":
            df[col] = df[col].map(_clean)
    df = df.sort_values("well", key=lambda s: s.map(plate_sort_key), kind="stable")
    return df.reset_index(drop=True)


def assign_sample_ids(table, condition_columns):
    """Fill in sample_IDs.

    If every row already has a sample_ID, those are kept. Otherwise wells with
    identical values in ``condition_columns`` get the same ID, numbered 1, 2, ...
    by the first well (in plate order) with each condition.
    """
    df = table.copy()
    if "sample_ID" in df.columns and (df["sample_ID"].map(_clean) != "").all():
        df["sample_ID"] = df["sample_ID"].map(to_sample_id)
        return df
    cols = [c for c in condition_columns if c in df.columns]
    order = df.sort_values("well", key=lambda s: s.map(plate_sort_key), kind="stable")
    ids = {}
    for _, row in order.iterrows():
        cond = tuple(_clean(row[c]) for c in cols)
        ids.setdefault(cond, len(ids) + 1)
    df["sample_ID"] = [ids[tuple(_clean(row[c]) for c in cols)] for _, row in df.iterrows()]
    return df


def check_metadata(table, condition_columns, wells_with_data=None):
    """Return a list of ('error'|'warning', message) for a metadata table."""
    issues = []
    dup = table["well"][table["well"].duplicated()].unique().tolist()
    if dup:
        issues.append(("error", f"Wells listed more than once: {dup}"))
    if wells_with_data is not None:
        missing = sorted(set(table["well"]) - set(wells_with_data), key=plate_sort_key)
        if missing:
            issues.append(("error", f"No ND2 files in data/ for wells: {missing}"))
        unused = sorted(set(wells_with_data) - set(table["well"]), key=plate_sort_key)
        if unused:
            issues.append(("warning", f"Wells with data that are not included: {unused}"))
    if "sample_ID" in table.columns:
        cols = [c for c in condition_columns if c in table.columns]
        if cols:
            conds = table[cols].map(_clean).apply(tuple, axis=1)
            sid = table["sample_ID"].astype(str)
            for s, c in pd.DataFrame({"s": sid, "c": conds}).groupby("s")["c"]:
                if c.nunique() > 1:
                    issues.append(("warning", f"sample_ID {s} covers different conditions: {sorted(set(c))}"))
            for c, s in pd.DataFrame({"s": sid, "c": conds}).groupby("c")["s"]:
                if s.nunique() > 1:
                    issues.append(("warning", f"Condition {c} has several sample_IDs: {sorted(set(s))}"))
    return issues


def table_to_config(table):
    """DataFrame -> (well_list, well_metadata) for experiment.json."""
    well_list = table["well"].tolist()
    meta = {}
    for _, row in table.iterrows():
        m = {}
        for col in table.columns:
            if col == "well":
                continue
            value = row[col]
            if col == "sample_ID":
                m[col] = to_sample_id(value)
            elif _clean(value) != "":
                m[col] = _clean(value)
        meta[row["well"]] = m
    return well_list, meta


def config_to_table(well_list, well_metadata):
    """(well_list, well_metadata) -> DataFrame, the inverse of table_to_config."""
    rows = [{"well": w, **(well_metadata.get(w) or {})} for w in well_list]
    df = pd.DataFrame(rows, columns=None)
    if df.empty:
        df = pd.DataFrame(columns=["well"])
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    extras = [c for c in df.columns if c not in ["well", *STANDARD_COLUMNS]]
    df = df[["well", *STANDARD_COLUMNS, *extras]]
    for col in df.columns:
        if col not in ("well", "sample_ID"):
            df[col] = df[col].map(_clean)
    return df


def wells_in_data(data_dir):
    """Wells that have ND2 files (``Well<W>_Channel...nd2``) in any round folder."""
    wells = set()
    if not os.path.isdir(data_dir):
        return []
    for sub in os.listdir(data_dir):
        sub_path = os.path.join(data_dir, sub)
        if not os.path.isdir(sub_path):
            continue
        for name in os.listdir(sub_path):
            m = _ND2_WELL_RE.search(name)
            if m and name.lower().endswith(".nd2"):
                wells.add(normalize_well(m.group(1)))
    return sorted(wells, key=plate_sort_key)


def channel_names(info_file):
    """Round/channel prefixes as notebook 06 names them, e.g. ['R0_DNA', 'R0_pRB', ...]."""
    info = pd.read_csv(info_file)
    names = []
    for _, row in info.iterrows():
        for col in info.columns[1:]:
            signal = row[col]
            if signal == signal and str(signal).strip():  # skip empty cells
                names.append(f"{str(row.iloc[0]).zfill(2)}_{signal}")
    return names


def default_derived_features(info_file):
    """Starting derived features for 07, based on the channels that exist."""
    names = channel_names(info_file)
    features = []
    for n in names:
        rnd, signal = n.split("_", 1)
        if signal == "pRB" and f"{rnd}_RB" in names:
            features.append({"name": "pRB_RB_ratio", "formula": f"{rnd}_pRB_nuc_mean / {rnd}_RB_nuc_mean"})
            break
    dna = [n for n in names if n.endswith("_DNA")]
    if dna:
        features.append({"name": "total_area_DNA", "formula": f"{dna[0]}_nuc_mean * nuc_area"})
    return features
