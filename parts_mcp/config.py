"""
Configuration management for Parts MCP server.
"""
import os
from dataclasses import dataclass
from pathlib import Path

# API Configuration
SOURCE_PARTS_API_KEY = os.getenv("SOURCE_PARTS_API_KEY", "")
SOURCE_PARTS_API_URL = os.getenv("SOURCE_PARTS_API_URL", "https://api.source.parts/v1/")

# Cache Configuration
CACHE_DIR = Path(os.getenv("PARTS_CACHE_DIR", "~/.cache/parts-mcp")).expanduser()
CACHE_EXPIRY_HOURS = int(os.getenv("CACHE_EXPIRY_HOURS", "24"))

# KiCad Configuration
KICAD_SEARCH_PATHS: list[str] = []
kicad_paths_env = os.getenv("KICAD_SEARCH_PATHS", "")
if kicad_paths_env:
    KICAD_SEARCH_PATHS = [
        Path(p.strip()).expanduser().resolve().as_posix()
        for p in kicad_paths_env.split(",")
        if p.strip()
    ]

# Default KiCad user directories by platform
if not KICAD_SEARCH_PATHS:
    home = Path.home()
    if os.name == "posix":
        if os.uname().sysname == "Darwin":  # macOS
            KICAD_SEARCH_PATHS = [
                (home / "Documents" / "KiCad").as_posix(),
                (home / "KiCad").as_posix(),
            ]
        else:  # Linux
            KICAD_SEARCH_PATHS = [
                (home / "Documents" / "KiCad").as_posix(),
                (home / "KiCad").as_posix(),
            ]
    elif os.name == "nt":  # Windows
        KICAD_SEARCH_PATHS = [
            (home / "Documents" / "KiCad").as_posix(),
            (Path(os.getenv("APPDATA", "")) / "KiCad").as_posix(),
        ]

# Search Configuration
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "100"))
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))

# Ensure cache directory exists (fall back to /tmp in containers where ~ may not be writable)
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    CACHE_DIR = Path("/tmp/parts-mcp-cache")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Server / Auth / Storage config dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServerConfig:
    transport: str
    host: str
    port: int
    path: str
    log_level: str

    @property
    def is_hosted(self) -> bool:
        return self.transport != "stdio"


@dataclass(frozen=True)
class AuthConfig:
    rsa_private_key_b64: str | None
    config_url: str | None
    client_id: str | None
    client_secret: str | None
    audience: str | None
    base_url: str | None
    issuer_url: str | None
    redirect_path: str | None
    jwt_signing_key: str | None
    access_token_ttl: int = 7 * 24 * 3600  # 7 days; configurable via MCP_ACCESS_TOKEN_TTL

    @property
    def has_rsa_key(self) -> bool:
        return bool(self.rsa_private_key_b64)

    @property
    def has_required_auth0(self) -> bool:
        return all([self.config_url, self.client_id, self.client_secret,
                    self.audience, self.base_url])


@dataclass(frozen=True)
class StorageConfig:
    redis_url: str | None
    storage_dir: str | None


def load_server_config() -> ServerConfig:
    return ServerConfig(
        transport=os.getenv("MCP_TRANSPORT", "stdio"),
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000")),
        path=os.getenv("MCP_PATH", "/mcp"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def load_auth_config() -> AuthConfig:
    p = "FASTMCP_SERVER_AUTH_AUTH0_"
    return AuthConfig(
        rsa_private_key_b64=os.getenv("MCP_JWT_RSA_PRIVATE_KEY"),
        config_url=os.getenv(f"{p}CONFIG_URL"),
        client_id=os.getenv(f"{p}CLIENT_ID"),
        client_secret=os.getenv(f"{p}CLIENT_SECRET"),
        audience=os.getenv(f"{p}AUDIENCE"),
        base_url=os.getenv(f"{p}BASE_URL"),
        issuer_url=os.getenv(f"{p}ISSUER_URL"),
        redirect_path=os.getenv(f"{p}REDIRECT_PATH"),
        jwt_signing_key=os.getenv(f"{p}JWT_SIGNING_KEY"),
        access_token_ttl=int(os.getenv("MCP_ACCESS_TOKEN_TTL", str(7 * 24 * 3600))),
    )


def load_storage_config() -> StorageConfig:
    return StorageConfig(
        redis_url=os.getenv("MCP_REDIS_URL"),
        storage_dir=os.getenv("MCP_STORAGE_DIR"),
    )
