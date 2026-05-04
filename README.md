# OCSF Mapper

A Databricks-hosted Streamlit app that converts vendor security telemetry
samples into Lakewatch presets normalized to the [Open Cybersecurity Schema
Framework (OCSF)](https://ocsf.io). Generated presets are reviewed in-app,
submitted via a staging volume, and automatically opened as PRs against this
repository.

> **Status:** working internal tool. Generates production-quality presets;
> the post-merge deployment to Lakewatch is still manual.

---

## What it does

Onboarding a new security data source to the Lakewatch platform requires
mapping vendor-specific telemetry to the canonical OCSF schema — a process
that today involves reading sample events by hand, identifying the right
OCSF class, writing SQL transforms for the bronze → silver → gold pipeline,
validating output against `schema.ocsf.io`, and iterating until correct.
For a single source this can take hours to days.

OCSF Mapper compresses this loop into an in-app workflow:

| Stage | What the tool does |
|-------|--------------------|
| **Classify** | Profiles the sample's structure and uses Claude to select the appropriate OCSF class UIDs |
| **Fetch schema** | Pulls class attributes from `schema.ocsf.io` and caches them locally |
| **Build preset** | Generates a complete bronze/silver/gold preset using existing presets in the reference library as style anchors |
| **Submit** | User reviews and edits in-app, then submits — the preset is staged on a UC volume and a PR is opened against this repository |

The classification and generation steps use Claude via the `ocsf_mapper`
library; the staging and PR flow are handled by a separate Databricks
notebook documented in [`docs/promoter.md`](docs/promoter.md).

---

## Architecture

<p align="center">
  <img src="architecture.png" alt="OCSF Mapper architecture" width="900" />
</p>

---

## Repository layout

```
tools/ocsf-mapper/
├── README.md
├── app.py                    # Streamlit entrypoint
├── app.yaml                  # Databricks Apps runtime config
├── config.toml               # Streamlit theme
├── requirements.txt          # Python dependencies
├── ocsf_mapper-*.whl         # ocsf_mapper library
└── docs/
    ├── architecture.md       # Data flow diagrams
    └── promoter.md           # Staging + promoter setup
```

---

## Deploying

### Prerequisites

- Databricks workspace with Apps enabled
- Access to `/Volumes/dsl_dev/internal/ocsf_mapper/` (wheel + reference library)
- An Anthropic API key (entered in the app sidebar)

### Deploy from the workspace

1. Clone this repo as a Databricks Git folder (`Workspace → Create → Git folder`).
2. Navigate to `tools/ocsf-mapper/`.
3. Create a new Databricks App, point its source at this folder.
4. Click **Deploy**. Databricks reads `app.yaml`, installs `requirements.txt`, and starts the app.

### Local development

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then enter your Anthropic API key in the sidebar.

---

## Submission flow

When a user clicks **Submit for review**, the app writes three files to the staging volume:

```
/Volumes/dsl_dev/internal/ocsf_mapper/staging/pending/<submission_id>/
├── preset.yaml          # The generated preset (post-edit)
├── report.md            # Generation report (classes, references, token counts)
└── metadata.json        # Submitter identity, OCSF version, classes, timestamp
```

Submission IDs follow the format `<UTC_timestamp>_<vendor>_<source_type>`, e.g.
`20260430T151155Z_snyk_vulnerabilities`.

The promoter (a separate Databricks notebook, not part of this app) drains
`pending/`, opens PRs against this repo, and moves the directory to
`processed/` or `failed/` based on outcome. See `docs/promoter.md` for the
notebook source and runbook.

---

## Configuration

Sidebar settings the user controls:

| Setting | Default | Notes |
|---------|---------|-------|
| Anthropic API key | — | Required; not persisted |
| OCSF version | 1.8.0 | Validated against `schema.ocsf.io` |
| Reference library | `/Volumes/.../preset_library` | Style anchors for generation |
| Output volume | `/Volumes/.../generated_presets` | "Save to Volume" target |
