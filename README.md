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

Today, onboarding a new security data source means manually:

1. Reading a vendor sample
2. Mapping fields to OCSF attributes
3. Writing SQL transforms for bronze → silver → gold
4. Validating against `schema.ocsf.io`
5. Iterating until correct

OCSF Mapper compresses this to:

1. Paste a sample path
2. Click Generate
3. Review and edit in-app
4. Click Submit for review
5. PR appears in this repo

The tool uses Claude (via the [`ocsf_mapper`](https://pypi.org/project/ocsf-mapper/)
library) to classify the sample, fetch the relevant OCSF schema, and generate
a complete preset using existing presets in the library as style anchors.

---

## Architecture

```
                      ┌──────────────────────┐
   👤 User      ──►   │  Streamlit app       │   ◄── Claude API
                      │  (Databricks Apps)   │
                      └──────────┬───────────┘
                                 │ writes 3 files
                                 ▼
                      ┌──────────────────────┐
                      │  UC Volume           │
                      │  staging/pending/    │
                      └──────────┬───────────┘
                                 │  ⏱ async (manual or scheduled)
                                 ▼
                      ┌──────────────────────┐
                      │  Promoter            │   ◄── Databricks Secret
                      │  (Databricks job)    │       (GitHub PAT)
                      └──────────┬───────────┘
                                 │ git push + open PR
                                 ▼
                      ┌──────────────────────┐
                      │  This repo —         │   ──► 👥 Reviewer
                      │  PR opened           │
                      └──────────────────────┘
```

The split — submit-to-volume in the app, promote-to-GitHub in a separate job — means submitters don't need GitHub access. The app captures their identity from Databricks Apps OBO headers, the promoter authors commits as them, and PR attribution is preserved end-to-end without exposing a shared GitHub PAT to all users.

See [`docs/architecture.md`](docs/architecture.md) for full data flow and `docs/promoter.md` for the staging/promotion details.

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

---

## Roadmap

- [x] Generate presets from vendor samples
- [x] In-app review and edit
- [x] Staging-volume submission flow with full submitter attribution
- [x] Promoter notebook drains staging → opens PRs
- [ ] Scheduled promoter job (currently manual)
- [ ] OCSF validation in promoter (run validator before opening PR)
- [ ] GitHub Actions deploy on PR merge → Lakewatch
- [ ] Service-account GitHub identity (replace personal PAT)

---

## Owners

- **Tool:** [@ashwin975](https://github.com/ashwin975)
- **Reviewers:** Bee, Sam