# RepoMind AI

AI-assisted local project analyzer and GitHub publisher controlled through a Telegram bot.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-API-green)
![Telegram](https://img.shields.io/badge/Telegram-Bot-2CA5E0)
![SQLite](https://img.shields.io/badge/SQLite-Local%20DB-003B57)

## Overview

RepoMind AI helps you inspect local projects, detect datasets and large files, summarize codebase characteristics, and push repositories to GitHub with minimal manual steps.  
It runs a local FastAPI server plus a Telegram bot interface, and uses Groq LLM prompts for natural-language command interpretation and README/description generation.

The current implementation is restricted to **D:\\ paths only** for browse/analyze/push operations.

---

## Features

- Interactive folder browsing from Telegram with inline buttons.
- Natural-language intent parsing (`analyze`, `push`, `list_repos`, `list_projects`, `help`).
- Project scanning with:
  - total size and file count,
  - large file detection (>100 MB),
  - large folder detection (>1 GB),
  - dataset-folder heuristics.
- Code analysis with:
  - Python file count and LOC,
  - detected ML frameworks from imports/`requirements.txt`,
  - model artifact detection (`.pt`, `.pth`, `.h5`, `.onnx`, etc.),
  - Git repository status.
- Exclusion flow for selected subfolders before analyze/push.
- GitHub automation:
  - create new repository or push to existing,
  - update repo description,
  - commit and push via `GitPython`.
- Auto README generation pipeline via `ReadmeGenerator` (LLM-first with fallback template).
- Local persistence using SQLite (`projects`, `datasets`, `user_preferences`).

---

## Project Structure

```text
repomind_ai/
├── agents/
│   ├── analyzer.py
│   ├── decision.py
│   ├── github_agent.py
│   ├── readme_generator.py
│   └── scanner.py
├── config/
│   └── README.txt
├── database/
│   ├── db.py
│   └── README.txt
├── server/
│   ├── local_listener.py
│   └── telegram_bot.py
├── utils/
│   ├── fuzzy_match.py
│   ├── llm.py
│   └── size_calculator.py
├── .env
├── .gitignore
├── main.py
├── README.md
└── requirements.txt
```

---

## Tech Stack

- **Backend API:** FastAPI, Uvicorn
- **Bot Interface:** `python-telegram-bot`
- **LLM Provider:** Groq (`groq` Python SDK)
- **GitHub Integration:** GitHub REST API + GitPython
- **Database:** SQLite (`sqlite3`)
- **Matching Utility:** RapidFuzz

---

## Installation

1. Clone the repository:

   ```bash
   git clone <your-repo-url>
   cd repomind_ai
   ```

2. Create and activate your environment (example with Conda):

   ```bash
   conda create -n dwenv python=3.11 -y
   conda activate dwenv
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create `.env` in `repomind_ai/` with the required keys:

   ```env
   SERVER_HOST=0.0.0.0
   SERVER_PORT=8000

   TELEGRAM_BOT_TOKEN=your_telegram_bot_token

   GITHUB_TOKEN=your_github_personal_access_token
   GITHUB_USERNAME=your_github_username

   GROQ_API_KEY=your_groq_api_key
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

---

## Running the App

### Option A: Full mode (Server + Telegram Bot)

```bash
python main.py
```

Behavior:
- Starts FastAPI in a background thread.
- Starts Telegram bot in the main thread if `TELEGRAM_BOT_TOKEN` is configured.

### Option B: API-only mode

If bot token is missing, `main.py` keeps only the local API server running.

You can also run API directly:

```bash
uvicorn server.local_listener:app --host 0.0.0.0 --port 8000
```

---

## Telegram Bot Commands

- `/start` – open main menu
- `/browse` – browse folders
- `/analyze <project_path>` – analyze a project
- `/push <project_path> <repo_name>` – push to GitHub
- `/repos` – list GitHub repositories
- `/projects` – list analyzed projects
- `/help` – show command help
- `/cancel` – cancel current flow

Natural-language examples:
- `Go to Drive D`
- `Analyze D:\\Class Work\\MyProject`
- `Push D:\\Class Work\\MyProject to GitHub`

> Note: non-`D:\\` paths are rejected by both bot and backend.

---

## REST API Endpoints

Base URL: `http://localhost:8000`

- `POST /analyze`
  - body: `{"project_path": "D:\\\\...", "exclude_paths": []}`
  - returns scan + analysis + decision payload

- `POST /push`
  - body includes:
    - `project_path`, `repo_name`, `commit_message`,
    - `use_existing`, `private`, `dataset_links`, `project_info`
  - creates/updates repo and pushes local code

- `GET /repos`
  - list GitHub repos for configured user

- `GET /repo_info/{repo_name}`
  - repository metadata/insights

- `GET /local_projects`
  - list analyzed projects stored in SQLite

- `POST /dataset_link`
  - store replacement dataset link for analyzed project

---

## Data Model (SQLite)

Database file is managed in `database/` (ignored by `.gitignore`).

Tables:
- `projects` (`id`, `name`, `path`, `total_size`, `last_analyzed`)
- `datasets` (`id`, `project_id`, `dataset_path`, `dataset_size`, `replacement_link`)
- `user_preferences` (`id`, `auto_exclude_threshold`, `default_dataset_action`)

---

## README Generation Flow

When pushing:
1. Project is scanned and analyzed.
2. A short GitHub repo description is generated via Groq.
3. `ReadmeGenerator` attempts full LLM README generation.
4. If LLM fails, a fallback template README is used.
5. README is written to target project if missing (or if old stub is detected).

---

## Security & Operational Notes

- Keep `.env` private and never commit tokens.
- Dataset/model/large binary patterns are ignored via `.gitignore`.
- Project path handling is intentionally restricted to `D:\\`.
- Force-push is used in current `GitHubAgent.push_repo` workflow (`HEAD:main --force`).

---

## Known Limitations

- Windows-focused path handling.
- Depends on external services (Groq + GitHub APIs).
- Error handling in some flows is intentionally minimal for speed.

---

## License

MIT (recommended). Add a `LICENSE` file if you want an explicit license declaration.
