import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        _client = Groq(api_key=api_key)
    return _client


def chat(prompt: str, system: str = None, model: str = None) -> str:
    """
    Send a prompt to Groq and return the response text.
    """
    client = get_client()
    model = model or os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()


def interpret_command(user_message: str, project_names: list) -> dict:
    """
    Use Groq to interpret a natural language command from the Telegram bot.
    Returns a dict with 'action' and 'params'.
    """
    system = (
        "You are an AI assistant for RepoMind AI running on a Windows laptop. "
        "You interpret natural language messages and extract the intended action and parameters. "
        "Return ONLY a valid JSON object with keys:\n"
        "  'action': one of [analyze, push, list_repos, list_projects, help, unknown]\n"
        "  'params': dict with keys like 'project_path', 'repo_name'\n\n"
        "IMPORTANT path rules for Windows:\n"
        "- Only drive D is allowed; never return paths on C or any other drive.\n"
        "- 'drive D' or 'D drive' means 'D:\\'\n"
        "- Convert natural language folder descriptions to Windows absolute paths.\n"
        "- Example: 'drive D class work openlab drowsiness detection' → 'D:\\Class Work\\openlab\\drowsiness detection'\n"
        "- Example: 'go to D class work open lab drowsiness detection' → 'D:\\Class Work\\open lab\\drowsiness detection'\n"
        "- Preserve spaces in folder names exactly as spoken.\n"
        "- If the user says 'push', 'upload', 'deploy to github', 'send to git' → action is 'push'.\n"
        "- If the user says 'analyze', 'scan', 'check', 'inspect', 'look at' → action is 'analyze'.\n"
        "- For push action, infer repo_name from the last folder name if not explicitly stated.\n"
        "Return ONLY valid JSON. No explanation."
    )
    projects_hint = f"Known local projects: {project_names}" if project_names else ""
    prompt = f"{projects_hint}\n\nUser message: {user_message}"
    result = chat(prompt, system=system)
    import json
    # Strip markdown code fences if present
    result = result.strip().strip('`')
    if result.startswith('json'):
        result = result[4:]
    try:
        return json.loads(result)
    except Exception:
        return {"action": "unknown", "params": {}}


def generate_full_readme(project_data: dict) -> str:
    """
    Use Groq to generate a complete, professional GitHub README.md.
    project_data keys: project_name, frameworks, total_python_files, total_lines_of_code,
                       total_files, total_size_hr, dataset_folders, model_files,
                       folder_structure, dataset_links, description
    """
    name         = project_data.get('project_name', 'My Project')
    frameworks   = project_data.get('frameworks', [])
    py_files     = project_data.get('total_python_files', 0)
    loc          = project_data.get('total_lines_of_code', 0)
    total_files  = project_data.get('total_files', 0)
    size_hr      = project_data.get('total_size_hr', '')
    datasets     = project_data.get('dataset_folders', [])
    model_files  = project_data.get('model_files', [])
    folders      = project_data.get('folder_structure', [])
    dataset_links = project_data.get('dataset_links', {})
    user_desc    = project_data.get('description', '')

    fw_str    = ', '.join(frameworks) if frameworks else 'standard Python libraries'
    ds_names  = [os.path.basename(d['path']) if isinstance(d, dict) else os.path.basename(d)
                 for d in datasets[:5]]
    mdl_names = [os.path.basename(m) for m in model_files[:5]]
    fl_str    = ', '.join(folders[:12]) if folders else 'N/A'
    ds_link_str = '\n'.join(f"- {os.path.basename(p)}: {lnk}" for p, lnk in dataset_links.items()) if dataset_links else 'No external dataset links.'

    prompt = f"""You are a senior software engineer writing a professional GitHub README.md for the project "{name}".

Here is everything known about the project:
- Description hint: {user_desc or '(infer from project name and context)'}
- Frameworks / Libraries detected: {fw_str}
- Python source files: {py_files} files, {loc} lines of code
- Total project files: {total_files} ({size_hr})
- Top-level folders: {fl_str}
- Dataset folders found: {', '.join(ds_names) if ds_names else 'none'}
- Trained model files found: {', '.join(mdl_names) if mdl_names else 'none'}
- Dataset download links:\n{ds_link_str}

Write a COMPLETE, PROFESSIONAL GitHub README.md with ALL of the following sections:

1. # {name} — with a short catchy one-line tagline below the title
2. ![Badges] — add relevant shields.io badge markdown for the detected frameworks/language
3. ## 📌 Overview — 4-6 sentences: what the project does, its real-world purpose, methodology, and key outcome
4. ## ✨ Features — 6-10 bullet points of *specific* technical features (mention model types, accuracy, techniques used)
5. ## 🛠️ Tech Stack — a markdown table: Library | Version | Purpose
6. ## 📁 Project Structure — a code block tree of the actual folder layout (use the provided folder names)
7. ## ⚙️ Installation — numbered steps: git clone, cd, pip install -r requirements.txt, any extras
8. ## 🚀 Usage — concrete example(s) with actual command syntax or short code snippet
9. ## 📊 Dataset — what dataset is used, where to get it, where to place it; include links if provided
10. ## 📈 Results — specific expected outputs, accuracy numbers, confusion matrix mention, demo output
11. ## 🤝 Contributing — brief contributing guide
12. ## 📄 License — MIT

CRITICAL RULES:
- Write REAL, SPECIFIC content — infer *everything* from the project name, folder names, frameworks detected
- NO generic filler like "Feature 1", "describe your project", "results here"
- If project is drowsiness detection → mention EAR ratio, eye aspect ratio, dlib/OpenCV, alarm system, accuracy
- If ML project → mention model architecture, training approach, evaluation metric
- Minimum 100 lines of markdown
- Use proper GitHub Markdown, emojis in headings, and code blocks
- Output ONLY the raw markdown. No preamble or explanation."""

    return chat(prompt, model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'))


def generate_short_description(project_name: str, frameworks: list, folders: list,
                                loc: int = 0, model_files: list = None) -> str:
    """
    Generate a short 1-2 sentence GitHub repo description (max 250 chars).
    """
    fw_str  = ', '.join(frameworks) if frameworks else 'Python'
    fl_str  = ', '.join(folders[:8]) if folders else ''
    mdl_str = ', '.join(os.path.basename(m) for m in (model_files or [])[:3])
    prompt = (
        f"Write a single crisp GitHub repository description (max 200 characters, no markdown) "
        f"for a project called '{project_name}'.\n"
        f"Frameworks: {fw_str}\n"
        f"Top folders: {fl_str}\n"
        f"Model files: {mdl_str or 'none'}\n"
        f"Lines of code: {loc}\n\n"
        f"Output ONLY the description text. No quotes, no markdown, no explanation."
    )
    desc = chat(prompt)
    # Truncate hard at 250 chars for GitHub API
    return desc.strip()[:250]


def generate_project_description(project_name: str, frameworks: list, file_count: int, loc: int) -> str:
    """Legacy shim — kept for backwards compatibility."""
    return generate_full_readme({
        'project_name': project_name,
        'frameworks': frameworks,
        'total_python_files': file_count,
        'total_lines_of_code': loc,
    })
