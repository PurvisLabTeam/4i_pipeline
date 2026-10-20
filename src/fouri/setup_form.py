"""Point-and-click form that writes an experiment's ``experiment.json``.

Used from ``setup_experiment.ipynb``::

    from fouri.setup_form import show_setup_form
    show_setup_form()
"""

import html
import json
import os

import ipywidgets as w
from IPython.display import display

from .config import CONFIG_NAME, DEFAULT_CONDITION_COLUMNS, DEFAULT_PATHS, Experiment, save_config
from .metadata import (
    STANDARD_COLUMNS,
    assign_sample_ids,
    channel_names,
    check_metadata,
    config_to_table,
    default_derived_features,
    plate_sort_key,
    read_metadata_table,
    table_to_config,
    wells_in_data,
)

ROWS = "ABCDEFGH"
COLS = range(1, 13)
SAMPLE_COLORS = [
    "#8dd3c7", "#fdb462", "#bebada", "#fb8072", "#80b1d3", "#b3de69",
    "#fccde5", "#bc80bd", "#ccebc5", "#ffed6f", "#d9d9d9", "#e5c494",
]
NO_DATA_COLOR = "#f2f2f2"
EXCLUDED_COLOR = "#ffffff"
SELECTED_COLOR = "#ff7f00"

INFO_FIELDS = [
    ("experiment_key", "Experiment key"),
    ("experiment_name", "Name"),
    ("cell_type", "Cell type"),
    ("passage", "Passage"),
    ("date_completed", "Date completed"),
]


class SetupForm:
    def __init__(self, folder=""):
        self.base_dir = ""
        self.config = {}
        self.data_wells = []        # wells with ND2 files
        self.included = set()       # wells in the experiment
        self.selected = set()       # wells picked for "Apply"
        self.meta = {}              # well -> {column: value}
        self.extra_columns = []

        lay = w.Layout(width="520px")
        self.folder = w.Text(value=folder, description="Folder", placeholder=r"Z:\Name\experiment folder", layout=w.Layout(width="620px"))
        self.load_btn = w.Button(description="Load folder", button_style="primary")
        self.load_btn.on_click(lambda _: self.load_folder())

        self.info = {k: w.Text(description=label, layout=lay, style={"description_width": "120px"}) for k, label in INFO_FIELDS}
        self.notes = w.Textarea(description="Notes", layout=w.Layout(width="520px", height="60px"), style={"description_width": "120px"})
        self.data_path = w.Text(description="data folder", layout=lay, style={"description_width": "120px"},
                                placeholder="data  (relative to the experiment folder, or a full path)")
        self.info_path = w.Text(description="info file", layout=lay, style={"description_width": "120px"},
                                placeholder="info_exp.csv")
        self.data_path.observe(lambda _: self.rescan(), names="value")

        # plate
        self.mode = w.ToggleButtons(options=[("Include / exclude wells", "include"), ("Select wells for a condition", "select")],
                                    value="include")
        self.mode.observe(lambda _: self.refresh(), names="value")
        self.buttons = {}
        grid = [w.HBox([w.Label("", layout=w.Layout(width="22px"))] + [w.Label(f"{c:02d}", layout=w.Layout(width="46px")) for c in COLS])]
        for r in ROWS:
            row = [w.Label(r, layout=w.Layout(width="22px"))]
            for c in COLS:
                well = f"{r}{c:02d}"
                b = w.Button(description="", layout=w.Layout(width="46px", height="30px"), tooltip=well)
                b.on_click(lambda _, well=well: self.click(well))
                self.buttons[well] = b
                row.append(b)
            grid.append(w.HBox(row))
        self.plate = w.VBox(grid)
        self.all_btn = w.Button(description="Include all wells with data")
        self.all_btn.on_click(lambda _: self.include_all())
        self.clear_sel_btn = w.Button(description="Clear selection")
        self.clear_sel_btn.on_click(lambda _: self.clear_selection())

        # condition entry
        self.cond = {c: w.Text(description=c, layout=w.Layout(width="300px")) for c in ("treatment", "dose", "treatment_time")}
        self.extra_names = w.Text(description="Extra columns", placeholder="e.g. replicate, cell_line",
                                  layout=w.Layout(width="420px"), style={"description_width": "100px"})
        self.extra_names.observe(lambda _: self.update_extra_columns(), names="value")
        self.extra_box = w.VBox()
        self.extra_fields = {}
        self.condition_checks = w.VBox()
        self.apply_btn = w.Button(description="Apply to selected wells", button_style="success")
        self.apply_btn.on_click(lambda _: self.apply_condition())

        # CSV
        self.csv_path = w.Text(description="CSV", placeholder="metadata.csv (in the folder, or a full path)", layout=w.Layout(width="520px"))
        self.import_btn = w.Button(description="Import CSV")
        self.import_btn.on_click(lambda _: self.import_csv())
        self.export_btn = w.Button(description="Export CSV template")
        self.export_btn.on_click(lambda _: self.export_csv())

        # derived features
        self.features = w.Textarea(layout=w.Layout(width="620px", height="90px"),
                                   placeholder="one per line:  name = formula   e.g.  pRB_RB_ratio = R0_pRB_nuc_mean / R0_RB_nuc_mean")
        self.channels_html = w.HTML()

        self.preview = w.HTML()
        self.messages = w.HTML()
        self.save_btn = w.Button(description=f"Save {CONFIG_NAME}", button_style="warning", icon="save")
        self.save_btn.on_click(lambda _: self.save())
        self.out = w.Output()

        if folder:
            self.load_folder()
        self.refresh()

    # -- layout -----------------------------------------------------------------
    def widget(self):
        h = lambda text: w.HTML(f"<h3 style='margin:12px 0 4px'>{text}</h3>")
        return w.VBox([
            h("1. Experiment folder"),
            w.HBox([self.folder, self.load_btn]),
            h("2. Experiment details"),
            *self.info.values(), self.notes,
            w.HTML("<i>Leave these empty to use the standard layout inside the experiment folder:</i>"),
            self.data_path, self.info_path,
            h("3. Wells and conditions"),
            w.HTML("Grey wells have no ND2 files. Coloured wells are included; the colour is the sample_ID. "
                   "To set a condition: switch to <b>Select wells</b>, click wells, fill in the fields, then <b>Apply</b>."),
            self.mode, self.plate, w.HBox([self.all_btn, self.clear_sel_btn]),
            w.HBox([w.VBox(list(self.cond.values())), w.VBox([self.extra_names, self.extra_box])]),
            self.apply_btn,
            w.HTML("<b>Columns that define a condition</b> (wells with the same values get the same sample_ID):"),
            self.condition_checks,
            w.HTML("<b>Or import a metadata CSV</b> (one row per well; only <code>well</code> is required):"),
            w.HBox([self.csv_path, self.import_btn, self.export_btn]),
            h("4. Derived features for notebook 07"),
            self.features, self.channels_html,
            h("5. Check and save"),
            self.preview, self.messages, self.save_btn, self.out,
        ])

    # -- loading ----------------------------------------------------------------
    def _resolve(self, value, default):
        value = (value or "").strip() or default
        return os.path.normpath(os.path.join(self.base_dir, value))

    def load_folder(self):
        folder = os.path.normpath(os.path.expanduser(self.folder.value.strip().strip('"')))
        self.messages.value = ""
        if not os.path.isdir(folder):
            self._msg("error", f"Folder not found: {folder}")
            return
        self.base_dir = folder
        cfg_path = os.path.join(folder, CONFIG_NAME)
        self.config = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                self.config = json.load(f)
        for k, _ in INFO_FIELDS:
            self.info[k].value = str(self.config.get(k, "") or "")
        if not self.info["experiment_key"].value:
            self.info["experiment_key"].value = os.path.basename(folder)
        self.notes.value = self.config.get("notes", "") or ""
        paths = self.config.get("paths") or {}
        self.data_path.value = paths.get("data", "")
        self.info_path.value = paths.get("info_file", "")

        exp_meta = Experiment(self.config, cfg_path).well_metadata if self.config else {}
        self.meta = {wl: dict(m) for wl, m in exp_meta.items()}  # keeps saved sample_IDs until conditions change
        extras = []
        for m in self.meta.values():
            extras += [c for c in m if c not in STANDARD_COLUMNS and c not in extras]
        self.extra_names.value = ", ".join(extras)
        self.rescan()
        self.included = set(self.config.get("well_list", [])) or set(self.data_wells)
        feats = self.config.get("derived_features")
        if feats is None and os.path.exists(self._resolve(self.info_path.value, DEFAULT_PATHS["info_file"])):
            feats = default_derived_features(self._resolve(self.info_path.value, DEFAULT_PATHS["info_file"]))
        self.features.value = "\n".join(f"{f['name']} = {f['formula']}" for f in (feats or []))
        conds = self.config.get("condition_columns", DEFAULT_CONDITION_COLUMNS)
        self.update_extra_columns(checked=conds)
        self._msg("ok", f"Loaded {folder}" + (" (existing experiment.json)" if self.config else " (new experiment)"))
        self.refresh()

    def rescan(self):
        if not self.base_dir:
            return
        data_dir = self._resolve(self.data_path.value, DEFAULT_PATHS["data"])
        self.data_wells = wells_in_data(data_dir)
        info = self._resolve(self.info_path.value, DEFAULT_PATHS["info_file"])
        if os.path.exists(info):
            names = channel_names(info)
            self.channels_html.value = ("<small>Columns available per cell (add <code>_nuc_mean</code>, "
                                        "<code>_ring_mean</code>, <code>_total_nuc_protein</code> or "
                                        "<code>_nuc_cyto_ratio</code>; also <code>nuc_area</code>, <code>ring_area</code>): "
                                        + ", ".join(names) + "</small>")
        else:
            self.channels_html.value = f"<small>info file not found: {html.escape(info)}</small>"
        self.refresh()

    # -- plate interaction -------------------------------------------------------
    def click(self, well):
        if self.mode.value == "include":
            if well not in self.data_wells:
                return
            self.included ^= {well}
        else:
            if well not in self.included:
                return
            self.selected ^= {well}
        self.refresh()

    def include_all(self):
        self.included = set(self.data_wells)
        self.refresh()

    def clear_selection(self):
        self.selected = set()
        self.refresh()

    def update_extra_columns(self, checked=None):
        names = []
        for n in self.extra_names.value.split(","):
            n = n.strip()
            if n and n not in STANDARD_COLUMNS and n != "well" and n not in names:
                names.append(n)
        self.extra_columns = names
        for n in names:
            self.extra_fields.setdefault(n, w.Text(description=n, layout=w.Layout(width="300px")))
        self.extra_box.children = [self.extra_fields[n] for n in names]
        prev = {cb.description: cb.value for cb in self._condition_boxes()}
        if checked is None:
            checked = [c for c, v in prev.items() if v] if prev else DEFAULT_CONDITION_COLUMNS
        boxes = []
        for c in ["treatment", "dose", "treatment_time", *names]:
            cb = w.Checkbox(value=c in checked, description=c, indent=False, layout=w.Layout(width="160px"))
            cb.observe(lambda _: self._conditions_changed(), names="value")
            boxes.append(cb)
        self.condition_checks.children = [w.HBox(boxes)]
        self.refresh()

    def _conditions_changed(self):
        for m in self.meta.values():  # which columns define a condition changed: regenerate sample_IDs
            m.pop("sample_ID", None)
        self.refresh()

    def _condition_boxes(self):
        return self.condition_checks.children[0].children if self.condition_checks.children else []

    @property
    def condition_columns(self):
        return [cb.description for cb in self._condition_boxes() if cb.value]

    def apply_condition(self):
        if not self.selected:
            self._msg("error", "Select wells first (switch to 'Select wells for a condition' and click wells).")
            return
        values = {c: f.value.strip() for c, f in self.cond.items()}
        values.update({c: self.extra_fields[c].value.strip() for c in self.extra_columns})
        for well in self.selected:
            self.meta.setdefault(well, {}).update(values)
        for m in self.meta.values():  # conditions changed: regenerate sample_IDs
            m.pop("sample_ID", None)
        self._msg("ok", f"Applied to {', '.join(sorted(self.selected, key=plate_sort_key))}")
        self.selected = set()
        self.refresh()

    # -- CSV ------------------------------------------------------------------
    def _csv_file(self):
        p = self.csv_path.value.strip().strip('"') or "metadata.csv"
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)

    def import_csv(self):
        try:
            table = read_metadata_table(self._csv_file())
        except Exception as e:  # show the problem in the form instead of a traceback
            self._msg("error", f"Could not import: {e}")
            return
        given_ids = "sample_ID" in table.columns and (table["sample_ID"] != "").all()
        self.included = set(table["well"])
        self.meta = {}
        for _, row in table.iterrows():
            self.meta[row["well"]] = {c: row[c] for c in table.columns if c != "well" and c != "sample_ID"}
        if given_ids:
            for _, row in table.iterrows():
                self.meta[row["well"]]["sample_ID"] = row["sample_ID"]
        extras = [c for c in table.columns if c not in ["well", *STANDARD_COLUMNS]]
        self.extra_names.value = ", ".join(extras)
        self._msg("ok", f"Imported {len(table)} wells from {self._csv_file()}"
                  + (" (using the CSV's sample_IDs)" if given_ids else " (sample_IDs generated)"))
        self.refresh()

    def export_csv(self):
        if not self.base_dir:
            self._msg("error", "Load a folder first.")
            return
        wells = sorted(self.included or self.data_wells, key=plate_sort_key)
        table = self.table(wells)
        path = self._csv_file()
        if os.path.exists(path):
            self._msg("error", f"{path} already exists; choose another file name in the CSV box.")
            return
        table.drop(columns=["sample_ID"]).to_csv(path, index=False)
        self._msg("ok", f"Wrote template {path}: fill it in (e.g. in Excel), then Import CSV.")

    # -- table / preview -----------------------------------------------------------
    def table(self, wells=None):
        wells = sorted(self.included if wells is None else wells, key=plate_sort_key)
        meta = {wl: dict(self.meta.get(wl, {})) for wl in wells}
        df = config_to_table(wells, meta)
        for c in self.extra_columns:
            if c not in df.columns:
                df[c] = ""
        keep_ids = all(str(meta[wl].get("sample_ID", "")).strip() for wl in wells) and wells
        if not keep_ids:
            df["sample_ID"] = ""
        return assign_sample_ids(df, self.condition_columns)

    def refresh(self):
        table = self.table() if self.included else None
        ids = dict(zip(table["well"], table["sample_ID"])) if table is not None else {}
        id_list = sorted(set(ids.values()), key=str)
        colors = {sid: SAMPLE_COLORS[i % len(SAMPLE_COLORS)] for i, sid in enumerate(id_list)}
        for well, b in self.buttons.items():
            has_data = well in self.data_wells
            b.disabled = not has_data
            if well in self.selected:
                b.style.button_color, b.description = SELECTED_COLOR, "✓"
            elif well in self.included:
                b.style.button_color, b.description = colors.get(ids.get(well), "#cccccc"), str(ids.get(well, ""))
            else:
                b.style.button_color, b.description = (EXCLUDED_COLOR if has_data else NO_DATA_COLOR), ""
        if table is None or table.empty:
            self.preview.value = "<i>No wells included yet.</i>"
            return
        cols = [c for c in ["treatment", "dose", "treatment_time", *self.extra_columns] if c in table.columns]
        rows = []
        for sid, grp in table.groupby("sample_ID", sort=False):
            cond = " · ".join(f"{c}={html.escape(str(grp.iloc[0][c]))}" for c in cols if str(grp.iloc[0][c]))
            rows.append(f"<tr><td style='background:{colors[sid]};padding:2px 8px'><b>{sid}</b></td>"
                        f"<td style='padding:2px 8px'>{cond or '<i>no condition set</i>'}</td>"
                        f"<td style='padding:2px 8px'>{', '.join(grp['well'])}</td></tr>")
        self.preview.value = ("<table style='border-collapse:collapse'><tr><th>sample_ID</th><th>condition</th>"
                              "<th>wells</th></tr>" + "".join(rows) + "</table>")

    # -- saving -----------------------------------------------------------------
    def parse_features(self):
        feats = []
        for line in self.features.value.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Derived feature needs 'name = formula': {line!r}")
            name, formula = (s.strip() for s in line.split("=", 1))
            feats.append({"name": name, "formula": formula})
        return feats

    def save(self):
        self.out.clear_output()
        if not self.base_dir:
            self._msg("error", "Load a folder first.")
            return
        if not self.included:
            self._msg("error", "No wells included.")
            return
        try:
            feats = self.parse_features()
        except ValueError as e:
            self._msg("error", str(e))
            return
        table = self.table()
        issues = check_metadata(table, self.condition_columns, self.data_wells)
        errors = [m for lvl, m in issues if lvl == "error"]
        if errors:
            self._msg("error", "Not saved:<br>" + "<br>".join(html.escape(m) for m in errors))
            return
        well_list, well_metadata = table_to_config(table)
        config = {k: v for k, v in self.config.items() if k not in ("base_dir", "mac_base_dir")}
        config.update({k: f.value.strip() for k, f in self.info.items()})
        config["notes"] = self.notes.value
        config["well_list"] = well_list
        config["well_metadata"] = well_metadata
        config["condition_columns"] = self.condition_columns
        config["derived_features"] = feats
        paths = {k: v for k, v in (config.get("paths") or {}).items() if k not in ("data", "info_file")}
        if self.data_path.value.strip():
            paths["data"] = self.data_path.value.strip()
        if self.info_path.value.strip():
            paths["info_file"] = self.info_path.value.strip()
        if paths:
            config["paths"] = paths
        else:
            config.pop("paths", None)
        cfg_path = os.path.join(self.base_dir, CONFIG_NAME)
        if os.path.exists(cfg_path):
            backup = cfg_path + ".bak"
            with open(cfg_path, encoding="utf-8") as src, open(backup, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        save_config(config, cfg_path)
        self.config = config
        warn = [m for lvl, m in issues if lvl == "warning"]
        cond_cols = [c for c in self.condition_columns if c in table.columns]
        blank = [wl for wl, row in zip(table["well"], table[cond_cols].itertuples(index=False)) if not any(map(str, row))] if cond_cols else []
        if blank and len(blank) < len(table):
            warn.append(f"Wells with no condition set (they share one sample_ID): {blank}")
        self._msg("ok", f"Saved {cfg_path}" + ("<br>Warnings:<br>" + "<br>".join(html.escape(m) for m in warn) if warn else ""))
        with self.out:
            print("Put this line at the top of each pipeline notebook:")
            print(f"CONFIG = r'{cfg_path}'")

    def _msg(self, level, text):
        color = {"error": "#c0392b", "ok": "#1e8449"}.get(level, "#7d6608")
        self.messages.value = f"<div style='color:{color};margin:6px 0'>{text}</div>"


def show_setup_form(folder=""):
    """Display the experiment setup form. ``folder`` pre-fills and loads a folder."""
    form = SetupForm(folder)
    display(form.widget())
    return form
