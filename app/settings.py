"""Configuração lida de variáveis de ambiente (ver .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "sim", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Banco do Zabbix (somente leitura)
    db_host: str = field(default_factory=lambda: os.getenv("ZBX_DB_HOST", "postgres-server"))
    db_port: int = field(default_factory=lambda: _int("ZBX_DB_PORT", 5432))
    db_name: str = field(default_factory=lambda: os.getenv("ZBX_DB_NAME", "zabbix"))
    db_user: str = field(default_factory=lambda: os.getenv("ZBX_DB_USER", "zbx_catalogo"))
    db_password: str = field(default_factory=lambda: os.getenv("ZBX_DB_PASSWORD", ""))
    db_sslmode: str = field(default_factory=lambda: os.getenv("ZBX_DB_SSLMODE", "prefer"))
    db_statement_timeout_s: int = field(default_factory=lambda: _int("ZBX_DB_STATEMENT_TIMEOUT", 600))

    # Frontend do Zabbix, usado só para montar links ("abrir no Zabbix")
    zabbix_url: str = field(default_factory=lambda: os.getenv("ZBX_FRONTEND_URL", "").rstrip("/"))

    # Coleta
    collect_interval_min: int = field(default_factory=lambda: _int("COLLECT_INTERVAL_MINUTES", 360))
    collect_at: str = field(default_factory=lambda: os.getenv("COLLECT_AT", "").strip())  # "HH:MM", opcional
    collect_on_start: bool = field(default_factory=lambda: _bool("COLLECT_ON_START", True))
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", False))

    # Arquivos
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")))
    rules_file: Path = field(default_factory=lambda: Path(os.getenv("RULES_FILE", "/config/rules.yaml")))

    # Acesso
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""))
    basic_auth_user: str = field(default_factory=lambda: os.getenv("BASIC_AUTH_USER", ""))
    basic_auth_password: str = field(default_factory=lambda: os.getenv("BASIC_AUTH_PASSWORD", ""))

    # Texto exibido no topo da interface
    app_title: str = field(default_factory=lambda: os.getenv("APP_TITLE", "Catálogo de Monitoramento"))

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalogo.sqlite"


settings = Settings()
