from cryptography.fernet import Fernet
import pytest
from pydantic import ValidationError
from echo.config import Settings, get_settings

def test_explicit_environment_file_selects_cloud_configuration(tmp_path, monkeypatch):
    env=tmp_path/'private.env'
    env.write_text('ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\nRESEARCHER_TOKEN='+'r'*40+'\nRETENTION_DAYS=9\nOPENAI_KEY_FILE=\n')
    monkeypatch.setenv('ECHO_ENV_FILE',str(env))
    get_settings.cache_clear()
    try:
        assert get_settings().retention_days==9
    finally:get_settings.cache_clear()

def test_validation_error_does_not_print_database_credential():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None,encryption_key=Fernet.generate_key().decode(),researcher_token='r'*40,
            database_url='postgresql+psycopg://user:private-credential@host/db',mode='invalid')
    assert 'private-credential' not in str(caught.value)
