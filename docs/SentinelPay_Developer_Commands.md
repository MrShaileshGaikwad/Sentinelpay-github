import pypandoc, os
from pathlib import Path

content = r"""# SentinelPay – Developer Commands & Local Runbook

This document contains the common commands for working on the SentinelPay Django project in Windows PowerShell / VS Code.

> **Project safety:** The local `MYBANK` MySQL database contains existing data. The development setup should use the project's default SQLite database unless you intentionally configure a separate test/development MySQL database. Do not run migrations, resets, deletes, or schema changes against `MYBANK`.

## 1. Project locations

Repository root:

```powershell
C:\Users\Shree\Downloads\MCA project\Sentinelpay-github
```

Django project folder (contains `manage.py`):

```powershell
C:\Users\Shree\Downloads\MCA project\Sentinelpay-github\sentinelpay
```

Open the repository root in VS Code. Run Git commands from the repository root. Run Django management commands from the `sentinelpay` folder.

## 2. Open the project and activate the virtual environment

```powershell
cd "C:\Users\Shree\Downloads\MCA project\Sentinelpay-github"
.\.venv\Scripts\Activate.ps1
cd .\sentinelpay
```

Confirm Python and pip:

```powershell
python --version
python -m pip --version
```

If PowerShell blocks activation, use this for the current terminal session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Prefer the project's existing `.venv`. The previously configured GitHub Actions workflow uses Python 3.12; verify the virtual environment's Python version before installing dependencies.

## 3. Install dependencies

Run from the `sentinelpay` folder:

```powershell
python -m pip install -r requirements.txt
```

Upgrade pip if needed:

```powershell
python -m pip install --upgrade pip
```

## 4. Select the safe local development database

The project was previously tested with its default SQLite configuration. To remove a PowerShell environment override for this terminal session:

```powershell
Remove-Item Env:DB_ENGINE -ErrorAction SilentlyContinue
```

Check the Django configuration:

```powershell
python manage.py check
```

**Important:** Removing this environment variable does not change the project's settings file. Confirm that `sentinelpay/settings.py` defaults to SQLite before running migrations. Do not set `DB_ENGINE=mysql` for this local run if that would connect to the existing `MYBANK` schema.

## 5. Database commands – use carefully

Check migrations:

```powershell
python manage.py showmigrations
```

See migration SQL without applying it:

```powershell
python manage.py sqlmigrate banking 0001
```

Apply migrations only to the confirmed local development database (normally SQLite):

```powershell
python manage.py migrate
```

Create a migration after changing Django models:

```powershell
python manage.py makemigrations
```

Inspect database configuration and tables before any database operation. Never use `flush`, `reset_db`, `DROP DATABASE`, `DROP TABLE`, or destructive migration commands against `MYBANK`.

## 6. Create an administrator account

Run from the folder containing `manage.py`:

```powershell
python manage.py createsuperuser
```

Then open:

```text
http://127.0.0.1:8000/admin/
```

A Django superuser is not necessarily a customer with a bank account. Creating a superuser does not automatically create a customer profile, account, or beneficiary.

## 7. Run the application

```powershell
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

Admin:

```text
http://127.0.0.1:8000/admin/
```

Stop the server with `Ctrl+C` in the terminal running the server.

To use another local port:

```powershell
python manage.py runserver 8001
```

## 8. Test and validate the project

Run Django system checks:

```powershell
python manage.py check
```

Run the test suite (from the Django project folder):

```powershell
python -m pytest -v
```

Run Django's built-in test runner:

```powershell
python manage.py test
```

The project previously passed 46 pytest tests using SQLite. Re-run tests after pulling new code; results may change as the code evolves.

## 9. Git commands – inspect changes before pulling

Run these from the **repository root**, not from the inner `sentinelpay` folder.

Check current branch and working tree:

```powershell
git status
git branch --show-current
```

See configured remotes:

```powershell
git remote -v
```

Download remote commit information without changing local files:

```powershell
git fetch origin
```

List commits on GitHub's `main` branch that are not in the current local `HEAD`:

```powershell
git log --oneline HEAD..origin/main
```

Show changed-file summary:

```powershell
git diff --stat HEAD..origin/main
```

Show actual incoming code differences:

```powershell
git diff HEAD..origin/main
```

Show commits in a compact graph:

```powershell
git log --oneline --decorate --graph -15
```

Show files changed by the latest commit:

```powershell
git show --stat --oneline HEAD
```

Show the latest commit's full patch:

```powershell
git show HEAD
```

Compare local branch with remote branch:

```powershell
git status -sb
```

## 10. Safely update local code from GitHub

First inspect your local changes:

```powershell
git status
```

If you have local changes, commit them or stash them before pulling. Do not discard work you need.

Optional: save tracked and untracked changes temporarily:

```powershell
git stash push -u -m "before updating SentinelPay"
```

Fetch and inspect:

```powershell
git fetch origin
git log --oneline HEAD..origin/main
git diff --stat HEAD..origin/main
git diff HEAD..origin/main
```

Only after reviewing the changes and confirming the working tree is safe:

```powershell
git pull --ff-only origin main
```

If you created a stash and want to restore it:

```powershell
git stash list
git stash pop
```

If `git pull --ff-only` reports that branches have diverged, stop and inspect the branch history; do not force-pull or reset blindly.

## 11. After pulling new code

From the repository root:

```powershell
git status
```

Then enter the Django folder and activate the environment if needed:

```powershell
cd .\sentinelpay
..\ .venv\Scripts\Activate.ps1
```

The activation command above should normally be entered without a space between `..` and `.venv`:

```powershell
..\.venv\Scripts\Activate.ps1
```

Install any updated dependencies:

```powershell
python -m pip install -r requirements.txt
```

Check and test:

```powershell
python manage.py check
python -m pytest -v
```

Review migrations before applying them. Apply only to the confirmed local development database:

```powershell
python manage.py showmigrations
python manage.py migrate
```

Start the app:

```powershell
python manage.py runserver
```

## 12. Useful troubleshooting commands

Confirm current directory:

```powershell
Get-Location
```

List files:

```powershell
Get-ChildItem
```

Confirm `manage.py` exists:

```powershell
Test-Path .\manage.py
```

Find Python executable:

```powershell
where.exe python
python -c "import sys; print(sys.executable)"
```

Check installed Django and pytest:

```powershell
python -m django --version
python -m pytest --version
```

Check whether the local server port is in use:

```powershell
netstat -ano | findstr :8000
```

## 13. Recommended daily workflow

1. Open the repository root in VS Code.
2. Run `git status`.
3. Run `git fetch origin`.
4. Review incoming commits and code differences.
5. Safely pull with `git pull --ff-only origin main`.
6. Activate `.venv` and enter `sentinelpay`.
7. Install updated requirements if needed.
8. Run `python manage.py check`.
9. Run `python -m pytest -v`.
10. Review migrations and apply only to the safe development database.
11. Run `python manage.py runserver`.
12. Test registration, login, account linking, beneficiaries, payments, fraud decisions and transaction history.

## 14. Quick command reference

| Task | Command |
|---|---|
| Activate environment (repository root) | `.\.venv\Scripts\Activate.ps1` |
| Enter Django folder | `cd .\sentinelpay` |
| Install dependencies | `python -m pip install -r requirements.txt` |
| Django check | `python manage.py check` |
| View migrations | `python manage.py showmigrations` |
| Apply safe local migrations | `python manage.py migrate` |
| Create admin | `python manage.py createsuperuser` |
| Run tests | `python -m pytest -v` |
| Start server | `python manage.py runserver` |
| Check Git status (repo root) | `git status` |
| Fetch GitHub changes | `git fetch origin` |
| List incoming commits | `git log --oneline HEAD..origin/main` |
| Compare incoming files | `git diff --stat HEAD..origin/main` |
| Review incoming code | `git diff HEAD..origin/main` |
| Pull safely | `git pull --ff-only origin main` |

## 15. Important project safety rules

- Run Git commands from the repository root.
- Run Django commands from the folder containing `manage.py`.
- Do not commit `.venv`, passwords, secret keys, `.env` files, database files or database dumps.
- Do not run migrations against the existing local `MYBANK` database.
- Do not run destructive database commands.
- Keep local development data separate from any future cloud database.
- Review code and migration changes before applying them.
- Never use `git reset --hard`, `git clean -fd`, or force-push unless you fully understand the consequences and have a backup.

---

**Document purpose:** Local development, Git update inspection, testing and safe operation of the SentinelPay academic project.

**Last reviewed:** 31 October 2026. Verify project paths, branch name, Python version and database settings if the project structure changes.
"""
out = "/mnt/data/SentinelPay_Developer_Commands.md"
pypandoc.convert_text(content, "md", format="md", outputfile=out, extra_args=["--standalone"])
print(out, os.path.getsize(out))
