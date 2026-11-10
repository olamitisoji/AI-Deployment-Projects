"""Generate a private app credential; never display it or change remote state.

Run only after verifying the project's session endpoint and CA certificate.
The private SQL contains a libpq-generated SCRAM verifier, not the password.
Apply that SQL through authorized administration after the runtime-role migration.
"""
import argparse
import os
from pathlib import Path
import re
import secrets

from dotenv import dotenv_values
from psycopg import pq
from sqlalchemy.engine import URL

ROOT=Path(__file__).resolve().parents[1]

def private_write(path,content):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as output: output.write(content)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ref',required=True)
    parser.add_argument('--session-host',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]{20}',args.project_ref):raise SystemExit('Invalid project reference')
    if not re.fullmatch(r'aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com',args.session_host):raise SystemExit('Expected a verified Supabase session hostname')
    backend=ROOT/'backend'
    target=backend/'.env.supabase'
    private_sql=backend/'.local'/'echo_runtime_password.sql'
    ca=backend/'certs'/'supabase-ca-2021.crt'
    if target.exists() or private_sql.exists():raise SystemExit('Private configuration already exists; refusing to rotate or overwrite credentials')
    if not ca.exists():raise SystemExit('Download the official project CA certificate first')
    values=dict(dotenv_values(backend/'.env'))
    if not values.get('ENCRYPTION_KEY') or not values.get('RESEARCHER_TOKEN'):raise SystemExit('Local Echo settings are required')
    password=secrets.token_urlsafe(48)
    connection=pq.PGconn.connect(b'host=/tmp/echo-no-database user=echo_runtime dbname=postgres connect_timeout=1')
    try: verifier=connection.encrypt_password(password.encode(),b'echo_runtime',b'scram-sha-256').decode()
    finally: connection.finish()
    if not verifier.startswith('SCRAM-SHA-256$') or "'" in verifier:raise SystemExit('Unexpected password verifier')
    database=URL.create('postgresql+psycopg',username='echo_runtime.'+args.project_ref,password=password,
        host=args.session_host,port=5432,database='postgres',
        query={'sslmode':'verify-full','sslrootcert':str(ca),'connect_timeout':'10'})
    values.update(DATABASE_URL=database.render_as_string(hide_password=False),
        SUPABASE_URL='https://'+args.project_ref+'.supabase.co',MODE='local',AUTH_MODE='local',
        OPENAI_API_KEY='',OPENAI_KEY_FILE='')
    # Retain the same encryption key so the existing draft can be copied intact.
    contents='# Private Supabase settings. Local researcher access; OpenAI disabled pending credit.\n'
    for key,value in values.items():
        escaped=str(value or '').replace('\\','\\\\').replace("'","\\'")
        contents+=key+"='"+escaped+"'\n"
    private_sql.parent.mkdir(exist_ok=True,mode=0o700)
    private_write(target,contents)
    private_write(private_sql,"ALTER ROLE echo_runtime LOGIN PASSWORD '"+verifier+"';\n")
    print('Private settings and a one-time SCRAM provisioning file are ready. No credentials displayed; no remote changes made.')

if __name__=='__main__':main()
