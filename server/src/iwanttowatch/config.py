import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration, read from IWANTTOWATCH_* environment variables.

    Everything a household configures (connectors, region, users) lives in the
    database and is set through the web UI instead.
    """

    model_config = SettingsConfigDict(env_prefix="IWANTTOWATCH_")

    data_dir: Path = Path("data")
    secret_key: str | None = None
    host: str = "0.0.0.0"
    port: int = 8080
    # Directory holding the built web app; when unset, only the API is served.
    static_dir: Path | None = None

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'iwanttowatch.db'}"

    def resolve_secret_key(self) -> str:
        """Return the configured secret key, or one generated once and kept in the data dir."""
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / "secret_key"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
            path.chmod(0o600)
        return path.read_text().strip()
