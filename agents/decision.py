from database.db import DatabaseManager


class DecisionLayer:
    def __init__(self, db: DatabaseManager = None):
        self.db = db

    def decide(self, scan_result: dict, analysis_result: dict, user_prefs: dict = None) -> dict:
        decisions = {
            'exclude_datasets': [],
            'dataset_links': {},
            'warn_large_files': [],
            'actions': [],
        }
        prefs = user_prefs or {}
        auto_threshold = prefs.get('auto_exclude_threshold', 100 * 1024 * 1024)
        default_action = prefs.get('default_dataset_action', 'ask')

        for lf in scan_result.get('large_files', []):
            if lf['size'] > auto_threshold:
                decisions['warn_large_files'].append(lf['path'])
                if default_action == 'exclude':
                    decisions['exclude_datasets'].append(lf['path'])
                    decisions['actions'].append(f"Auto-excluded large file: {lf['path']}")

        for ds in scan_result.get('dataset_folders', []):
            if default_action == 'exclude':
                decisions['exclude_datasets'].append(ds['path'])
                decisions['actions'].append(f"Auto-excluded dataset folder: {ds['path']}")
            else:
                decisions['actions'].append(f"Dataset folder detected (awaiting user input): {ds['path']}")

        return decisions

    def apply_dataset_link(self, decisions: dict, dataset_path: str, link: str) -> dict:
        decisions['dataset_links'][dataset_path] = link
        if dataset_path not in decisions['exclude_datasets']:
            decisions['exclude_datasets'].append(dataset_path)
        decisions['actions'].append(f"Dataset {dataset_path} replaced with link: {link}")
        return decisions

