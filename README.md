# GitHub Downloader Bot

A Telegram bot for searching GitHub repositories and downloading repository source code and release assets.

## Requirements

- **Python 3.12 (recommended)**. Use the same version as CI to maximize availability of prebuilt Windows wheels for native dependencies such as `aiohttp` and `pydantic-core`.
- A Telegram bot token
- Optional: a GitHub personal access token for authenticated GitHub API requests

## Local setup (Windows PowerShell)

Check that the Python 3.12 launcher is installed:

```powershell
py -3.12 --version
```

Create a clean virtual environment and install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --prefer-binary -e ".[test]"
```

If PowerShell blocks activation, you can skip activation and run:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --prefer-binary -e ".[test]"
```

If you already created `.venv` with a different Python version, remove that environment first and recreate it with `py -3.12 -m venv .venv`. Do not install into an environment created by another Python version.

## Linux/macOS setup

1. Create and activate a Python 3.12 virtual environment.
2. Install the project and test dependencies:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install --prefer-binary -e '.[test]'
   ```

3. Create a `.env` file in the project root:

   ```dotenv
   BOT_TOKEN=your_telegram_bot_token
   GITHUB_TOKEN=
   USE_LOCAL_BOT_API=false
   LOCAL_BOT_API_URL=http://127.0.0.1:8081
   MAX_CONCURRENT_JOBS=1
   MAX_QUEUE_SIZE=100
   MAX_DOWNLOAD_MB=49
   USE_SQLITE_WORKER_GATEWAY=false
   ```

   Keep real tokens out of Git. Do not commit `.env`.

4. Start the bot:

   ```bash
   python bot.py
   ```

Do not run two polling instances with the same Telegram bot token at the same time.

## Worker persistence migration

The default worker path remains the legacy persistence facade. The new SQLite worker gateway is opt-in:

```dotenv
USE_SQLITE_WORKER_GATEWAY=true
```

Do not enable this in production until the full test suite and a controlled smoke test have passed. See [the worker migration plan](docs/worker-migration-plan.md). The architecture PR has not been deployed to the VPS.

## Tests and CI

Run checks locally with:

```bash
python -m compileall -q bot.py handlers keyboards repositories services workers src tests
python -m pytest -q
```

On Windows, use the Python 3.12 environment created above. The GitHub Actions workflow is currently configured for manual dispatch only; pushes and pull requests do not start it automatically.

## Architecture

The codebase is being migrated toward domain, application, infrastructure, and worker layers. See [ARCHITECTURE.md](ARCHITECTURE.md) for the current boundaries and [the migration plan](docs/worker-migration-plan.md) for rollout safeguards.
