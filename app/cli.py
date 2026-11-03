"""Linha de comando.

  python -m app.cli testar-conexao   # confere acesso e permissões no banco do Zabbix
  python -m app.cli coletar          # roda uma coleta agora e sai
  python -m app.cli validar-regras   # confere a sintaxe do rules.yaml

Dentro do container: docker exec -it catalogo-monitoramento python -m app.cli testar-conexao
"""
from __future__ import annotations

import sys
import time

from app.rules import load_rules
from app.settings import settings


def testar_conexao() -> int:
    from app.collector.zabbix_source import ZabbixSource
    print(f"Conectando em {settings.db_host}:{settings.db_port}/{settings.db_name} como {settings.db_user}…")
    with ZabbixSource(settings) as src:
        print(f"  versão do schema: {src.version() or 'desconhecida'}")
        checks = {
            "hosts": "SELECT COUNT(*) FROM hosts WHERE status IN (0,1) AND flags IN (0,4)",
            "host groups": "SELECT COUNT(*) FROM hstgrp WHERE type = 0",
            "itens": "SELECT COUNT(*) FROM items WHERE flags IN (0,4)",
            "triggers": "SELECT COUNT(*) FROM triggers WHERE flags IN (0,4)",
            "proxies": "SELECT COUNT(*) FROM proxy",
            "tags de item": "SELECT COUNT(*) FROM item_tag",
            "macros (texto)": "SELECT COUNT(*) FROM hostmacro WHERE type = 0",
            "estado dos itens": "SELECT COUNT(*) FROM item_rtdata WHERE state = 1",
            "interfaces": "SELECT COUNT(*) FROM interface WHERE main = 1",
        }
        ok = True
        for label, sql in checks.items():
            t = time.monotonic()
            try:
                n = src._all(sql)[0][0]
                print(f"  ok   {label:<18} {n:>12,}  ({time.monotonic() - t:.1f}s)".replace(",", "."))
            except Exception as exc:  # noqa: BLE001
                src.conn.rollback()
                ok = False
                print(f"  ERRO {label:<18} {type(exc).__name__}: {str(exc).strip().splitlines()[0]}")
    return 0 if ok else 1


def coletar() -> int:
    from app.collector.build import build_catalog
    meta = build_catalog(settings)
    print({k: v for k, v in meta.items() if k != "timings"})
    print("tempos acumulados:", meta["timings"])
    return 0


def validar_regras() -> int:
    r = load_rules(settings.rules_file)
    print(f"{settings.rules_file}: ok")
    print(f"  aplicações automáticas: {'ligadas' if r.auto.enabled else 'desligadas'}")
    for a in r.apps:
        kinds = [k for k in ("host_groups", "host_names", "host_tags", "host_macros", "templates",
                             "item_keys", "item_names", "triggers") if getattr(a, k)]
        print(f"  - {a.name}: {', '.join(kinds) or 'só metadados'}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"testar-conexao": testar_conexao, "coletar": coletar, "validar-regras": validar_regras}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(2)
    sys.exit(fn())
