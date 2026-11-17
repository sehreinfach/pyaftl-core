from git import Repo, Git
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
        # disable SSL verification for clone/pull
        ssl_no_verify_env = {'GIT_SSL_NO_VERIFY': 'false'}
        ssl_no_verify_option = 'http.sslVerify=false'
        # check if repo already exists
        if os.path.isdir(repo_path):
            # repo already exist in workingdir so pull
            repo = Repo(repo_path)
            origin = repo.remotes.origin
            with repo.git.custom_environment(**ssl_no_verify_env):
                # '-c' must be passed as a global git option (before the
                # subcommand), so use the Git callable interface here
                # instead of origin.pull(c=...), which would place it after
                # 'pull' and fail with "unknown switch `c'".
                repo.git(c=ssl_no_verify_option).pull(origin.name)
        else:
            # # repo does not exist in workingdir so initial clone
            with Git().custom_environment(**ssl_no_verify_env):
                Repo.clone_from(
                    repo_url,
                    repo_path,
                    branch=app.config['GIT'][repo]['branch'],
                    multi_options=[f'-c http.sslVerify=false '],
                    allow_unsafe_options=True)
    except Exception as e:
        print(f"clone/pull error: {e}")
        return e
