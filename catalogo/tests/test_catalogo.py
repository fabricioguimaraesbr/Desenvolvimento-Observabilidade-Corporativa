"""Testes com a fonte demo: montam o catálogo e exercitam API e regras."""
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    os.environ.update(DEMO_MODE="true", DATA_DIR=str(data), RULES_FILE=str(ROOT / "config/rules.yaml"),
                      COLLECT_ON_START="false", ADMIN_TOKEN="segredo")
    from app import settings as st
    st.settings = st.Settings()
    from app.collector.build import build_catalog
    build_catalog(st.settings)
    import app.main as main
    main.settings = st.settings
    main.catalog.path = st.settings.catalog_path
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_rules_auto_name():
    from app.rules import load_rules
    r = load_rules(ROOT / "config/rules.yaml")
    assert r.auto.app_name_for_group("APP/Checkout/Front") == "Checkout"
    assert r.auto.app_name_for_group("Linux servers") is None


def test_summary_and_apps(client):
    s = client.get("/api/summary").json()
    assert s["meta"]["hosts"] > 1000
    apps = client.get("/api/apps").json()
    names = {a["name"] for a in apps}
    assert {"Checkout", "Pagamentos", "Certificados digitais"} <= names


def test_partial_hosts_by_item_rule(client):
    d = client.get("/api/apps/checkout").json()
    assert d["hosts_partial"] > 0
    hosts = client.get("/api/apps/checkout/hosts?status=partial").json()
    assert hosts["rows"] and all(h["scope"] == "partial" for h in hosts["rows"])
    assert all(re.match(r"db-", h["host"]) for h in hosts["rows"])


def test_triggers_grouped_by_raw_name(client):
    t = client.get("/api/apps/pdv-lojas/triggers").json()
    assert t["groups"] < 20  # nomes com {HOST.NAME} não explodem em um grupo por host


def test_search_and_host(client):
    r = client.get("/api/search?q=pgsql").json()
    assert r["items"]
    hid = client.get("/api/search?q=chk-").json()["hosts"][0]["hostid"]
    h = client.get(f"/api/hosts/{hid}").json()
    assert h["apps"] and h["families"]


def test_exports(client):
    assert client.get("/api/export/apps.csv").status_code == 200
    x = client.get("/api/export/apps/checkout.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_admin_requires_token(client):
    assert client.post("/api/admin/collect").status_code == 403


def test_unmapped(client):
    assert client.get("/api/unmapped").json()["total"] > 0


def test_base_path(client, monkeypatch):
    """Atrás do nginx (BASE_PATH=/catalogo) e no acesso direto, sem prefixo."""
    import app.main as main
    monkeypatch.setattr(main, "settings", replace(main.settings, base_path="/catalogo"))
    monkeypatch.setattr(main.app, "root_path", "/catalogo")
    for path in ("/catalogo/", "/catalogo/static/app.css", "/catalogo/api/summary", "/catalogo/api/export/apps.csv",
                 "/", "/static/app.js", "/api/health"):
        assert client.get(path).status_code == 200, path
    assert "/catalogo/openapi.json" in client.get("/catalogo/api/docs").text
    # A interface só usa caminhos relativos, para funcionar com ou sem o prefixo
    for name in ("index.html", "app.js", "app.css"):
        text = (ROOT / "app/static" / name).read_text(encoding="utf-8")
        assert not re.search(r"""["'`(]/(api|static)/""", text), name
