# pyAFTL - core: routes and functions

This document describes the HTTP routes of the Flask app (`app.py`) and the helper functions in `actions/`.

The examples assume the app runs on `localhost:5000` (see `PORT` in `etc/config.json`).

## docker

The image is based on `python:3.13-alpine`, runs the app with gunicorn (2 workers) as user `pyaftl`, and listens on port 5000.

build the image

```bash
docker build -t pyaftl-core:latest .
```

On first start, the entrypoint creates `data/db.sqlite3` from `data/init.sql` if it does not exist yet.

run the container

```bash
docker run -d --name pyaftl-core -p 5000:5000 \
  -v "$HOME/.kube/config:/home/pyaftl/.kube/config:ro" \
  -v pyaftl-workspace:/app/workspace \
  -v pyaftl-data:/app/data \
  pyaftl-core:latest
```

- `/home/pyaftl/.kube/config` is the kubeconfig used by `actions/kube.py`. Without it the app cannot start.
- `/app/workspace` holds the cloned Ansible repo. Keep it on a volume so it survives restarts.
- `/app/data` holds `db.sqlite3` with the `runner-log` table. Keep it on a volume as well.
- To use another configuration, set `AFTL_ENV` (for example `-e AFTL_ENV=dev`) and mount the matching `etc/config.<env>.json` to `/app/etc/`.

check the container

```bash
curl -s http://localhost:5000/
```

### docker compose (local)

`docker-compose.yml` builds the image and runs it with the same settings as above:

- port 5000 is published on `127.0.0.1` only
- the container user `pyaftl` has UID/GID 1000 by default. If your kubeconfig belongs to another UID, run `PYAFTL_UID=$(id -u) PYAFTL_GID=$(id -g) docker compose up -d --build`. Recreate the volumes (`docker compose down -v`) if they were created with a different UID.
- `~/.kube/config` is mounted read-only into the container; set `KUBECONFIG_FILE` to use another file, e.g. `KUBECONFIG_FILE=/path/to/config docker compose up -d`. The file must exist on the host, otherwise `docker compose up` fails.
- `etc/` is mounted read-only, so `AFTL_ENV=dev` can load `etc/config.dev.json`
- `workspace` and `data` are named volumes

```bash
# start (builds the image if needed)
docker compose up -d --build

# use the dev config
AFTL_ENV=dev docker compose up -d

# logs and stop
docker compose logs -f pyaftl-core
docker compose down
```

## routes overview

| method | route                  | purpose                                                     |
|--------|------------------------|-------------------------------------------------------------|
| GET    | `/`                    | lists the available entry points                            |
| GET    | `/update/repo/ansible` | clones or pulls the Ansible git repo into `workspace/`      |
| GET    | `/kube/prepare`        | creates the Kubernetes namespace and runner ConfigMap       |
| POST   | `/job/run/single`      | starts one Ansible runner, optionally limited to one host   |
| POST   | `/job/run/group`       | starts one Ansible runner for an inventory group            |

Parameters for the POST routes can be sent as form data (`-F`) or as a JSON body (`-H 'Content-Type: application/json' -d '{...}'`).

---

## `GET /`

Returns the list of entry points.

```bash
curl -s http://localhost:5000/
```

```json
{
  "update ansible repo": "/update/repo/ansible",
  "prepare cluster": "/kube/prepare"
}
```

---

## `GET /update/repo/ansible`

Clones the Ansible repo (`GIT.ansible` in the config) into `workspace/ansible`, or pulls it if it already exists. Run this before `/job/run/group`, because that route reads the inventory from the local copy.

```bash
curl -s http://localhost:5000/update/repo/ansible
```

```json
"OK"
```

Errors while cloning or pulling are printed to the server log. The route still returns `"OK"`.

Function: `actions.git.git_pull(repo)`.

---

## `GET /kube/prepare`

Prepares the Kubernetes cluster:

- creates the namespace `RUNNER.kube_namespace` if it does not exist
- creates the ConfigMap `pyaftl-runner-conf`, which holds the Git repo URL for the runner (an existing ConfigMap is left unchanged)

```bash
curl -s http://localhost:5000/kube/prepare
```

```json
{
  "created": {
    "namespace": "aftl",
    "runner_configmap": "pyaftl-runner-conf"
  }
}
```

Functions: `Kubernetes.create_namespace(namespace)`, `Kubernetes.create_runner_configmap()`.

---

## `POST /job/run/single`

Starts one Ansible runner that runs `playbooks/<playbook>.yaml` with inventory `groups/linux.ini`.

| parameter  | required | default                 | meaning                                                                 |
|------------|----------|-------------------------|-------------------------------------------------------------------------|
| `host`     | no       | none (all hosts)        | limits the run to this host, passed as `--limit`                        |
| `playbook` | no       | `playbooks/linux.yaml`  | name of the playbook; the file used is `playbooks/<playbook>.yaml`      |

Examples:

```bash
# run the default playbook against all hosts of groups/linux.ini
curl -s -X POST http://localhost:5000/job/run/single

# limit to one host
curl -s -X POST -F host=yoda.home http://localhost:5000/job/run/single

# use playbooks/linux.yaml and limit to one host (JSON body)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"host": "yoda.home", "playbook": "linux"}' \
  http://localhost:5000/job/run/single
```

Response:

```json
"OK"
```

The generated command is roughly:

```bash
ansible-playbook -vv -i groups/linux.ini playbooks/linux.yaml --limit yoda.home
```

Functions: `Kubernetes.setup_job(host, playbook)`, `build_runner_cmd(host, playbook)`.

---

## `POST /job/run/group`

Starts one Ansible runner for an inventory group. Both parameters are required.

| parameter  | required | meaning                                                                                                   |
|------------|----------|-----------------------------------------------------------------------------------------------------------|
| `playbook` | yes      | the file `playbooks/<playbook>.yaml` is run                                                               |
| `group`    | yes      | the inventory `groups/<group>.ini` is used; only letters, digits, `-` and `_` are allowed                 |

The hosts listed under the sections `[linux]` and `[home]` in `groups/<group>.ini` are collected (duplicates removed) and passed to Ansible as `--limit host1,host2,...`.

Example inventory section:

```ini
[linux]
yoda.home
luke.home

[home]
leia.home
```

With that file, the limit is `yoda.home,luke.home,leia.home`.

Examples:

```bash
# form data
curl -s -X POST -F playbook=linux -F group=linux http://localhost:5000/job/run/group

# JSON body
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"playbook": "linux", "group": "linux"}' \
  http://localhost:5000/job/run/group
```

Responses:

| status | body                                                                 | cause                                                |
|--------|----------------------------------------------------------------------|------------------------------------------------------|
| 200    | `"OK"`                                                               | job created                                          |
| 400    | `{"error": "parameters 'playbook' and 'group' are required"}`        | a parameter is missing                               |
| 400    | `{"error": "invalid group name: '...'"}`                             | the group name contains invalid characters           |
| 400    | `{"error": "no hosts found under [linux] or [home] in group ..."}`   | the inventory has no hosts in those sections         |
| 404    | `{"error": "group not found: ..."}`                                  | `groups/<group>.ini` does not exist in `workspace/`  |

Functions: `read_group_hosts(group)`, `Kubernetes.setup_job(host, playbook, group)`.

---

## Kubernetes job handling

Each run is a Kubernetes `Job` created from a suspended `CronJob` named after `RUNNER.name`:

- The CronJob has `suspend: true`, so it never starts runs on a schedule. It only holds the job template.
- It has `successfulJobsHistoryLimit: 2`, so the cluster keeps the last two successful runs and deletes older ones, including their pods.
- Each Job has a controller owner reference to the CronJob, which lets the CronJob controller apply that limit.
- Failed Jobs are not limited by this setting (`failedJobsHistoryLimit` is not set, so Kubernetes uses its default of 1).

Each Job's pod runs the same script: it clones the Ansible repo from the ConfigMap, then runs `ansible-playbook` with the inventory, playbook and `--limit` value from the request.

### useful commands

```bash
# list runs and their status
kubectl -n aftl get jobs -l app=pyaftl

# show the logs of a run
kubectl -n aftl logs job/<job-name>
```

---

## helper functions

### `actions/git.py`

- `git_pull(repo)`: clones the repo `repo` (for example `"ansible"`) into `workspace/<path>`, or pulls it if it already exists.

### `actions/kube.py`

- `read_group_hosts(group, sections=("linux", "home"))`: reads `workspace/ansible/groups/<group>.ini` and returns the hosts under the given sections as a list.
- `build_runner_cmd(host=None, playbook=None, group=None)`: returns the shell script for the runner container. Values are shell-quoted. Defaults are `groups/linux.ini`, `playbooks/linux.yaml`, and no `--limit`.
- `Kubernetes.create_namespace(namespace)`: creates the namespace if it does not exist.
- `Kubernetes.create_runner_configmap()`: creates the ConfigMap `pyaftl-runner-conf` with the repo URL.
- `Kubernetes.create_container(image, name, host, playbook, group)`: builds the runner container with the generated command.
- `Kubernetes.create_pod_template(pod_name, container)`: builds the pod spec with the ConfigMap and SSH key volumes.
- `Kubernetes.create_job(job_name, pod_template)`: builds a `Job` with `backoff_limit=1`.
- `Kubernetes.ensure_cronjob(namespace, cron_name, pod_template)`: creates or updates the suspended CronJob.
- `Kubernetes.setup_job(host, playbook, group)`: ensures the namespace and CronJob exist, then creates one owned Job for this run.
