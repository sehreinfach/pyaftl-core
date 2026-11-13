# pyAFTL - core

## setup

create a virtualenv

```bash
mkvirtualenv -p python3.15 pyaftl-core
pip install -r requirements.txt
```

create/initialze db

```bash
# create db
sqlite3 data/db.sqlite3 < data/init.sql
```

## run app

create/edit _etc/config.json_

for **development**

```bash
AFTL_ENV="dev" python app.py
```

for **production**

```bash
python app.py
```

## setup

### prepare Kubernetes

(_optional if needed_) create a secret to pull images from private registry

```bash
kubectl -n pyaftl create secret docker-registry dockerpull-secret --docker-server=<registry.url> --docker-username=<username> --docker-password=<password>
```

create a secret with your private key for Ansible

```bash
kubectl -n pyaftl create secret generic ssh-ansible-runner --from-file=ssh-privatekey=.ssh/ansible-runner
```

- create namespace
- create configMap for runners

```bash
curl -s http://localhost:5000/kube/prepare
```

get Ansible repo

```bash
curl -s http://localhost:5000/update/repo/ansible
```

## git source

the git source should look like

```text
.
ansible.cfg
groups/
  group_name01.ini
  group_name02.ini
playbooks/
  playbook01.yaml
  playbook02.yaml
roles/
  role_name01/
  role_name02/
```

## usage

run Ansible playbook _linux_ on a single host e.g. _yoda.home_

```bash
curl -s -XPOST \
-H "Content-Type: application/json" \
--data '{
"host": "yoda.home",
"playbook": "linux"
}' \
http://localhost:5000/job/run/single
```