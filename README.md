# tokenome-quality-actions

Shared composite actions and gate-drift checker for Tokenome repos.
Single source of truth for quality gates across the Tokenome workspace.

## Actions

| Action | Purpose |
|--------|---------|
| `pre-commit-check` | Checkout + toolchain setup + `pre-commit run --all-files` (check mode). |
| `python-quality` | `ruff format --check`, `isort --check-only`, `ruff check`, `mypy` for uv-managed repos. |
| `node-quality` | `format:check`, `lint`, `tsc --noEmit` for pnpm- or npm-managed repos (autodetected from lockfile). Clears stale `.next` typegen before gating. |

All actions are composite actions, not reusable workflows, so repos can
compose the steps into existing jobs.

## Usage

Consumers pin the major tag `@v1`:

```yaml
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: khodex-rei/tokenome-quality-actions/python-quality@v1
        with:
          python-version: "3.11"
          sync-args: --extra dev
          paths: src tests
```

### pre-commit-check

```yaml
- uses: khodex-rei/tokenome-quality-actions/pre-commit-check@v1
  with:
    language: python        # python or node
    python-version: "3.11"  # for language=python
    sync-args: --extra dev  # for language=python
    node-version: "22"      # for language=node
    working-directory: .
    extra-args: --all-files
```

### python-quality

```yaml
- uses: khodex-rei/tokenome-quality-actions/python-quality@v1
  with:
    python-version: "3.11"
    sync-args: --extra dev
    paths: src tests          # paths for ruff/isort
    mypy-targets: ""          # empty = bare `uv run mypy`
    working-directory: .
```

### node-quality

Package manager is autodetected from the lockfile (`pnpm-lock.yaml` → pnpm,
`package-lock.json` → npm).

```yaml
- uses: khodex-rei/tokenome-quality-actions/node-quality@v1
  with:
    node-version: "22"
    working-directory: .
    app: ""                   # optional workspace scope (pnpm --filter / npm --workspace)
```

## Gate drift checker

`scripts/check_gate_drift.py` asserts per repo:

1. **No duplicated gate commands** in `.github/workflows/*.yml` outside
   `khodex-rei/tokenome-quality-actions` call sites. Any `run:` step
   invoking ruff, isort, mypy, sqlfluff, prettier, eslint, tsc, turbo
   lint/check-types, or `format:check` in a job that does not call the
   shared actions is a finding.
2. **pre-commit hook revs match lockfile versions** for ruff and isort
   (`uv.lock`). If a repo pins `ruff-pre-commit` at `v0.12.0` but
   `uv.lock` has ruff `0.15.11`, that is a finding.

```bash
python scripts/check_gate_drift.py .
python scripts/check_gate_drift.py /path/to/repo
python scripts/check_gate_drift.py --selftest
```

Exits nonzero with named findings on drift.

## Versioning policy

- Releases are tagged `vN` (major) and `vN.M.P` (full).
- Consumers pin the major tag: `@v1`.
- The `v1` tag is a moving pointer to the latest `v1.x.x` release.
- Breaking changes bump the major tag (`v2`).

## Adding a new check

1. Add the check to the appropriate composite action in this repo.
2. Update the README action table and inputs.
3. Bump the full version tag (`v1.0.0` → `v1.1.0`) and move the major
   tag (`v1`) forward.
4. In each consumer repo, run the drift checker to confirm the new
   check does not false-positive on existing workflows.

## Self-hosted CI

This repo runs its own quality gates on itself:

- `pre-commit run --all-files` (see `.pre-commit-config.yaml`).
- `scripts/check_gate_drift.py .` — drift check on this repo.
- `scripts/check_gate_drift.py --selftest` — drift checker self-test.

## License

MIT
