FROM python:3.12-slim AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app


FROM python-base AS deps-base

COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt


FROM deps-base AS deps-db_orch

COPY requirements/db_orch.txt requirements/db_orch.txt
RUN pip install -r requirements/db_orch.txt


FROM deps-base AS deps-main_agent

COPY requirements/main_agent.txt requirements/main_agent.txt
RUN pip install -r requirements/main_agent.txt


FROM deps-base AS deps-sandbox

COPY requirements/sandbox.txt requirements/sandbox.txt
RUN pip install -r requirements/sandbox.txt


FROM deps-db_orch AS db_orch

COPY services/__init__.py services/__init__.py
COPY services/common/ services/common/
COPY services/db_orch/ services/db_orch/

EXPOSE 8001
CMD ["python", "-m", "services.db_orch.main"]


FROM deps-main_agent AS main_agent

COPY services/__init__.py services/__init__.py
COPY services/common/ services/common/
COPY services/main_agent/ services/main_agent/

RUN mkdir -p /app/logs

EXPOSE 8002
CMD ["python", "-m", "services.main_agent.main"]


FROM deps-sandbox AS sandbox

COPY services/__init__.py services/__init__.py
COPY services/common/ services/common/
COPY services/sandbox/ services/sandbox/

RUN mkdir -p /app/sandboxes

EXPOSE 8003
CMD ["python", "-m", "services.sandbox.main"]
