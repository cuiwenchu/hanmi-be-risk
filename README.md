# Hanmi BE Risk Workbench

Version 2 of the chemical generic-drug bioequivalence risk assessment workbench.

The application compares a reference product and a test product, predicts formulation-development risk, and separates likely API, formulation/process, dissolution, and exposure causes.

## Version 2

- Reference vs Test formulation workbench
- AUC and Cmax T/R ratios with estimated 90% confidence intervals
- Dissolution similarity factor (`f2`)
- API, excipient, process, and PK-exposure risk classification
- Reference-parameter source and confidence labels
- SANOFI 10/10 demonstration dataset
- Formulation optimization candidates and multi-round adjustment suggestions
- Result-aware BE optimization Agent with constrained Test-side proposals and preview recalculation
- Seven-stage originator-development evidence package:
  - RLD/reference identity verification
  - Three or more commercial reference lots
  - Per-API salt, polymorph, PSD, and pH-solubility data
  - Paired pH 1.2/4.5/6.8, FaSSIF, and FeSSIF dissolution profiles
  - Formulation and manufacturing-process operating ranges
  - Pilot/pre-BE Cmax and AUC model calibration
  - BE study design, success probability, and suggested subject count
- Development-readiness score with missing-data priorities and source-aware warnings
- ADMET-AI integration with deterministic fallback
- PBPK simulation through `mrgsolve`
- PK/PD simulation through `RxODE2`
- PostgreSQL-backed users, sessions, tasks, runs, projects, and audit records
- Local Ketcher structure editor assets

## Important Scope

This project is a formulation-development decision-support system. It is not a validated regulatory BE decision engine.

Reference-product values supplied by demonstrations or public literature must not be treated as exact commercial manufacturing parameters. Clinical or regulatory decisions require measured RLD data, model validation, and qualified scientific review.

## Architecture

```text
FastAPI / Uvicorn
├── BE risk workbench
├── ADMET analysis
├── PBPK / PBBM
├── PK/PD and DDI
├── Authentication and audit
└── PostgreSQL persistence
```

Main files:

- `pipeline58_local/app.py`: API routes and web application
- `pipeline58_local/service.py`: ADMET, PBPK, PK/PD, PBBM, and reporting logic
- `pipeline58_local/pbpk_workbench.html`: BE risk workbench UI
- `pipeline58_local/db.py`: PostgreSQL persistence
- `pipeline58_local/auth.py`: authentication and roles
- `pipeline58_local/runners/`: R model runners

## Requirements

- Python 3.11+
- PostgreSQL
- R with `mrgsolve` and `RxODE2` for the preferred simulation backends

Install Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure environment variables using `.env.example` as a reference. The initial administrator password must be supplied through `PIPELINE58_ADMIN_PASSWORD`.

Run:

```bash
uvicorn pipeline58_local.app:app --host 0.0.0.0 --port 8781
```

Open `http://127.0.0.1:8781/`.

## Data Excluded From Git

The repository intentionally excludes:

- User accounts and sessions
- Database credentials
- Analysis inputs and generated results
- Runtime logs
- Server backups
- Proprietary reference-product documents
- Commercial software and Windows VM images

## Optional PK-Sim Integration

Legacy PK-Sim integration code is retained for compatibility, but no PK-Sim Windows VM or commercial installation is included. The main BE workbench operates independently. Any future PK-Sim connection must be configured explicitly through environment variables.
