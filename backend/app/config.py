from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "private-cloud-self-service-portal"
    app_env: str = "local"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "portal_db"
    db_user: str = "portal_user"
    db_password: str = "portal_pass"

    kube_context: str = "kind-portal-dev"

    demo_mode: bool = False
    demo_max_projects: int = 3
    demo_max_replicas: int = 1
    demo_allowed_images: str = "nginx:latest,httpd:alpine,nginx-not-exist-demo:latest"
    demo_namespace_prefix: str = "demo-"
    cors_allowed_origins: str = (
        "http://127.0.0.1:5173,"
        "http://localhost:5173,"
        "http://127.0.0.1:4173,"
        "http://localhost:4173"
    )
    ingress_base_domain: str = "localtest.me"
    app_ingress_class_name: str = "nginx"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
