from kubernetes import client
from kubernetes import config
import logging
import json
import os
import random
import string
import shlex

from flask import Flask

app = Flask(__name__)

if not os.environ.get('AFTL_ENV'):
    app.config.from_file("../etc/config.json", load=json.load)
else:
    app.config.from_file(f"../etc/config.{os.environ.get('AFTL_ENV')}.json", load=json.load)


logging.basicConfig(level=logging.INFO)
config.load_kube_config()

def read_group_hosts(group, sections=("linux", "home")):
    """
    reads the hosts listed under the given sections of groups/<group>.ini
    from the local Ansible repo copy
    :param group: inventory name (groups/<group>.ini)
    :param sections: inventory sections to collect hosts from
    :return: list of unique host names in file order
    """
    path = os.path.join(app.config['APP']['working_dir'] + app.config['GIT']['ansible']['path'],
                        "groups", f"{group}.ini")
    hosts = []
    section = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if section in sections:
                host = line.split()[0]
                if host not in hosts:
                    hosts.append(host)
    return hosts

def build_runner_cmd(host=None, playbook=None, group=None):
    """
    builds the shell script executed in the runner container
    :param host: optional host(s) to limit the ansible run to (comma separated)
    :param playbook: optional playbook name, referencing playbooks/<playbook>.yaml
    :param group: optional inventory name, referencing groups/<group>.ini
    :return: str
    """
    limit = shlex.quote(host) if host else '""'
    playbook_file = shlex.quote(f"playbooks/{playbook}.yaml") if playbook else "playbooks/linux.yaml"
    inventory = shlex.quote(f"groups/{group}.ini") if group else "groups/linux.ini"
    return f"""
set -e
REPO_URL=$(cat /etc/config/ansible_repo | tr -d '\n')
git clone "$REPO_URL" ansible
cd ansible
ansible-playbook -vv -i {inventory} {playbook_file} --limit {limit}
"""

KEEP_SUCCESSFUL_JOBS = 2

class Kubernetes:
    def __init__(self):
        # Init Kubernetes
        self.core_api = client.CoreV1Api()
        self.batch_api = client.BatchV1Api()
        self.random_id = ''.join(random.SystemRandom().choice(string.ascii_lowercase + string.digits) for _ in range(12))


    def create_namespace(self, namespace):
        namespaces = self.core_api.list_namespace()
        all_namespaces = []
        for ns in namespaces.items:
            all_namespaces.append(ns.metadata.name)
        if namespace in all_namespaces:
            logging.info(f"Namespace {namespace} already exists. Reusing.")
        else:
            namespace_metadata = client.V1ObjectMeta(name=namespace)
            self.core_api.create_namespace(
                client.V1Namespace(metadata=namespace_metadata)
            )
            logging.info(f"Created namespace {namespace}.")
        return namespace

    def create_runner_configmap(self):
        metadata = client.V1ObjectMeta(
            name="pyaftl-runner-conf",
            namespace=app.config['RUNNER']['kube_namespace'],
            labels={"app": "pyaftl"}
        )
        data = {
            "ansible_repo": f"https://{app.config['GIT']['access_token']}:x-oauth-basic@{app.config['GIT']['ansible']['repo_url']}"
        }
        configmap = client.V1ConfigMap(
            api_version="v1", kind="ConfigMap", metadata=metadata, data=data
        )
        try:
            api_response = self.core_api.create_namespaced_config_map(
                namespace=app.config['RUNNER']['kube_namespace'], body=configmap
            )
            print(f"ConfigMap '{api_response.metadata.name}' created successfully.")
        except Exception as e:
            print(f"Exception when calling CoreV1Api->create_namespaced_config_map: {e}")
        return configmap

    @staticmethod
    def create_container(image, name, host=None, playbook=None, group=None):
        volume_mount = client.V1VolumeMount(
            name="pyaftl-runner-conf",
            mount_path="/etc/config",
            read_only=True
        )
        ssh_mount = client.V1VolumeMount(
            name="ssh-key-vol",
            mount_path = "/home/ansible/.ssh",
            read_only = True
        )
        container = client.V1Container(
            image=image,
            name=name,
            image_pull_policy="Always",
            command=["/bin/sh", "-c"],
            args=[build_runner_cmd(host=host, playbook=playbook, group=group)],
            volume_mounts=[volume_mount, ssh_mount]
        )
        logging.info(
            f"Created container with name: {container.name}, "
            f"image: {container.image}"
        )
        return container

    @staticmethod
    def create_pod_template(pod_name, container):
        volume = client.V1Volume(
            name="pyaftl-runner-conf",
            config_map=client.V1ConfigMapVolumeSource(
                name="pyaftl-runner-conf"
            )
        )
        ssh_volume = client.V1Volume(
            name = "ssh-key-vol",
            secret=client.V1SecretVolumeSource(
                secret_name="ssh-ansible-runner",
                default_mode=0o400
            )
        )
        pod_template = client.V1PodTemplateSpec(
            spec=client.V1PodSpec(
                security_context=client.V1PodSecurityContext(
                    run_as_user=1000,
                    run_as_group=1000,
                    fs_group=1000
                ),
                restart_policy="Never",
                containers=[container],
                image_pull_secrets=[client.V1LocalObjectReference(name="dockerpull-secret")],
                volumes=[volume, ssh_volume]
            ),
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={"pod_name": pod_name}
            ),
        )
        return pod_template

    @staticmethod
    def create_job(job_name, pod_template):
        metadata = client.V1ObjectMeta(name=job_name, labels={"job_name": job_name, "app": "pyaftl"})
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=metadata,
            spec=client.V1JobSpec(
                backoff_limit=1,
                template=pod_template,
            ),
        )
        return job

    def ensure_cronjob(self, namespace, cron_name, pod_template):
        """
        creates or updates a suspended CronJob used as template and history holder
        for the on-demand runs (successfulJobsHistoryLimit keeps the last 2 successful jobs)
        :return: the CronJob object as stored in the cluster
        """
        cron_job = client.V1CronJob(
            api_version="batch/v1",
            kind="CronJob",
            metadata=client.V1ObjectMeta(name=cron_name, labels={"app": "pyaftl"}),
            spec=client.V1CronJobSpec(
                schedule="0 0 1 1 *",  # never runs: the CronJob is suspended
                suspend=True,
                successful_jobs_history_limit=KEEP_SUCCESSFUL_JOBS,
                concurrency_policy="Allow",
                job_template=client.V1JobTemplateSpec(
                    metadata=client.V1ObjectMeta(labels={"app": "pyaftl"}),
                    spec=client.V1JobSpec(backoff_limit=1, template=pod_template),
                ),
            ),
        )
        try:
            existing = self.batch_api.read_namespaced_cron_job(cron_name, namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise
            return self.batch_api.create_namespaced_cron_job(namespace, cron_job)
        cron_job.metadata.resource_version = existing.metadata.resource_version
        return self.batch_api.replace_namespaced_cron_job(cron_name, namespace, cron_job)

    def setup_job(self, host=None, playbook=None, group=None):
        namespace = app.config['RUNNER']['kube_namespace']
        runner_name = app.config['RUNNER']['name']
        # create namespace if not exists
        self.create_namespace(namespace=namespace)
        # create container for this run
        runner_container = self.create_container(
            image=app.config['RUNNER']['image'],
            name=runner_name,
            host=host,
            playbook=playbook,
            group=group
        )
        # create a pod template spec
        pod_name = f"pod-{runner_name}-{self.random_id}"
        pod_spec = self.create_pod_template(pod_name=pod_name, container=runner_container)
        # the CronJob keeps the history of runs
        cron_name = runner_name
        cron_job = self.ensure_cronjob(namespace, cron_name, pod_spec)
        # create a job owned by the CronJob, so its history limit applies to it
        job_name = f"{runner_name}-{self.random_id}"
        _job = self.create_job(job_name=job_name, pod_template=pod_spec)
        _job.metadata.owner_references = [
            client.V1OwnerReference(
                api_version="batch/v1",
                kind="CronJob",
                name=cron_job.metadata.name,
                uid=cron_job.metadata.uid,
                controller=True,
                block_owner_deletion=True,
            )
        ]
        # execute job
        self.batch_api.create_namespaced_job(namespace, _job)
