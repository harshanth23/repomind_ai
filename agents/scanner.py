import os
from utils.size_calculator import calculate_size, human_readable_size

DATASET_KEYWORDS = ['dataset', 'data', 'raw', 'images', 'videos', 'input', 'train', 'test', 'val']
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024   # 100 MB
LARGE_FOLDER_THRESHOLD = 1 * 1024 * 1024 * 1024  # 1 GB


class ProjectScanner:
    def __init__(self, root_path: str):
        self.root_path = root_path
        self.result = {}

    def scan(self) -> dict:
        large_files = []
        large_folders = []
        dataset_folders = []
        all_files = []
        total_size = 0

        for dirpath, dirnames, filenames in os.walk(self.root_path):
            # Skip hidden folders like .git
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]

            folder_size = calculate_size(dirpath)
            folder_name = os.path.basename(dirpath).lower()

            # Detect dataset folders
            if any(kw in folder_name for kw in DATASET_KEYWORDS) and dirpath != self.root_path:
                dataset_folders.append({
                    'path': dirpath,
                    'size': folder_size,
                    'size_hr': human_readable_size(folder_size)
                })

            # Detect large non-root folders
            if folder_size > LARGE_FOLDER_THRESHOLD and dirpath != self.root_path:
                large_folders.append({
                    'path': dirpath,
                    'size': folder_size,
                    'size_hr': human_readable_size(folder_size)
                })

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    fsize = os.path.getsize(filepath)
                except OSError:
                    fsize = 0
                total_size += fsize
                all_files.append(filepath)
                if fsize > LARGE_FILE_THRESHOLD:
                    large_files.append({
                        'path': filepath,
                        'size': fsize,
                        'size_hr': human_readable_size(fsize)
                    })

        self.result = {
            'root_path': self.root_path,
            'total_size': total_size,
            'total_size_hr': human_readable_size(total_size),
            'total_files': len(all_files),
            'large_files': large_files,
            'large_folders': large_folders,
            'dataset_folders': dataset_folders,
        }
        return self.result

