from flask import Flask, jsonify, session, flash, request, redirect, url_for
from flask_wtf import FlaskForm, CSRFProtect
import random
import re
import string
import json
import os

# load own packages/libs
from actions import git, kube, db

app = Flask(__name__)
app.secret_key = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(24))
#csrf = CSRFProtect(app)

# load app config depending on env
if not os.environ.get('AFTL_ENV'):
    app.config.from_file("etc/config.json", load=json.load)
else:
    app.config.from_file(f"etc/config.{os.environ.get('AFTL_ENV')}.json", load=json.load)

# start/index
@app.route('/', methods=['GET'])
def start():
    msg = {
        "update ansible repo": "/update/repo/ansible",
        "prepare cluster": "/kube/prepare"
    }
    return jsonify(msg)

# get/update ansible code from repo
@app.route('/update/repo/ansible')
def git_pull():
    """
    clone/update a defined git repo
    :return: str
    """
    git.git_pull(repo="ansible")
    return jsonify("OK")

@app.route('/kube/prepare')
def kube_prepare():
    k8s = kube.Kubernetes()
    k8s.create_namespace(app.config['RUNNER']['kube_namespace'])
    k8s.create_runner_configmap()
    return {
        "created": {
            "namespace": app.config['RUNNER']['kube_namespace'],
            "runner_configmap": "pyaftl-runner-conf"
        }
    }


@app.route('/job/run/single', methods=['POST'])
def job_run_single():
    """
    starts a single Ansible runner in Kubernetes cluster
    optional POST parameter "host" limits the Ansible run to that host
    optional POST parameter "playbook" runs playbooks/<playbook>.yaml instead of the default
    :return: none
    """
    git.git_pull(repo="ansible")
    data = request.get_json(silent=True) or {}
    host = request.form.get('host') or data.get('host') or None
    playbook = request.form.get('playbook') or data.get('playbook') or None
    k8s = kube.Kubernetes()
    k8s.setup_job(host=host, playbook=playbook)
    db.log_job_start(host=host, group="single", playbook=playbook or "linux")
    return jsonify("OK")

@app.route('/job/run/group', methods=['POST'])
def job_run_group():
    """
    starts a single Ansible runner using playbooks/<playbook>.yaml and groups/<group>.ini
    the hosts listed under [linux] and [home] in the inventory are used as ansible limit
    POST parameters: "playbook" (required), "group" (required)
    :return: none
    """
    git.git_pull(repo="ansible")
    data = request.get_json(silent=True) or {}
    playbook = request.form.get('playbook') or data.get('playbook')
    group = request.form.get('group') or data.get('group')
    if not playbook or not group:
        return jsonify(error="parameters 'playbook' and 'group' are required"), 400
    if not re.fullmatch(r"[A-Za-z0-9_-]+", group):
        return jsonify(error=f"invalid group name: {group!r}"), 400
    try:
        hosts = kube.read_group_hosts(group)
    except FileNotFoundError:
        return jsonify(error=f"group not found: {group}"), 404
    if not hosts:
        return jsonify(error=f"no hosts found under [linux] or [home] in group {group}"), 400
    k8s = kube.Kubernetes()
    k8s.setup_job(host=",".join(hosts), playbook=playbook, group=group)
    db.log_job_start(host=",".join(hosts), group=group, playbook=playbook)
    return jsonify("OK")

# run app
if __name__ == "__main__":
    app.config['SESSION_TYPE'] = 'filesystem'
    app.run(
        debug=app.config['DEBUG'],
        host=app.config['LISTEN'],
        port=app.config['PORT']
    )
