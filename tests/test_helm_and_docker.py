"""Tests verifying Dockerfile manifests, Nginx reverse proxy configuration, and Helm chart templates."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_backend_configuration():
    """Verify backend Dockerfile uses multi-stage builds, non-root user, and exposes all 3 ports."""
    dockerfile_path = REPO_ROOT / "Dockerfile.backend"
    assert dockerfile_path.exists(), "Dockerfile.backend must exist"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage verification
    assert "AS builder" in content, "Backend Dockerfile must feature a builder stage"
    assert "AS runtime" in content, "Backend Dockerfile must feature a runtime stage"

    # Non-root user
    assert "appuser" in content, "Backend must configure non-root user 'appuser'"
    assert "10001" in content, "Backend user must use standard UID 10001"
    assert "USER appuser" in content, "Backend must switch to 'USER appuser'"

    # Scratch volume setup
    assert "/scratch" in content, "Backend must initialize /scratch for DuckDB out-of-core spill"
    assert "DUCKDB_TEMP_DIRECTORY=/scratch" in content

    # Multi-protocol ports
    assert "8000" in content, "Port 8000 (REST) must be exposed"
    assert "5433" in content, "Port 5433 (PGWire) must be exposed"
    assert "5005" in content, "Port 5005 (Flight) must be exposed"

    # Healthcheck
    assert "HEALTHCHECK" in content
    assert "/api/v1/health" in content


def test_frontend_docker_and_nginx_config():
    """Verify frontend multi-stage build, SPA fallback routing, and reverse proxy."""
    dockerfile_path = REPO_ROOT / "frontend" / "Dockerfile"
    assert dockerfile_path.exists(), "frontend/Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "AS builder" in content
    assert "AS runtime" in content
    assert "nginx:alpine" in content

    nginx_path = REPO_ROOT / "frontend" / "nginx.conf"
    assert nginx_path.exists(), "frontend/nginx.conf must exist"
    nginx_conf = nginx_path.read_text(encoding="utf-8")

    # SPA routing
    assert "try_files $uri $uri/ /index.html;" in nginx_conf

    # Reverse proxy to backend
    assert "proxy_pass http://data-hub-backend:8000/api/v1/;" in nginx_conf

    # Security headers & compression
    assert "X-Frame-Options" in nginx_conf
    assert "X-Content-Type-Options" in nginx_conf
    assert "gzip on;" in nginx_conf


def test_helm_chart_yaml_metadata():
    """Verify Helm Chart.yaml metadata syntax and standard attributes."""
    chart_file = REPO_ROOT / "deploy" / "helm" / "data-hub" / "Chart.yaml"
    assert chart_file.exists(), "deploy/helm/data-hub/Chart.yaml must exist"

    with chart_file.open("r", encoding="utf-8") as f:
        meta = yaml.safe_load(f)

    assert meta["apiVersion"] == "v2"
    assert meta["name"] == "data-hub"
    assert meta["version"] == "1.0.0"
    assert "description" in meta


def test_helm_values_yaml():
    """Verify values.yaml defines scratch volume, resource limits, and multi-protocol ports."""
    values_file = REPO_ROOT / "deploy" / "helm" / "data-hub" / "values.yaml"
    assert values_file.exists(), "deploy/helm/data-hub/values.yaml must exist"

    with values_file.open("r", encoding="utf-8") as f:
        values = yaml.safe_load(f)

    backend = values["backend"]
    assert backend["ports"]["http"] == 8000
    assert backend["ports"]["pgwire"] == 5433
    assert backend["ports"]["flight"] == 5005

    # Scratch volume for DuckDB NVMe spill
    scratch = backend["scratchVolume"]
    assert scratch["enabled"] is True
    assert scratch["mountPath"] == "/scratch"
    assert scratch["sizeLimit"] == "100Gi"

    # Environment settings
    env = backend["env"]
    assert env["duckdbTempDirectory"] == "/scratch"
    assert env["duckdbMemoryLimit"] == "24GB"
    assert env["enablePgwire"] is True
    assert env["enableFlight"] is True

    # Multi-protocol service configuration
    svc = values["service"]
    assert svc["ports"]["http"] == 8000
    assert svc["ports"]["pgwire"] == 5433
    assert svc["ports"]["flight"] == 5005


def test_helm_templates_backend_deployment():
    """Verify backend deployment template configures non-root user, scratch mount, and ports."""
    tpl_file = REPO_ROOT / "deploy" / "helm" / "data-hub" / "templates" / "deployment-backend.yaml"
    assert tpl_file.exists()
    content = tpl_file.read_text(encoding="utf-8")

    assert "runAsNonRoot: true" in content
    assert "runAsUser: 10001" in content
    assert "mountPath: {{ .Values.backend.scratchVolume.mountPath }}" in content or "mountPath: /scratch" in content
    assert "emptyDir:" in content
    assert "name: http" in content
    assert "name: pgwire" in content
    assert "name: flight" in content
    assert "path: /api/v1/health" in content


def test_helm_templates_service():
    """Verify multi-port Kubernetes Service exposing HTTP, PGWire, and Flight."""
    svc_file = REPO_ROOT / "deploy" / "helm" / "data-hub" / "templates" / "service.yaml"
    assert svc_file.exists()
    content = svc_file.read_text(encoding="utf-8")

    assert "name: http" in content
    assert "name: pgwire" in content
    assert "name: flight" in content
    assert "port: {{ .Values.service.ports.http }}" in content
    assert "port: {{ .Values.service.ports.pgwire }}" in content
    assert "port: {{ .Values.service.ports.flight }}" in content


def test_vnet_peering_blueprint():
    """Verify enterprise network blueprint covers ExpressRoute, on-prem ports, and private link."""
    bp_file = REPO_ROOT / "deploy" / "vnet-peering-blueprint.md"
    assert bp_file.exists()
    content = bp_file.read_text(encoding="utf-8")

    assert "10.240.0.0/16" in content, "Must define AKS spoke VNet CIDR"
    assert "ExpressRoute" in content, "Must document ExpressRoute connectivity"
    assert "1521" in content, "Must document Oracle port 1521 egress rule"
    assert "1433" in content, "Must document SQL Server port 1433 egress rule"
    assert "privatelink" in content, "Must document Private Endpoints"
    assert "NVMe" in content, "Must document NVMe scratch disk for DuckDB spill"
