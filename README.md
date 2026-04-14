# OCSF Mapper Tool

A Streamlit-based **Databricks App** for mapping raw security telemetry (logs, events, alerts) to the [Open Cybersecurity Schema Framework (OCSF)](https://ocsf.io). Paste in a sample payload, pick a target OCSF class, and get back a normalized event plus a reusable mapping you can drop into your Lakewatch silver layer.

Built on top of the [`ocsf_mapper`](https://pypi.org/project/ocsf-mapper/) Python package and deployed as a [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html).

---

## What it does

- **Ingests** a raw event sample (JSON, syslog, CEF, etc.)
- **Suggests** the right OCSF class (e.g. `Authentication`, `Network Activity`, `File System Activity`) based on the payload shape
- **Maps** source fields to OCSF attributes, with LLM-assisted suggestions for ambiguous fields
- **Exports** the mapping as a reusable config (YAML/SQL) for use in silver-layer transformations or Lakewatch presets
- **Validates** the output against the OCSF schema

---

## Repository layout

```
.
├── app.py                              # Streamlit entrypoint
├── app.yaml                            # Databricks Apps runtime config
├── config.toml                         # Streamlit theme/config
├── requirements.txt                    # Python dependencies
└── ocsf_mapper-0.3.0-py3-none-any.whl  # Bundled ocsf_mapper package
```

### `app.yaml`
Tells Databricks Apps how to launch the app:

```yaml
command:
  - streamlit
  - run
  - app.py
  - --server.port
  - "8000"
  - --server.address
  - "0.0.0.0"
```

### `requirements.txt`
The app depends on:
- `streamlit>=1.30` — UI framework
- `databricks-sdk>=0.30` — workspace / Unity Catalog access
- `ocsf_mapper` — the mapping engine (installed from a UC Volume wheel at `/Volumes/dsl_dev/internal/ocsf_mapper/`)

---

## Prerequisites

- A Databricks workspace with **Databricks Apps** enabled
- Access to the Unity Catalog volume hosting the `ocsf_mapper` wheel (`/Volumes/dsl_dev/internal/ocsf_mapper/`)
- An LLM API key (entered via the app sidebar — not set as an env var)

---

## Deploying to Databricks

### Option 1: Deploy from this repo (recommended)

1. In Databricks, go to **Workspace → Create → Git folder** and clone this repository.
2. Open **Compute → Apps → Create App**.
3. Point the app source at the cloned repo path (`/Workspace/Repos/<you>/OCSF-Mapper-Tool`).
4. Click **Deploy**. Databricks will read `app.yaml`, install `requirements.txt`, and start the app.

### Option 2: Deploy via the Databricks CLI

```bash
databricks apps deploy ocsf-mapper-tool \
  --source-code-path /Workspace/Repos/<you>/OCSF-Mapper-Tool
```

---

## Running locally

You can also run the Streamlit app outside Databricks for development:

```bash
pip install -r requirements.txt
# If the wheel path in requirements.txt isn't accessible locally,
# install ocsf_mapper from a local copy of the .whl file instead:
pip install ./ocsf_mapper-0.3.0-py3-none-any.whl

streamlit run app.py
```

Then open http://localhost:8501 and enter your API key in the sidebar.

---

## Using the tool

1. **Paste a raw event** into the input panel (JSON, key-value, CEF, syslog, etc.).
2. **Select a target OCSF class** — or let the tool auto-suggest one.
3. **Review the suggested field mapping.** Edit, confirm, or override individual mappings.
4. **Export** the mapping as:
   - A YAML mapping block (for Lakewatch presets)
   - A SQL `SELECT` for bronze → silver transforms
   - A normalized sample event for validation

---

## Notes for Rearc / Lakewatch users

This tool is designed to complement the [`security-content-library`](https://github.com/rearc/security-content-library) preset workflow. Mappings exported from here can be dropped directly into `data_sources/lakewatch/<vendor>/<source_type>/preset.yaml` silver transforms, following the same OCSF conventions as the Wiz reference preset.

---

## Roadmap

- [ ] Bulk mapping from sample files in a UC volume
- [ ] Preset-aware export (auto-generate full `preset.yaml` stubs)
- [ ] OCSF version selector (currently pinned to the version bundled with `ocsf_mapper`)
- [ ] CI validation of exported mappings against OCSF schema

---

## License

Internal Rearc tooling. Not for public distribution.
