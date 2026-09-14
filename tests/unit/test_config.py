"""Port of Go base_test.go plus the Python additions."""

from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from flag_commons.config import BaseConfig, ConfigError, load_base, parse_listen_addr
from flag_commons.secrets import EnvProvider, SecretsBackendError


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in ("DATABASE_URL", "LOG_LEVEL", "LOG_FORMAT", "LISTEN_ADDR"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_load_base_success_with_defaults(clean_env: pytest.MonkeyPatch) -> None:
    # Go: TestLoadBase / success with defaults
    clean_env.setenv("DATABASE_URL", "postgres://localhost/flagdb")
    cfg = load_base("karr", EnvProvider())
    assert cfg.component == "karr"
    assert cfg.log_level == "info"
    assert cfg.log_format == "text"
    assert cfg.database_url.get_secret_value() == "postgres://localhost/flagdb"
    assert cfg.listen_addr == ":8080"


def test_load_base_custom_values(clean_env: pytest.MonkeyPatch) -> None:
    # Go: TestLoadBase / custom values
    clean_env.setenv("DATABASE_URL", "postgres://localhost/flagdb")
    clean_env.setenv("LOG_LEVEL", "debug")
    clean_env.setenv("LOG_FORMAT", "json")
    clean_env.setenv("LISTEN_ADDR", ":9090")
    cfg = load_base("kitt", EnvProvider())
    assert (cfg.log_level, cfg.log_format, cfg.listen_addr) == (
        "debug",
        "json",
        ":9090",
    )


def test_load_base_missing_database_url(clean_env: pytest.MonkeyPatch) -> None:
    # Go: TestLoadBase / missing DATABASE_URL
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_base("karr", EnvProvider())


def test_load_base_empty_database_url_rejected(clean_env: pytest.MonkeyPatch) -> None:
    # FIX: Go accepted an empty value.
    clean_env.setenv("DATABASE_URL", "")
    with pytest.raises(ConfigError, match="empty"):
        load_base("karr", EnvProvider())


def test_load_base_database_optional(clean_env: pytest.MonkeyPatch) -> None:
    cfg = load_base("bonnie", EnvProvider(), require_database=False)
    assert cfg.database_url.get_secret_value() == ""


def test_load_base_empty_component(clean_env: pytest.MonkeyPatch) -> None:
    # Go: TestLoadBase / empty component
    with pytest.raises(ConfigError, match="component name"):
        load_base("", EnvProvider())


def test_setup_logging_from_config() -> None:
    # Go: TestBase_Logger
    buf = io.StringIO()
    cfg = BaseConfig(component="test", log_level="debug", log_format="json")
    logger = cfg.setup_logging(stream=buf, dist_name="flag-commons")
    logger.debug("hi")
    record = json.loads(buf.getvalue())
    assert record["component"] == "test"
    assert record["level"] == "DEBUG"


def test_subclass_reads_extra_keys(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgres://x")
    clean_env.setenv("MY_TOKEN", "t")

    class MyConfig(BaseConfig):
        my_token: str

    cfg = MyConfig(
        **BaseConfig.base_fields("my", EnvProvider()),
        my_token=EnvProvider().get("MY_TOKEN"),
    )
    assert cfg.my_token == "t"
    assert cfg.component == "my"


def test_config_is_frozen_and_forbids_extras() -> None:
    cfg = BaseConfig(component="x")
    with pytest.raises(ValidationError):
        cfg.component = "y"
    with pytest.raises(ValidationError):
        BaseConfig(component="x", unknown=1)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("addr", "expected"),
    [
        (":8080", ("0.0.0.0", 8080)),
        ("127.0.0.1:9090", ("127.0.0.1", 9090)),
        ("[::1]:8080", ("::1", 8080)),
        ("  :80 ", ("0.0.0.0", 80)),
    ],
)
def test_bind_address(addr: str, expected: tuple[str, int]) -> None:
    assert BaseConfig(component="x", listen_addr=addr).bind_address() == expected


@pytest.mark.parametrize(
    "addr", ["", "8080", "host:", "host:abc", "host:0", "host:70000"]
)
def test_bind_address_invalid(addr: str) -> None:
    with pytest.raises(ConfigError):
        parse_listen_addr(addr)


def test_database_url_never_leaks(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql://flag:sup3rs3cr3t@db/karr")
    cfg = load_base("karr", EnvProvider())
    assert "sup3rs3cr3t" not in repr(cfg)
    assert "sup3rs3cr3t" not in cfg.model_dump_json()
    assert cfg.database_url.get_secret_value().endswith("@db/karr")


def test_backend_error_becomes_config_error(clean_env: pytest.MonkeyPatch) -> None:
    class Broken:
        def get(self, key: str) -> str:
            raise SecretsBackendError("openbao down")

        def get_or_default(self, key: str, default: str) -> str:
            return default

    with pytest.raises(ConfigError, match="openbao down"):
        load_base("karr", Broken())


def test_component_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        BaseConfig(component="")
