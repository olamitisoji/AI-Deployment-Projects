"""Explicit database initialization. Production uses PostgreSQL, never SQLite."""
import argparse
from pathlib import Path
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from .config import get_settings
from .database import Base, Project, Membership, Study, database
from .security import Vault
from .conversation_pathway_engine import default_pathway

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['init-db','seed-study'])
    args=parser.parse_args()
    settings=get_settings()
    if settings.database_url.startswith('sqlite'):
        Path(make_url(settings.database_url).database).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    engine,sessions=database(settings.database_url)
    if args.command=='init-db':
        # PostgreSQL creates and secures every table in one transaction. There
        # must not be a committed interval with default Supabase table grants.
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
            if engine.dialect.name=='postgresql':
                # Supabase browser clients must not read backend tables through its REST API.
                # The backend connects as a trusted database owner and applies project membership checks.
                roles=set(connection.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")).scalars())
                for table in Base.metadata.sorted_tables:
                    connection.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
                    connection.execute(text(f'REVOKE ALL ON "{table.name}" FROM PUBLIC'))
                    for role in roles:
                        connection.execute(text(f'REVOKE ALL ON "{table.name}" FROM "{role}"'))
        print('Database schema initialized. No participant records were created.')
    else:
        if settings.mode!='local' or settings.auth_mode!='local':raise SystemExit('Study seed is local-only.')
        vault=Vault(settings.encryption_key.get_secret_value())
        with sessions.begin() as db:
            if db.scalar(select(Project).limit(1)):
                print('Existing projects preserved; no seed added.')
            else:
                project=Project(name='Healthcare administration research');db.add(project);db.flush()
                db.add(Membership(project_id=project.id,user_id='local-researcher'))
                pathway=default_pathway()
                db.add(Study(project_id=project.id,title=pathway.title,pathway=vault.seal(pathway.model_dump()),status='draft'))
                print('Healthcare research draft added for your review. No interviews or approvals were fabricated.')
    engine.dispose()

if __name__=='__main__': main()
