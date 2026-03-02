import os

ML_FRAMEWORKS = {
    'pytorch': ['torch', 'torchvision'],
    'tensorflow': ['tensorflow', 'keras'],
    'sklearn': ['sklearn', 'scikit-learn'],
    'xgboost': ['xgboost'],
    'lightgbm': ['lightgbm'],
    'jax': ['jax'],
}

MODEL_EXTENSIONS = ['.pt', '.pth', '.h5', '.pb', '.ckpt', '.pkl', '.onnx']


class ProjectAnalyzer:
    def __init__(self, project_path: str, exclude_paths: list = None):
        self.project_path = project_path
        self.exclude_paths = set(os.path.normpath(p) for p in (exclude_paths or []))

    def analyze(self) -> dict:
        detected_frameworks = []
        requirements_found = False
        model_files = []
        total_lines = 0
        py_files = []
        git_initialized = os.path.isdir(os.path.join(self.project_path, '.git'))

        for dirpath, dirnames, filenames in os.walk(self.project_path):
            # Skip excluded folders entirely
            if os.path.normpath(dirpath) in self.exclude_paths:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames
                if os.path.normpath(os.path.join(dirpath, d)) not in self.exclude_paths
                and not d.startswith('.')]

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                ext = os.path.splitext(filename)[1].lower()

                # Count Python lines
                if ext == '.py':
                    py_files.append(filepath)
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            total_lines += sum(1 for _ in f)
                    except OSError:
                        pass

                # Check requirements.txt
                if filename.lower() == 'requirements.txt':
                    requirements_found = True
                    # Detect frameworks from requirements
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                        for fw, keywords in ML_FRAMEWORKS.items():
                            if any(kw in content for kw in keywords):
                                if fw not in detected_frameworks:
                                    detected_frameworks.append(fw)
                    except OSError:
                        pass

                # Detect model files
                if ext in MODEL_EXTENSIONS:
                    model_files.append(filepath)

        # Also scan .py files for framework imports
        for pyf in py_files:
            try:
                with open(pyf, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().lower()
                for fw, keywords in ML_FRAMEWORKS.items():
                    if any(kw in content for kw in keywords):
                        if fw not in detected_frameworks:
                            detected_frameworks.append(fw)
            except OSError:
                pass

        return {
            'project_path': self.project_path,
            'detected_frameworks': detected_frameworks,
            'requirements_found': requirements_found,
            'model_files': model_files,
            'total_python_files': len(py_files),
            'total_lines_of_code': total_lines,
            'git_initialized': git_initialized,
        }

