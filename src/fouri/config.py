"""Experiment configuration: one ``experiment.json`` per experiment.

Every pipeline notebook starts with::

    from fouri import load_config
    CONFIG = r'Z:\\Clara\\1.3_20260310_Working Folder 4i\\experiment.json'
    exp = load_config(CONFIG)

and takes all of its paths and the well list from ``exp``. Create or edit the
file with ``setup_experiment.ipynb``.

The JSON format is compatible with Lauryn's ``project_config`` configs
(experiment_key, experiment_name, base_dir, mac_base_dir, well_list,
well_metadata, ...). Fields added here are optional:

- ``well_metadata[well]["treatment_time"]`` and any extra per-well columns
- ``condition_columns``: metadata columns that define a sample_ID
- ``derived_features``: ``[{"name": ..., "formula": ...}]`` used by notebook 07
- ``paths``: per-folder overrides, absolute or relative to base_dir
"""

import json
import os
import platform

from .metadata import plate_sort_key, to_sample_id

CONFIG_NAME = "experiment.json"

# Folder layout inside an experiment's base_dir. Any of these can be
# overridden in the config's "paths" section.
DEFAULT_PATHS = {
    "info_file": "info_exp.csv",
    "data": "data",
    "output_df": "output_df",
    "output_images": "output_images",
    "segmented": "segmented",
    "aligned_tiffs": "aligned_tiffs",
    "masks": "masks",
    "cell_data": "cell_data",
}

DEFAULT_CONDITION_COLUMNS = ["treatment", "dose", "treatment_time"]


class Experiment:
    """A loaded experiment config with its folder paths resolved."""

    def __init__(self, config, config_path):
        self.config = config
        self.config_path = os.path.abspath(config_path)
        self.base_dir = _resolve_base_dir(config, self.config_path)
        overrides = config.get("paths") or {}
        self.paths = {
            name: os.path.normpath(os.path.join(self.base_dir, overrides.get(name) or default))
            for name, default in DEFAULT_PATHS.items()
        }

    # -- identity -------------------------------------------------------------
    @property
    def key(self):
        return self.config.get("experiment_key", "")

    @property
    def name(self):
        return self.config.get("experiment_name", "")

    # -- wells and metadata ---------------------------------------------------
    @property
    def well_list(self):
        return list(self.config.get("well_list", []))

    @property
    def well_metadata(self):
        """{well: {"sample_ID": int, "treatment": ..., ...}} for every well in well_list."""
        meta = self.config.get("well_metadata") or {}
        out = {}
        for well in self.well_list:
            m = dict(meta.get(well, {}))
            if "sample_ID" in m:
                m["sample_ID"] = to_sample_id(m["sample_ID"])
            out[well] = m
        return out

    @property
    def metadata_columns(self):
        """All metadata column names used by any well, sample_ID first."""
        cols = []
        for m in self.well_metadata.values():
            for c in m:
                if c not in cols:
                    cols.append(c)
        return sorted(cols, key=lambda c: (c != "sample_ID", c not in DEFAULT_CONDITION_COLUMNS, cols.index(c)))

    @property
    def condition_columns(self):
        return list(self.config.get("condition_columns", DEFAULT_CONDITION_COLUMNS))

    @property
    def derived_features(self):
        return list(self.config.get("derived_features", []))

    # -- folders --------------------------------------------------------------
    @property
    def info_file(self):
        return self.paths["info_file"]

    @property
    def data_dir(self):
        return self.paths["data"]

    @property
    def output_df(self):
        return self.paths["output_df"]

    @property
    def output_images(self):
        return self.paths["output_images"]

    @property
    def segmented(self):
        return self.paths["segmented"]

    @property
    def aligned_tiffs(self):
        return self.paths["aligned_tiffs"]

    @property
    def masks(self):
        return self.paths["masks"]

    @property
    def cell_data(self):
        return self.paths["cell_data"]

    def file(self, name):
        """Path of a file directly in base_dir, e.g. exp.file('standard_adata.h5ad')."""
        return os.path.join(self.base_dir, name)

    # dict-style access for code written against Lauryn's project_config
    def __getitem__(self, item):
        if item == "base_dir":
            return self.base_dir
        return self.config[item]

    def get(self, item, default=None):
        try:
            return self[item]
        except KeyError:
            return default

    def __repr__(self):
        return f"Experiment({self.key!r}, base_dir={self.base_dir!r}, {len(self.well_list)} wells)"


def _resolve_base_dir(config, config_path):
    """base_dir from the config if set (Lauryn-style), else the config file's folder."""
    if platform.system() != "Windows" and (config.get("mac_base_dir") or "").strip():
        return os.path.normpath(config["mac_base_dir"].strip())
    if (config.get("base_dir") or "").strip():
        return os.path.normpath(config["base_dir"].strip())
    return os.path.dirname(config_path)


def config_path_for(path):
    """Accept either an experiment.json path or the experiment folder."""
    path = os.path.expanduser(str(path))
    if os.path.isdir(path):
        return os.path.join(path, CONFIG_NAME)
    return path


def load_config(path, announce=True):
    """Load an experiment config and print which experiment is active.

    ``path`` is the experiment's ``experiment.json`` (or the folder holding it).
    """
    config_path = config_path_for(path)
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"No experiment config at {config_path}. "
            "Create one with setup_experiment.ipynb, or check the CONFIG path."
        )
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    exp = Experiment(config, config_path)
    if announce:
        announce_experiment(exp)
    return exp


def announce_experiment(exp):
    """Print a banner with the experiment and warn about missing folders."""
    print(f"Experiment: {exp.key or '(no key)'}" + (f" - {exp.name}" if exp.name else ""))
    print(f"  config:   {exp.config_path}")
    print(f"  base_dir: {exp.base_dir}")
    print(f"  wells:    {len(exp.well_list)}")
    if not os.path.isdir(exp.base_dir):
        print(f"  WARNING: base_dir does not exist: {exp.base_dir}")
    for name in ("data", "info_file"):
        if not os.path.exists(exp.paths[name]):
            print(f"  WARNING: {name} not found: {exp.paths[name]}")


def save_config(config, path):
    """Write a config dict to ``path`` (experiment.json or its folder)."""
    config = dict(config)
    config["well_list"] = sorted(config.get("well_list", []), key=plate_sort_key)
    meta = config.get("well_metadata") or {}
    config["well_metadata"] = {w: meta[w] for w in config["well_list"] if w in meta}
    config_path = config_path_for(path)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return config_path
