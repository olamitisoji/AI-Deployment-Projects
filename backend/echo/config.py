from functools import lru_cache
import os
from pathlib import Path
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)
    mode: str = 'local'
    auth_mode: str = 'local'
    database_url: str = 'sqlite:///./.local/echo.db'
    encryption_key: SecretStr
    researcher_token: SecretStr = SecretStr('')
    openai_api_key: SecretStr = SecretStr('')
    openai_key_file: str = ''
    transcription_model: str = 'gpt-transcribe'
    decision_model: str = 'gpt-4.1-mini'
    whatsapp_access_token: SecretStr = SecretStr('')
    whatsapp_app_secret: SecretStr = SecretStr('')
    whatsapp_verify_token: SecretStr = SecretStr('')
    whatsapp_phone_number_id: str = ''
    whatsapp_display_number: str = ''
    whatsapp_api_version: str = ''
    whatsapp_business_account_id: str = ''
    whatsapp_test_mode: bool = True
    test_recipient_allowlist: str = ''
    commercial_eligibility_verified: bool = False
    support_contact: str = 'the researcher who shared your invitation'
    privacy_notice_url: str = ''
    retention_days: int = 7
    supabase_url: str = ''
    supabase_jwt_audience: str = 'authenticated'
    approved_templates: str = ''

    @model_validator(mode='after')
    def validate_runtime(self):
        from cryptography.fernet import Fernet
        Fernet(self.encryption_key.get_secret_value().encode())
        if self.mode not in {'local','production'} or self.auth_mode not in {'local','supabase'}:
            raise ValueError('Unsupported runtime/auth mode')
        if self.database_url.startswith('postgresql://'):
            self.database_url='postgresql+psycopg://'+self.database_url.removeprefix('postgresql://')
        if self.auth_mode == 'local' and (self.mode != 'local' or len(self.researcher_token.get_secret_value()) < 32):
            raise ValueError('Local access requires a local runtime and a strong researcher token')
        if self.auth_mode == 'supabase' and not self.supabase_url.startswith('https://'):
            raise ValueError('Supabase authentication requires its HTTPS URL')
        if self.mode == 'production' and not self.database_url.startswith(('postgresql://','postgresql+psycopg://')):
            raise ValueError('Production requires PostgreSQL')
        if not self.whatsapp_test_mode and not self.commercial_eligibility_verified:
            raise ValueError('Commercial eligibility must be verified before non-test messaging')
        if not self.whatsapp_test_mode and (not self.privacy_notice_url.startswith('https://') or self.support_contact=='the researcher who shared your invitation'):
            raise ValueError('Participant research requires an HTTPS privacy notice and an explicit human support contact')
        if not 1 <= self.retention_days <= 90:
            raise ValueError('Retention must be 1–90 days')
        if self.openai_key_file and not self.openai_api_key.get_secret_value():
            from dotenv import dotenv_values
            values = dotenv_values(Path(self.openai_key_file))
            self.openai_api_key = SecretStr(values.get('OPENAI_API_KEY') or '')
        return self

    @property
    def whatsapp_configured(self):
        return bool(self.whatsapp_access_token.get_secret_value() and self.whatsapp_app_secret.get_secret_value() and self.whatsapp_verify_token.get_secret_value() and self.whatsapp_phone_number_id and self.whatsapp_api_version and self.whatsapp_display_number)

    @property
    def test_recipients(self):
        return {x.strip().lstrip('+') for x in self.test_recipient_allowlist.split(',') if x.strip()}

@lru_cache
def get_settings():
    return Settings(_env_file=os.environ.get('ECHO_ENV_FILE', '.env'))
