# OCSF Mapper

A Databricks-hosted compiler for OCSF presets. Point it at a vendor sample, and it produces a complete Lakewatch preset — bronze ingestion, silver field extraction, gold OCSF normalization — ready for review and merge into this repository.

> **Status:** working internal tool. Generates production-quality presets; the post-merge deployment to Lakewatch is still manual.

## Quick Start

Open the app, then in the Generator tab:

```
Sample path:    /Volumes/dsl_dev/internal/ocsf_mapper/samples/snyk_vulns.jsonl
Vendor:         snyk (example)
Source type:    vulnerabilities (example)
[Generate preset]
```

The tool classifies the sample to the relevant OCSF class, fetches the schema, and generates the preset using existing presets in the library as style references. Review and edit in-app, then click **Submit for review** — the preset is staged on a UC volume and a PR is opened against this repository.

## What it does

Onboarding a new security data source to the Lakewatch platform requires mapping vendor-specific telemetry to the canonical OCSF schema — a process that today involves reading sample events by hand, identifying the right OCSF class, writing SQL transforms for the bronze → silver → gold pipeline, validating output against `schema.ocsf.io`, and iterating until correct. For a single source this can take hours to days.

OCSF Mapper compresses this loop into an in-app workflow:

| Stage | What the tool does |
|-------|--------------------|
| **Classify** | Profiles the sample's structure and uses Claude to select the appropriate OCSF class UIDs |
| **Fetch schema** | Pulls class attributes from `schema.ocsf.io` and caches them locally |
| **Build preset** | Generates a complete bronze/silver/gold preset using reference presets in the library as style anchors |
| **Submit** | User reviews and edits in-app, then submits — the preset is staged on a UC volume and a PR is opened against this repository |

## Architecture

<p align="center">
  <img src="architecture.png" alt="OCSF Mapper architecture" width="900" />
</p>

Three layers, separated by a UC volume boundary so submitters never need GitHub credentials:

| Layer | Component | What it does |
|-------|-----------|--------------|
| App | Streamlit (Databricks Apps) | Generates and reviews presets; writes submissions to `staging/pending/` |
| Storage | UC Volume | Hosts vendor samples, the reference preset library, schema cache, and the submission queue |
| Promoter (WIP) | Databricks notebook / job | Drains `staging/pending/`, opens authored PRs against this repo, moves submissions to `processed/` or `failed/` |

The split between submission (app) and promotion (job) means submitters' identities are captured at submission time via Databricks Apps OBO headers, then propagated to git commit `--author`, the PR body, and the preset YAML's attribution header. No shared GitHub PAT is exposed to app users.

## Generation Pipeline

```
              Vendor Sample
                    |
                    v
  Profile (detect format, extract fields)
                    |
                    v
  Classify (Claude picks OCSF class UIDs)
                    |
                    v
  Fetch Schema (schema.ocsf.io --> local cache)
                    |
                    v
  Build Preset (Claude + reference YAMLs as context)
                    |
                    v
          preset.yaml + report.md
```

Each step writes a structured progress event back to the UI, so the user sees classification, schema fetch, and token-by-token preset streaming in real time.

## Submission Flow

When a user clicks **Submit for review**, the app writes three files to the staging volume:

```
/Volumes/dsl_dev/internal/ocsf_mapper/staging/pending/<submission_id>/
├── preset.yaml          # Generated preset, post-edit
├── report.md            # Generation report (classes, references, token counts)
└── metadata.json        # Submitter identity, OCSF version, classes, timestamp
```

Submission IDs follow the format `<UTC_timestamp>_<vendor>_<source_type>` — for example, `20260430T151155Z_snyk_vulnerabilities`.

The promoter notebook drains `pending/`, computes the target file path (`data_sources/lakewatch/<vendor>/<source_type>/preset.yaml`), commits with the submitter as git author, pushes, and opens a PR. On success the submission moves to `processed/` with `pr_url.txt`; on failure it moves to `failed/` with `error.txt`.

See [`docs/promoter.md`](docs/promoter.md) for the full runbook.

## Repository Layout

```
tools/ocsf-mapper/
├── README.md                         # this file
├── app.py                            # Streamlit entrypoint
├── app.yaml                          # Databricks Apps runtime config
├── config.toml                       # Streamlit theme
├── requirements.txt                  # Python dependencies
├── ocsf_mapper-*.whl                 # ocsf_mapper library (bundled)
└── architecture.png              # diagram source above
```

## Configuration

Sidebar settings the user controls:

| Setting | Default | Notes |
|---------|---------|-------|
| Anthropic API key | — | Required; not persisted |
| OCSF version | 1.8.0 | Validated against `schema.ocsf.io` |
| Reference library | `/Volumes/dsl_dev/internal/ocsf_mapper/preset_library` | Style anchors for generation |
| Output volume | `/Volumes/dsl_dev/internal/ocsf_mapper/generated_presets` | "Save to Volume" target |

## Deploying

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Databricks workspace | Apps must be enabled |
| UC Volume access | Read on `/Volumes/dsl_dev/internal/ocsf_mapper/` |
| Anthropic API key | Entered in the sidebar at runtime |

### Deploy from this repo

1. Clone this repository as a Databricks Git folder (`Workspace → Create → Git folder`).
2. Navigate to `tools/ocsf-mapper/`.
3. Create a new Databricks App, pointing its source at this folder.
4. Click **Deploy**. Databricks reads `app.yaml`, installs `requirements.txt`, and starts the app.

### Local development

```
pip install -r requirements.txt
streamlit run app.py
```
