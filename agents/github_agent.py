import os
import requests
from git import Repo, InvalidGitRepositoryError


class GitHubAgent:
    API_BASE = "https://api.github.com"

    def __init__(self, token: str, username: str):
        self.token = token
        self.username = username
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def create_repo(self, repo_name: str, description: str = "", private: bool = False) -> dict:
        url = f"{self.API_BASE}/user/repos"
        payload = {"name": repo_name, "description": description, "private": private, "auto_init": False}
        response = requests.post(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_repos(self) -> list:
        url = f"{self.API_BASE}/user/repos?per_page=100"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_repo_info(self, repo_name: str) -> dict:
        url = f"{self.API_BASE}/repos/{self.username}/{repo_name}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def delete_repo(self, repo_name: str) -> bool:
        url = f"{self.API_BASE}/repos/{self.username}/{repo_name}"
        response = requests.delete(url, headers=self.headers)
        return response.status_code == 204

    def push_repo(self, repo_path: str, repo_name: str, commit_message: str = "Initial commit",
                  exclude_paths: list = None) -> dict:
        remote_url = f"https://{self.token}@github.com/{self.username}/{repo_name}.git"
        try:
            repo = Repo(repo_path)
        except InvalidGitRepositoryError:
            repo = Repo.init(repo_path)

        if exclude_paths:
            gitignore_path = os.path.join(repo_path, '.gitignore')
            existing = ""
            if os.path.exists(gitignore_path):
                with open(gitignore_path, 'r') as f:
                    existing = f.read()
            with open(gitignore_path, 'a') as f:
                for ep in exclude_paths:
                    rel = os.path.relpath(ep, repo_path).replace('\\', '/')
                    if rel not in existing:
                        f.write(f"\n{rel}\n")

        repo.git.add(A=True)
        if repo.is_dirty(index=True, untracked_files=False) or len(repo.index.entries) > 0:
            repo.index.commit(commit_message)

        if 'origin' in [r.name for r in repo.remotes]:
            repo.remotes.origin.set_url(remote_url)
        else:
            repo.create_remote('origin', remote_url)

        try:
            repo.git.push('--set-upstream', 'origin', 'HEAD:main', '--force')
        except Exception as e:
            raise RuntimeError(f"Git push failed: {e}")

        return {"status": "pushed", "repo": repo_name, "url": f"https://github.com/{self.username}/{repo_name}"}

