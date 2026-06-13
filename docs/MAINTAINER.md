# Maintainer notes (not for end users)

## Before pushing to GitHub

- `.runtime/` is local-only (~15 GB micromamba env) — never commit it
- Copy `scripts\set_mamma_repo.bat.example` → `set_mamma_repo.bat` for local paths (gitignored)
- Do not save workflows with password fields filled — see [SECURITY.md](../SECURITY.md)
- Run `scripts\verify_clean.bat` before `git push`
