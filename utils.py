import os
import shutil
from git import Repo

def clone_or_update_repo(repo_url: str, repo_path: str) -> bool:
    """Safely clones a public repo, deleting the old version first for a clean run."""

    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    try:
        print(f"Cloning {repo_url} to {repo_path}...")
        Repo.clone_from(repo_url, to_path=repo_path)
        return True
    except Exception as e:
        print(f"Error cloning repository: {e}")
        return False