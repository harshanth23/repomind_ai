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
        "You are an AI assistant for RepoMind AI, a tool that analyzes local projects and pushes them to GitHub. "
        "You receive natural language messages from a user and must identify the intended action. "
        "Return a JSON object with keys: 'action' (one of: analyze, push, list_repos, list_projects, help, unknown) "
        "and 'params' (a dict with relevant parameters like 'project_path', 'repo_name'). "
        "Only return valid JSON, no explanation."
    )
    projects_hint = f"Known local projects: {project_names}" if project_names else ""
    prompt = f"{projects_hint}\n\nUser message: {user_message}"
    result = chat(prompt, system=system)
    import json
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
