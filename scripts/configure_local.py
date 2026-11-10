"""Prepare ignored local settings without printing or copying API credentials."""
from pathlib import Path
import os
import secrets
from cryptography.fernet import Fernet
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
backend=root/'backend'
(backend/'.local').mkdir(exist_ok=True,mode=0o700)
env_path=backend/'.env'
if not env_path.exists():
    values={
        'MODE':'local','AUTH_MODE':'local','DATABASE_URL':'sqlite:///./.local/echo.db',
        'ENCRYPTION_KEY':Fernet.generate_key().decode(),'RESEARCHER_TOKEN':secrets.token_urlsafe(48),
        'OPENAI_API_KEY':'','OPENAI_KEY_FILE':'',
        'TRANSCRIPTION_MODEL':'gpt-transcribe','DECISION_MODEL':'gpt-4.1-mini',
        'WHATSAPP_TEST_MODE':'true','WHATSAPP_ACCESS_TOKEN':'','WHATSAPP_APP_SECRET':'',
        'WHATSAPP_VERIFY_TOKEN':secrets.token_urlsafe(32),'WHATSAPP_PHONE_NUMBER_ID':'',
        'WHATSAPP_DISPLAY_NUMBER':'','WHATSAPP_API_VERSION':'','TEST_RECIPIENT_ALLOWLIST':'',
        'SUPPORT_CONTACT':'the researcher who shared your invitation','PRIVACY_NOTICE_URL':'','RETENTION_DAYS':'7',
        'COMMERCIAL_ELIGIBILITY_VERIFIED':'false',
    }
    fd=os.open(env_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        for key,value in values.items(): f.write(f'{key}="{value}"\n')
else:
    os.chmod(env_path,0o600)
settings=dotenv_values(env_path)
dashboard_path=root/'dashboard'/'.env.local'
if not dashboard_path.exists():
    fd=os.open(dashboard_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('ECHO_API_URL=http://127.0.0.1:8000\nECHO_AUTH_MODE=local\n')
        f.write('ECHO_RESEARCHER_TOKEN='+str(settings['RESEARCHER_TOKEN'])+'\n')
else: os.chmod(dashboard_path,0o600)
compose_path=root/'.env.compose'
if not compose_path.exists():
    fd=os.open(compose_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('POSTGRES_PASSWORD='+secrets.token_hex(32)+'\n')
        f.write('OPENAI_ENV_FILE='+str(env_path)+'\n')
print('Local backend and dashboard settings are ready. Credentials were not displayed.')
