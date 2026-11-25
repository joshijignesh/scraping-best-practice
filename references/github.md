# Version control and pushing to GitHub (step 10)

## From step 1: local git

```bash
git init -b main
cp <skill>/templates/gitignore .gitignore      # BEFORE the first git add
git add -A && git status                        # read the list: no data/, .venv/, .env, cookies
git commit -m "Scaffold <site> scraper"
```

Commit at every gate: `structure`, `export formats`, `sample approved`, `full run verified`,
`schedule added`.

## Step 10: push to the specific repo

1. **Ask for the exact repo** (`owner/name` or URL) and branch if the user hasn't given them.
   Never guess the owner, never create a repo, and never make one public without being asked.
2. Check access: `gh repo view owner/name` (or `git ls-remote <url>`).
3. If the repo doesn't exist and the user asked you to create it:
   `gh repo create owner/name --private --source . --remote origin`.
4. Otherwise: `git remote add origin git@github.com:owner/name.git` (or `set-url` if it exists).
5. Final review before pushing:
   ```bash
   git status
   git ls-files | grep -E '^data/|\.env|storage_state|cookies|\.log$|\.xlsx$|\.csv$' && echo "STOP: data/secrets tracked"
   ```
   Test fixtures under `tests/fixtures/` are fine to commit (public pages). Scraped exports are
   not, unless the user explicitly wants them in the repo.
6. `git push -u origin <branch>`. If the remote has history, `git pull --rebase origin <branch>`
   first; never force-push without the user saying so.
7. Tag milestones: `git tag -a v0.1-sample -m "Sample approved"`, `v1.0-full`,
   `v1.1-scheduled`; `git push origin --tags`.
8. Report the repo URL, branch, commit hash and tags to the user.

## What goes in the repo

| Commit | Don't commit |
|---|---|
| Code, `tests/`, `tests/fixtures/` | `data/` (captures, runs, exports, logs) |
| `config.toml` (no secrets) | `.venv/`, `__pycache__/` |
| `requirements.txt` (pinned) | `.env`, credentials, `storage_state.json`, cookies |
| `scripts/`, `README.md` | `.scrapy/`, HTTP cache DBs, `JOBDIR` |
| `schedule_approvals.log` | Screenshots of logged-in pages |

Secrets go in `.env` (gitignored) and are read with `os.environ`; document the variable names in
the README and ship a `.env.example`.

## Branching for later changes

Work on a branch (`feat/<change>`), open a PR with `gh pr create`, merge after the sample and
verification pass on the branch. A site-layout fix always comes with its updated fixture and test.
