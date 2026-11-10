"""Fresh downloads must not silently borrow credentials from adjacent projects."""
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from dotenv import dotenv_values


def run_setup(tmp_path):
    project = tmp_path / 'echo-whatsapp'
    (project / 'scripts').mkdir(parents=True, exist_ok=True)
    (project / 'backend').mkdir(exist_ok=True)
    (project / 'dashboard').mkdir(exist_ok=True)
    script = project / 'scripts' / 'configure_local.py'
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts' / script.name, script)
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    return project, result


def test_fresh_setup_does_not_adopt_a_neighboring_api_key(tmp_path):
    neighbor = tmp_path / 'echo-research'
    neighbor.mkdir()
    (neighbor / '.env.local').write_text('OPENAI_API_KEY=synthetic-neighbor-key\n')
    project, result = run_setup(tmp_path)
    backend = dotenv_values(project / 'backend' / '.env')
    dashboard = dotenv_values(project / 'dashboard' / '.env.local')
    compose = dotenv_values(project / '.env.compose')
    assert not backend.get('OPENAI_KEY_FILE')
    assert not backend.get('OPENAI_API_KEY')
    assert Path(compose['OPENAI_ENV_FILE']) == project / 'backend' / '.env'
    assert len(backend['RESEARCHER_TOKEN']) >= 32
    assert dashboard['ECHO_RESEARCHER_TOKEN'] == backend['RESEARCHER_TOKEN']
    assert backend['RESEARCHER_TOKEN'] not in result.stdout + result.stderr
    for file in [project / 'backend' / '.env', project / 'dashboard' / '.env.local', project / '.env.compose']:
        assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_rerunning_setup_preserves_existing_private_settings(tmp_path):
    project, _ = run_setup(tmp_path)
    files = [project / 'backend' / '.env', project / 'dashboard' / '.env.local', project / '.env.compose']
    before = [file.read_bytes() for file in files]
    run_setup(tmp_path)
    assert [file.read_bytes() for file in files] == before
