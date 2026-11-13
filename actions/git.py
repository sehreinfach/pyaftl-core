from git import Repo
import os
import json
from flask import Flask

app = Flask(__name__)

if not os.environ.get('AFTL_ENV'):
    app.config.from_file("../etc/config.json", load=json.load)
else:
    app.config.from_file(f"../etc/config.{os.environ.get('AFTL_ENV')}.json", load=json.load)


def git_pull(repo):
    try:
        repo_url = f"https://{app.config['GIT']['access_token']}:x-oauth-basic@{app.config['GIT'][repo]['repo_url']}"
        repo_path = app.config['APP']['working_dir'] + app.config['GIT'][repo]['path']
        # check if repo already exists
        if os.path.isdir(repo_path):
            # repo already exist in workingdir so pull
            repo = Repo(repo_path)
            origin = repo.remotes.origin
            origin.pull()
        else:
            # # repo does not exist in workingdir so initial clone
            Repo.clone_from(
                repo_url,
                repo_path,
                branch=app.config['GIT'][repo]['branch'])
    except Exception as e:
        print(f"clone/pull error: {e}")
        return e