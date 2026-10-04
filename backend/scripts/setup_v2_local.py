"""Provision isolated local databases without displaying credentials."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env.v2"
    if destination.exists():
        raise SystemExit("Local v2 configuration already exists; keeping it unchanged.")
    values = dotenv_values(args.source_env)
    source = make_url(values["DATABASE_URL"])
    if source.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("This provisioner only accepts a local MySQL server.")
    engine = create_engine(source.set(database="mysql"))
    password = secrets.token_urlsafe(32)
    databases = ("zhida_kids_v2_dev", "zhida_kids_v2_test", "zhida_kids_v2_migration_test")
    try:
        with engine.connect() as connection:
            existing = connection.execute(text(
                "SELECT COUNT(*) FROM mysql.user WHERE User = 'zhida_v2_local' AND Host = '127.0.0.1'"
            )).scalar_one()
            if existing:
                raise SystemExit("Local v2 database account exists; refusing to replace its password.")
            for name in databases:
                connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4"))
            connection.execute(text(
                "CREATE USER 'zhida_v2_local'@'127.0.0.1' IDENTIFIED BY :password"
            ), {"password": password})
            for name in databases:
                connection.execute(text(
                    f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'zhida_v2_local'@'127.0.0.1'"
                ))
            connection.commit()
    finally:
        engine.dispose()
    local_url = source.set(username="zhida_v2_local", password=password, host="127.0.0.1")
    config = {
        "V2_DATABASE_URL": local_url.set(database=databases[0]).render_as_string(hide_password=False),
        "V2_TEST_DATABASE_URL": local_url.set(database=databases[1]).render_as_string(hide_password=False),
        "V2_JWT_SECRET": secrets.token_urlsafe(48),
        "V2_ENV": "development",
        "V2_DEV_WECHAT_MOCK": "false",
        "V2_WECHAT_APPID": values.get("WECHAT_APPID") or "wx33ab8a66217dc933",
        "V2_WECHAT_SECRET": values.get("WECHAT_SECRET") or "",
    }
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        for key, value in config.items():
            handle.write(f"{key}={value}\n")
    print("Created isolated v2 dev/test databases and private local configuration.")


if __name__ == "__main__":
    main()
