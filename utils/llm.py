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
        max_tokens=2048,
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


def generate_project_description(project_name: str, frameworks: list, file_count: int, loc: int) -> str:
    """
    Use Groq to generate a smart project description for the README.
    """
    prompt = (
        f"Write a professional 2-sentence project description for a GitHub README. "
        f"Project name: {project_name}. "
        f"Frameworks/libraries used: {', '.join(frameworks) if frameworks else 'none detected'}. "
        f"Total Python files: {file_count}, Lines of code: {loc}. "
        f"Be concise and professional."
    )
    return chat(prompt)
