
import subprocess

init_pyenv = 'eval "$(pyenv init -)" && eval "$(pyenv virtualenv-init -)"'

def run_command(command):
    """
    Run a shell command and return the output.
    """
    command = init_pyenv+' '+command
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command '{command}' failed with error: {e.stderr}")

def start_backend(backend):
    """
    Start the backend using the provided command.
    """
    try:
        result = subprocess.run(f"supervisorctl -s unix:///tmp/supervisor.sock start {backend}", shell=True, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"failed to start backend {backend}: {e.stderr}")

def create_pipeline_runner_config(pipeline_id):

    """
    Create a pipeline runner config file.
    """
    config = """
    [program:{pipeline_id}]
    command=/bin/bash -c 'eval "$(pyenv init -)" && eval "$(pyenv virtualenv-init -)" && pyenv activate $PIPELINE_VENV && python -u /app/workspace/main.py --disable-smart-memory --disable-cuda-malloc --listen 0.0.0.0 --port 7860'
    autostart=false
    startretries=0
    priority=3
    stdout_logfile=/dev/fd/1
    stdout_logfile_maxbytes=0
    redirect_stderr=true
    autorestart=true
    environment=PYTHONUNBUFFERED=1,PIPELINE_VENV={pipeline_id},PYTHONPATH=/root/.pyenv/versions/comfyui
    """
    config = config.format(pipeline_id=pipeline_id)
    with open(f"/etc/supervisor/conf.d/{pipeline_id}.conf", "w") as f:
        f.write(config)
    
    subprocess.run(f"supervisorctl -s unix:///tmp/supervisor.sock reread", shell=True, check=True)
    subprocess.run(f"supervisorctl -s unix:///tmp/supervisor.sock update", shell=True, check=True)