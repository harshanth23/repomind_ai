import os
from datetime import datetime

try:
    from utils.llm import generate_project_description
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
        description = info.get('description', '')
        if not description and self.use_llm:
            try:
                description = generate_project_description(
                    project_name=name,
                    frameworks=info.get('detected_frameworks', []),
                    file_count=info.get('total_python_files', 0),
                    loc=info.get('total_lines_of_code', 0)
                )
            except Exception:
                description = 'No description provided.'
        if not description:
            description = 'No description provided.'
        features = info.get('features', [])
        install_steps = info.get('installation_steps', ['pip install -r requirements.txt'])
        usage = info.get('usage_example', 'python main.py')
        dataset_links = info.get('dataset_links', {})
        results = info.get('results', 'No results documented yet.')
        license_type = info.get('license', 'MIT')
        frameworks = info.get('detected_frameworks', [])
        year = datetime.now().year

        lines = []
        lines.append(f"# {name}\n")
        lines.append(f"{description}\n")
        if frameworks:
            lines.append(f"**Frameworks:** {', '.join(frameworks)}\n")
        lines.append("## Features\n")
        if features:
            for feat in features:
                lines.append(f"- {feat}")
        else:
            lines.append("- Feature 1")
            lines.append("- Feature 2")
        lines.append("")
        lines.append("## Installation\n")
        lines.append("```bash")
        for step in install_steps:
            lines.append(step)
        lines.append("```\n")
        lines.append("## Usage\n")
        lines.append("```bash")
        lines.append(usage)
        lines.append("```\n")
        if dataset_links:
            lines.append("## Dataset\n")
            lines.append("The dataset is not included in this repository due to its size.")
            lines.append("Download it from:\n")
            for ds_path, link in dataset_links.items():
                folder_name = os.path.basename(ds_path)
                lines.append(f"- [{folder_name}]({link})")
            lines.append("")
            lines.append("Place the data in the `data/` directory.\n")
        lines.append("## Results\n")
        lines.append(f"{results}\n")
        lines.append("## License\n")
        lines.append(f"This project is licensed under the {license_type} License. (c) {year}\n")

        readme_content = "\n".join(lines)
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
        return readme_content

