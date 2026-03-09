from pydantic_settings import BaseSettings, SettingsConfigDict


class ScaffoldAgentSettings(BaseSettings):
    INBOX_EMAIL: str
    EMAIL_SUBJECT_PREFIX: str = "[Scaffold Web Agent]"
    model_config = SettingsConfigDict(env_prefix="SCAFFOLD_")


def load_settings() -> ScaffoldAgentSettings:
    return ScaffoldAgentSettings()
