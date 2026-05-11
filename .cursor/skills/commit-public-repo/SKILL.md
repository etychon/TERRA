---
name: commit-public-repo
description: >-
  Verifies TERRA is safe to push to a public GitHub repo, summarizes all changes
  since HEAD, and creates a git commit. Use when the user invokes /commit or asks
  to commit with public-repo readiness checks before merging to main.
disable-model-invocation: true
---

# commit-public-repo

## Verbatim workflow (from product owner)

1. Verify the code is ready to be committed to a public repo.
2. Write a short summary of the changes since the last commit.
3. Commit the code change.

## Instructions (agent)

### 1) Verify public readiness

From the repository root, run:

```bash
bash .cursor/skills/commit-public-repo/scripts/verify-public-ready.sh
```

If it fails, **stop**: fix failures, then restart this workflow. Do not commit.

**Manual gates** (script does not replace judgment):

- **No secrets:** reject staging if paths include `.env`, private keys, tokens, or customer exports. If unsure, stop and ask the user.
- **No accidental artifacts:** do not stage `node_modules/`, `.venv/`, `dist/`, coverage HTML, or machine-specific junk (see `.gitignore`).

### 2) Summarize since last commit

Produce a **short** summary for the commit message body (3–6 bullets max). Base it on:

```bash
git status --short
git diff --stat HEAD
```

If there is **no** change vs `HEAD`, report that and **do not** run `git commit`.

### 3) Commit

1. Stage only intentional paths (`git add …`). Prefer explicit paths over blind `git add -A` unless the user confirmed a full-tree commit.
2. Re-run `git diff --cached --stat` and ensure the summary still matches what is staged.
3. Commit using **Conventional Commit** style title + body:

```text
<type>(<scope>): <imperative title ≤72 chars>

- <bullet tied to a real change>
- …
```

Use types such as `feat`, `fix`, `docs`, `chore`, `ci`, `test`, `refactor`. For this repo, `scope` is optional (`frontend`, `ci`, `specs`, …).

Example:

```text
docs(readme): clarify Node version for npm tooling

- Note Node 18+ with 20 LTS recommended
- Document engines field on root package.json
```

4. Run `git status` after commit; working tree should be clean except deliberate untracked files.

## Additional resources

- Repo conventions: `AGENTS.md`
- Pre-PR checklist items also apply before a public commit.
