"""API e interface web do Catálogo de Monitoramento."""
from __future__ import annotations

import base64
import csv
import io
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.catalog import Catalog, CatalogMissing
from app.collector import build
from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("catalogo")

STATIC = Path(__file__).parent / "static"
catalog = Catalog(settings.catalog_path)


# ------------------------------------------------------------------ acesso
async def base_path(request: Request, call_next):
    # Atrás do nginx do Zabbix os caminhos chegam com o prefixo (/catalogo/...); o acesso direto
    # pela porta do container e o healthcheck chegam sem ele. O Starlette espera o prefixo no
    # caminho, então completamos aqui para rotas e arquivos estáticos funcionarem nos dois casos.
    path, prefix = request.scope["path"], settings.base_path
    if prefix and path != prefix and not path.startswith(prefix + "/"):
        request.scope["path"] = prefix + path
    return await call_next(request)


async def basic_auth(request: Request, call_next):
    if settings.basic_auth_user and request.scope["path"] != settings.base_path + "/api/health":
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, settings.basic_auth_user) and \
                    secrets.compare_digest(pwd, settings.basic_auth_password)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="catalogo"'})
    return await call_next(request)


async def _missing(_request, _exc):
    return JSONResponse(status_code=503, content={
        "detail": "O catálogo ainda não foi gerado. A primeira coleta está em andamento ou falhou.",
        "collector": build.state()})


def _404(obj):
    if obj is None:
        raise HTTPException(404, "Não encontrado")
    return obj


# --------------------------------------------------------------- agendador
def _next_run(now: datetime) -> datetime:
    if settings.collect_at:
        hh, mm = (int(x) for x in settings.collect_at.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)
    return now + timedelta(minutes=max(settings.collect_interval_min, 5))


def _run_collect():
    try:
        build.build_catalog(settings)
    except Exception:  # já registrado em build
        pass


def _scheduler():
    if settings.collect_on_start or not settings.catalog_path.exists():
        _run_collect()
    while True:
        nxt = _next_run(datetime.now())
        build._state["next_run"] = nxt.isoformat(timespec="minutes")
        log.info("próxima coleta: %s", nxt)
        time.sleep(max(5, (nxt - datetime.now()).total_seconds()))
        _run_collect()


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_scheduler, name="coletor", daemon=True).start()
    yield


app = FastAPI(title=settings.app_title, docs_url="/api/docs", redoc_url=None, lifespan=lifespan,
              root_path=settings.base_path)
app.middleware("http")(basic_auth)
app.middleware("http")(base_path)  # registrado por último = roda primeiro
app.add_exception_handler(CatalogMissing, _missing)


# --------------------------------------------------------------------- API
@app.get("/api/health")
def health():
    return {"ok": True, "catalog": settings.catalog_path.exists(), "collector": config()["collector"]}


@app.get("/api/config")
def config():
    st = build.state()
    try:
        st["last_finished"] = st.get("last_finished") or catalog.summary()["meta"].get("collected_at")
    except CatalogMissing:
        pass
    return {"title": settings.app_title, "zabbix_url": settings.zabbix_url, "demo": settings.demo_mode,
            "collector": st}


@app.get("/api/summary")
def summary():
    return catalog.summary()


@app.get("/api/apps")
def apps(q: str = "", sort: str = "name"):
    return catalog.list_apps(q, sort)


@app.get("/api/apps/{slug}")
def app_detail(slug: str):
    return _404(catalog.app_detail(slug))


@app.get("/api/apps/{slug}/hosts")
def app_hosts(slug: str, q: str = "", status: str = "", page: int = 1, size: int = Query(50, le=500)):
    return _404(catalog.app_hosts(slug, q, status, page, size))


@app.get("/api/apps/{slug}/items")
def app_items(slug: str, q: str = ""):
    return _404(catalog.app_items(slug, q))


@app.get("/api/apps/{slug}/triggers")
def app_triggers(slug: str, q: str = "", severity: int | None = None, problems: bool = False,
                 page: int = 1, size: int = Query(50, le=500)):
    return _404(catalog.app_triggers(slug, q, severity, problems, page, size))


@app.get("/api/hosts/{hostid}")
def host_detail(hostid: int):
    return _404(catalog.host_detail(hostid))


@app.get("/api/unmapped")
def unmapped(q: str = "", page: int = 1, size: int = Query(50, le=500)):
    return catalog.unmapped_hosts(q, page, size)


@app.get("/api/search")
def search(q: str = ""):
    return catalog.search(q)


@app.get("/api/templates/apps")
def template_apps(name: str):
    return catalog.apps_for_template(name)


@app.get("/api/items/apps")
def item_apps(key: str):
    return catalog.apps_for_item_key(key)


@app.post("/api/admin/collect")
def collect_now(request: Request):
    token = request.headers.get("x-admin-token", "")
    if not settings.admin_token or not secrets.compare_digest(token, settings.admin_token):
        raise HTTPException(403, "Token de administração inválido ou não configurado (ADMIN_TOKEN)")
    if build.state().get("running"):
        raise HTTPException(409, "Já existe uma coleta em andamento")
    threading.Thread(target=_run_collect, daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------- exportação
def _csv(rows: list[dict], filename: str) -> Response:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    data = "﻿" + buf.getvalue()  # BOM para o Excel abrir com acentos
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _xlsx(sheets: dict[str, list[dict]], filename: str) -> StreamingResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=False)
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="C8102E")
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        if not rows:
            ws.append(["Sem dados"])
            continue
        cols = list(rows[0].keys())
        ws.append(cols)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append([r.get(c) for c in cols])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, c in enumerate(cols, 1):
            width = max([len(str(c))] + [len(str(r.get(c) or "")) for r in rows[:300]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 70)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


@app.get("/api/export/apps.{fmt}")
def export_apps(fmt: str):
    rows = catalog.export_apps()
    if fmt == "csv":
        return _csv(rows, f"aplicacoes-monitoradas-{_stamp()}.csv")
    if fmt == "xlsx":
        return _xlsx({"Aplicações": rows}, f"aplicacoes-monitoradas-{_stamp()}.xlsx")
    raise HTTPException(400, "Formato deve ser csv ou xlsx")


@app.get("/api/export/apps/{slug}.{fmt}")
def export_app(slug: str, fmt: str):
    sheets = _404(catalog.export_app(slug))
    if fmt == "csv":
        return _csv(sheets["Hosts"], f"{slug}-hosts-{_stamp()}.csv")
    if fmt == "xlsx":
        return _xlsx(sheets, f"{slug}-{_stamp()}.xlsx")
    raise HTTPException(400, "Formato deve ser csv ou xlsx")


# ---------------------------------------------------------------- interface
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
