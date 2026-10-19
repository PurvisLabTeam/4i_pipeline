"""Helpers for notebook 07 (cell data -> AnnData)."""

import os

import pandas as pd

# column names notebook 07 has always used in fullest_df / adata.obs
_OBS_NAMES = {"treatment_time": "treatment time"}


def build_fullest_df(exp):
    """Concatenate every well's cell_data CSV and add its metadata from the config."""
    frames = []
    for well, meta in exp.well_metadata.items():
        print(f"starting Well {well}")
        df = pd.read_csv(os.path.join(exp.cell_data, f"cell_data_{well}_df.csv"), sep=",")
        meta_df = pd.DataFrame({_OBS_NAMES.get(c, c): [v] * len(df) for c, v in meta.items()}, index=df.index)
        frames.append(pd.concat([df, meta_df], axis=1))
        print(len(frames[-1]))
    fullest_df = pd.concat(frames, ignore_index=True)
    print(f"{len(fullest_df)} cells in {len(frames)} wells")
    return fullest_df


def metadata_obs_columns(exp):
    """fullest_df column names that hold well metadata (go to adata.obs, not .X)."""
    return [_OBS_NAMES.get(c, c) for c in exp.metadata_columns]


def add_derived_features(df, derived_features):
    """Add columns defined as {"name": ..., "formula": ...} (pandas.eval syntax).

    Features are added in order, so a formula can use an earlier one. A feature
    whose formula uses a column that doesn't exist is skipped with a message,
    so experiments without e.g. an S6 antibody don't stop here.
    """
    df = df.copy()  # one contiguous block, so adding columns one by one stays fast
    for spec in derived_features:
        name, formula = spec["name"], spec["formula"]
        try:
            df[name] = df.eval(formula)
            print(f"added {name} = {formula}")
        except (pd.errors.UndefinedVariableError, KeyError) as e:
            print(f"SKIPPED {name} = {formula}  ({e})")
    return df


def standardize_columns(df):
    """z-score every column (sample standard deviation, as before)."""
    return (df - df.mean()) / df.std()


def default_threshold_sample(exp):
    """sample_ID to use for picking the pRB threshold: the control if there is one."""
    meta = exp.well_metadata
    for m in meta.values():
        if "control" in str(m.get("treatment", "")).lower():
            return m.get("sample_ID")
    ids = [m.get("sample_ID") for m in meta.values() if "sample_ID" in m]
    return ids[0] if ids else None
