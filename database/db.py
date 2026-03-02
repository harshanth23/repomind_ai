import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'repomind.db')


class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    total_size INTEGER,
                    last_analyzed TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    dataset_path TEXT,
                    dataset_size INTEGER,
                    replacement_link TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    auto_exclude_threshold INTEGER DEFAULT 104857600,
                    default_dataset_action TEXT DEFAULT 'ask'
                )
            ''')
            # Insert default preferences if not exist
            cur = conn.execute('SELECT COUNT(*) FROM user_preferences')
            if cur.fetchone()[0] == 0:
                conn.execute('INSERT INTO user_preferences (auto_exclude_threshold, default_dataset_action) VALUES (?, ?)',
                             (104857600, 'ask'))
            conn.commit()

    # --- Projects ---
    def upsert_project(self, name: str, path: str, total_size: int, last_analyzed: str) -> int:
        with self._get_conn() as conn:
            conn.execute('''
                INSERT INTO projects (name, path, total_size, last_analyzed)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    total_size=excluded.total_size,
                    last_analyzed=excluded.last_analyzed
            ''', (name, path, total_size, last_analyzed))
            conn.commit()
            cur = conn.execute('SELECT id FROM projects WHERE path=?', (path,))
            return cur.fetchone()[0]

    def get_all_projects(self) -> list:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT * FROM projects')
            return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

    def get_project_by_name(self, name: str) -> dict:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT * FROM projects WHERE name=?', (name,))
            row = cur.fetchone()
            if row:
                return dict(zip([d[0] for d in cur.description], row))
            return {}

    # --- Datasets ---
    def upsert_dataset(self, project_id: int, dataset_path: str, dataset_size: int, replacement_link: str = ""):
        with self._get_conn() as conn:
            conn.execute('''
                INSERT INTO datasets (project_id, dataset_path, dataset_size, replacement_link)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            ''', (project_id, dataset_path, dataset_size, replacement_link))
            conn.commit()

    def update_dataset_link(self, project_id: int, dataset_path: str, link: str):
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE datasets SET replacement_link=? WHERE project_id=? AND dataset_path=?
            ''', (link, project_id, dataset_path))
            conn.commit()

    def get_datasets_for_project(self, project_id: int) -> list:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT * FROM datasets WHERE project_id=?', (project_id,))
            return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

    # --- User Preferences ---
    def get_preferences(self) -> dict:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT * FROM user_preferences LIMIT 1')
            row = cur.fetchone()
            if row:
                return dict(zip([d[0] for d in cur.description], row))
            return {}

    def update_preferences(self, auto_exclude_threshold: int = None, default_dataset_action: str = None):
        prefs = self.get_preferences()
        threshold = auto_exclude_threshold if auto_exclude_threshold is not None else prefs.get('auto_exclude_threshold', 104857600)
        action = default_dataset_action if default_dataset_action is not None else prefs.get('default_dataset_action', 'ask')
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE user_preferences SET auto_exclude_threshold=?, default_dataset_action=? WHERE id=1
            ''', (threshold, action))
            conn.commit()
