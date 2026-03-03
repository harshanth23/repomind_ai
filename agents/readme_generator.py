import os
from datetime import datetime

try:
    from utils.llm import generate_full_readme
    LLM_AVAILABLE = True
except Exception:
    LLM_AVAILABLE = False


class ReadmeGenerator:
    def __init__(self, project_info: dict, use_llm: bool = True):
        self.project_info = project_info
        self.use_llm = use_llm and LLM_AVAILABLE

    def generate(self, output_path: str = None) -> str:
        info = self.project_info
        name = info.get('project_name', 'My Project')
        year = datetime.now().year

        readme_content = None

        # --- LLM path: generate the entire README ---
        if self.use_llm:
            try:
                # Build top-level folder list from scan data if available
                root_path = info.get('project_path', '')
                folder_structure = []
                if root_path and os.path.isdir(root_path):
                    try:
                        folder_structure = sorted([
                            d for d in os.listdir(root_path)
                            if os.path.isdir(os.path.join(root_path, d))
                            and not d.startswith('.')
                            and d not in ('__pycache__', '.git', 'venv', '.venv', 'env', 'node_modules')
                        ])
                    except Exception:
                        folder_structure = []

                project_data = {
                    'project_name':        name,
                    'description':         info.get('description', ''),
                    'frameworks':          info.get('detected_frameworks', []),
                    'total_python_files':  info.get('total_python_files', 0),
                    'total_lines_of_code': info.get('total_lines_of_code', 0),
                    'total_files':         info.get('total_files', 0),
                    'total_size_hr':       info.get('total_size_hr', ''),
                    'dataset_folders':     info.get('dataset_folders', []),
                    'model_files':         info.get('model_files', []),
                    'folder_structure':    folder_structure,
                    'dataset_links':       info.get('dataset_links', {}),
                }
                readme_content = generate_full_readme(project_data)
            except Exception:
                readme_content = None

        # --- Fallback: build a decent template if LLM unavailable or failed ---
        if not readme_content:
            frameworks   = info.get('detected_frameworks', [])
            dataset_links = info.get('dataset_links', {})
            lines = []
            lines.append(f"# {name}\n")
            lines.append(f"> Auto-generated README for **{name}**\n")
            if frameworks:
                lines.append(f"**Frameworks:** {', '.join(frameworks)}\n")
            lines.append("## Installation\n")
            lines.append("```bash")
            lines.append(f"git clone https://github.com/<your-username>/{name}.git")
            lines.append(f"cd {name}")
            lines.append("pip install -r requirements.txt")
            lines.append("```\n")
            lines.append("## Usage\n")
            lines.append("```bash")
            lines.append("python main.py")
            lines.append("```\n")
            if dataset_links:
                lines.append("## Dataset\n")
                for ds_path, link in dataset_links.items():
                    lines.append(f"- [{os.path.basename(ds_path)}]({link})")
                lines.append("")
            lines.append("## License\n")
            lines.append(f"MIT License © {year}\n")
            readme_content = "\n".join(lines)

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
        return readme_content

