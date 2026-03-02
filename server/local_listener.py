import ast
import logging
import os
import subprocess
import sys
import traceback
from datetime import datetime
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
from pydantic import BaseModel
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from agents.scanner import ProjectScanner
from agents.analyzer import ProjectAnalyzer
from agents.decision import DecisionLayer
from agents.readme_generator import ReadmeGenerator
from agents.github_agent import GitHubAgent
from database.db import DatabaseManager
from utils.llm import generate_short_description

app = FastAPI(title="RepoMind AI Local Server")
db = DatabaseManager()


# --- Helpers ---

def _generate_requirements(project_path: str) -> str:
    """
    Generate requirements.txt for a project if it doesn't already exist.
    Tries pipreqs first; falls back to a basic AST import scan.
    Returns 'pipreqs', 'scan', or 'exists'.
    """
    req_path = os.path.join(project_path, 'requirements.txt')
    if os.path.exists(req_path):
        return 'exists'

    # --- Attempt 1: pipreqs ---
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pipreqs.pipreqs', project_path,
             '--force', '--savepath', req_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and os.path.exists(req_path):
            return 'pipreqs'
    except Exception:
        pass

    # --- Attempt 2: basic AST import scan ---
    stdlib = sys.stdlib_module_names if hasattr(sys, 'stdlib_module_names') else set()
    # common stdlib extras for older Python
    stdlib = stdlib | {
        'os', 'sys', 're', 'io', 'abc', 'ast', 'csv', 'copy', 'json',
        'math', 'time', 'uuid', 'enum', 'pathlib', 'typing', 'string',
        'logging', 'hashlib', 'datetime', 'tempfile', 'argparse',
        'threading', 'functools', 'itertools', 'collections', 'subprocess',
        'traceback', 'warnings', 'unittest', 'contextlib', 'dataclasses',
        'pickle', 'struct', 'socket', 'shutil', 'glob', 'fnmatch',
        '__future__', 'builtins', 'types', 'inspect', 'operator',
    }
    found = set()
    for dirpath, dirnames, filenames in os.walk(project_path):
        # skip hidden / venv dirs
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in
                       ('venv', '.venv', 'env', '__pycache__', 'node_modules', '.git')]
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                    tree = ast.parse(fh.read(), filename=fpath)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split('.')[0]
                            if top and top not in stdlib:
                                found.add(top)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            top = node.module.split('.')[0]
                            if top and top not in stdlib:
                                found.add(top)
            except Exception:
                pass

    if found:
        with open(req_path, 'w') as fh:
            for pkg in sorted(found):
                fh.write(pkg + '\n')
        return 'scan'
    return 'scan'


# --- Request Models ---
class AnalyzeRequest(BaseModel):
    project_path: str
    exclude_paths: list = []

class PushRequest(BaseModel):
    project_path: str
    repo_name: str
    description: str = ""
    commit_message: str = "Initial commit"
    private: bool = False
    use_existing: bool = False
    dataset_links: dict = {}
    project_info: dict = {}

class DatasetLinkRequest(BaseModel):
    project_path: str
    dataset_path: str
    link: str


# --- Endpoints ---
@app.post('/analyze')
def analyze(req: AnalyzeRequest):
    if not os.path.isdir(req.project_path):
        raise HTTPException(status_code=400, detail=f"Path not found: {req.project_path}")

    scanner = ProjectScanner(req.project_path, exclude_paths=req.exclude_paths)
    scan_result = scanner.scan()

    analyzer = ProjectAnalyzer(req.project_path, exclude_paths=req.exclude_paths)
    analysis_result = analyzer.analyze()

    prefs = db.get_preferences()
    decision = DecisionLayer(db=db)
    decisions = decision.decide(scan_result, analysis_result, prefs)

    # Save to DB
    project_name = os.path.basename(req.project_path)
    project_id = db.upsert_project(
        name=project_name,
        path=req.project_path,
        total_size=scan_result['total_size'],
        last_analyzed=datetime.now().isoformat()
    )
    for ds in scan_result.get('dataset_folders', []):
        db.upsert_dataset(project_id, ds['path'], ds['size'])

    return {
        "project_name": project_name,
        "scan": scan_result,
        "analysis": analysis_result,
        "decisions": decisions,
    }


@app.post('/push')
def push(req: PushRequest):
    try:
        return _push_impl(req)
    except HTTPException:
        raise
    except Exception as e:
        logging.error("PUSH 500 EXCEPTION:\n" + traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


def _push_impl(req: PushRequest):
    token = os.getenv('GITHUB_TOKEN')
    username = os.getenv('GITHUB_USERNAME')
    if not token or not username:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN or GITHUB_USERNAME not set in .env")

    agent = GitHubAgent(token=token, username=username)

    # Quick scan+analyze to feed real data into README and description
    try:
        _scanner  = ProjectScanner(req.project_path)
        _scan     = _scanner.scan()
        _analyzer = ProjectAnalyzer(req.project_path)
        _analysis = _analyzer.analyze()
    except Exception:
        _scan = {}
        _analysis = {}

    # Auto-generate a meaningful GitHub repo description via Groq
    _frameworks = _analysis.get('detected_frameworks', [])
    _loc        = _analysis.get('total_lines_of_code', 0)
    _model_files = _analysis.get('model_files', [])
    _folders = []
    try:
        _folders = sorted([
            d for d in os.listdir(req.project_path)
            if os.path.isdir(os.path.join(req.project_path, d)) and not d.startswith('.')
        ])
    except Exception:
        pass
    auto_desc = req.description
    if not auto_desc:
        try:
            auto_desc = generate_short_description(
                req.repo_name, _frameworks, _folders, _loc, _model_files
            )
        except Exception:
            auto_desc = ''

    # Create or verify GitHub repo
    if not req.use_existing:
        try:
            agent.create_repo(req.repo_name, description=auto_desc, private=req.private)
        except Exception as e:
            err = str(e)
            if "already exists" in err.lower() or "422" in err:
                # Repo already exists — update the description
                try:
                    agent.update_repo(req.repo_name, auto_desc)
                except Exception:
                    pass
            else:
                raise HTTPException(status_code=500, detail=err)
    else:
        if not agent.repo_exists(req.repo_name):
            raise HTTPException(status_code=404, detail=f"Repo '{req.repo_name}' not found on GitHub")
        # Update description on existing repo too
        try:
            agent.update_repo(req.repo_name, auto_desc)
        except Exception:
            pass

    # Generate README with all real project data
    project_info = req.project_info or {}
    project_info['project_name']        = project_info.get('project_name', req.repo_name)
    project_info['project_path']        = req.project_path
    project_info['dataset_links']       = req.dataset_links
    project_info['description']         = auto_desc
    project_info['detected_frameworks'] = _frameworks
    project_info['total_python_files']  = _analysis.get('total_python_files', 0)
    project_info['total_lines_of_code'] = _loc
    project_info['model_files']         = _model_files
    project_info['total_files']         = _scan.get('total_files', 0)
    project_info['total_size_hr']       = _scan.get('total_size_hr', '')
    project_info['dataset_folders']     = _scan.get('dataset_folders', [])
    readme_gen = ReadmeGenerator(project_info)
    readme_path = os.path.join(req.project_path, 'README.md')
    readme_gen.generate(output_path=readme_path)

    # Auto-generate requirements.txt if missing
    _generate_requirements(req.project_path)

    # Push
    try:
        result = agent.push_repo(
            repo_path=req.project_path,
            repo_name=req.repo_name,
            commit_message=req.commit_message,
            exclude_paths=list(req.dataset_links.keys()) if req.dataset_links else None,
            use_existing=req.use_existing
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result


@app.get('/repos')
def get_repos():
    token = os.getenv('GITHUB_TOKEN')
    username = os.getenv('GITHUB_USERNAME')
    if not token or not username:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN or GITHUB_USERNAME not set in .env")
    agent = GitHubAgent(token=token, username=username)
    repos = agent.list_repos()
    return [{"name": r['name'], "url": r['html_url'], "private": r['private']} for r in repos]


@app.get('/repo_info/{repo_name}')
def repo_info(repo_name: str):
    token = os.getenv('GITHUB_TOKEN')
    username = os.getenv('GITHUB_USERNAME')
    if not token or not username:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN or GITHUB_USERNAME not set in .env")
    agent = GitHubAgent(token=token, username=username)
    try:
        info = agent.get_repo_info(repo_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return info


@app.get('/local_projects')
def local_projects():
    return db.get_all_projects()


@app.post('/dataset_link')
def set_dataset_link(req: DatasetLinkRequest):
    project = db.get_project_by_name(os.path.basename(req.project_path))
    if not project:
        raise HTTPException(status_code=404, detail="Project not analyzed yet. Run /analyze first.")
    db.update_dataset_link(project['id'], req.dataset_path, req.link)
    return {"status": "updated", "dataset": req.dataset_path, "link": req.link}

