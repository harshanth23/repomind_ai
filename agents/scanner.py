import os
from utils.size_calculator import human_readable_size

DATASET_KEYWORDS = ['dataset', 'data', 'raw', 'images', 'videos', 'input', 'train', 'test', 'val']
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024        # 100 MB
LARGE_FOLDER_THRESHOLD = 1 * 1024 * 1024 * 1024  # 1 GB


class ProjectScanner:
    def __init__(self, root_path: str, exclude_paths: list = None):
        self.root_path = root_path
        self.exclude_paths = set(os.path.normpath(p) for p in (exclude_paths or []))
        self.result = {}

    def scan(self) -> dict:
        large_files = []
        large_folders = []
        dataset_folder_names = []   # just paths, sizes computed after
        all_files = []
        total_size = 0

        # folder_sizes[path] = cumulative bytes — built in ONE pass from file sizes only
        folder_sizes: dict[str, int] = {}

        def onerror(err):
            pass  # silently skip inaccessible folders

        for dirpath, dirnames, filenames in os.walk(self.root_path, onerror=onerror, followlinks=False):
            # Skip excluded folders entirely
            if os.path.normpath(dirpath) in self.exclude_paths:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames
                if os.path.normpath(os.path.join(dirpath, d)) not in self.exclude_paths
                and not d.startswith('.')]
            folder_name = os.path.basename(dirpath).lower()

            # Detect dataset folders by name only — no size call here
            if dirpath != self.root_path and any(kw in folder_name for kw in DATASET_KEYWORDS):
                dataset_folder_names.append(dirpath)

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    fsize = os.path.getsize(filepath)
                except OSError:
                    fsize = 0

                total_size += fsize
                all_files.append(filepath)

                # Accumulate size upward through all ancestor folders
                parts = dirpath
                while True:
                    folder_sizes[parts] = folder_sizes.get(parts, 0) + fsize
                    parent = os.path.dirname(parts)
                    if parent == parts:
                        break
                    parts = parent

                if fsize > LARGE_FILE_THRESHOLD:
                    large_files.append({
                        'path': filepath,
                        'size': fsize,
                        'size_hr': human_readable_size(fsize)
                    })

        # Now resolve dataset folder sizes from accumulated map (no re-walk)
        dataset_folders = []
        for ds_path in dataset_folder_names:
            ds_size = folder_sizes.get(ds_path, 0)
            dataset_folders.append({
                'path': ds_path,
                'size': ds_size,
                'size_hr': human_readable_size(ds_size)
            })

        # Detect large folders from accumulated map (no re-walk)
        for fpath, fsize in folder_sizes.items():
            if fpath != self.root_path and fsize > LARGE_FOLDER_THRESHOLD:
                large_folders.append({
                    'path': fpath,
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
        return self.result

