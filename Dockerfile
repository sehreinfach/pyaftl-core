FROM python:3.13-alpine

# UID/GID of the runtime user; set them to your host user so a 0600 kubeconfig is readable
ARG PYAFTL_UID=1000
ARG PYAFTL_GID=1000

# git is needed by GitPython to clone/pull the Ansible repo
RUN apk add --no-cache git \
    && addgroup -S -g ${PYAFTL_GID} pyaftl \
    && adduser -S -u ${PYAFTL_UID} -G pyaftl -h /home/pyaftl pyaftl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=pyaftl:pyaftl . .

# writable runtime directories (workspace = cloned Ansible repo, data = sqlite db)
RUN mkdir -p /app/workspace /app/data \
    && chown -R pyaftl:pyaftl /app/workspace /app/data \
    && chmod +x /app/docker-entrypoint.sh

USER pyaftl

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
