#!/bin/bash
# Wrapper script for launchd to run LifeOS with proper environment

# Prevent Python from checking for venv markers
export PYTHONNOUSERSITE=1
export __PYVENV_LAUNCHER__=""

cd /Users/nathanramia/Documents/Code/LifeOS

# Source environment variables from .env if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Add site-packages to PYTHONPATH directly
export PYTHONPATH="/Users/nathanramia/Documents/Code/LifeOS:/Users/nathanramia/Documents/Code/LifeOS/venv/lib/python3.13/site-packages"
export PATH="/opt/homebrew/bin:$PATH"

# Run uvicorn using system Python
exec /opt/homebrew/bin/python3 -S -c "
import sys
# Remove site-packages manipulation
sys.path = [p for p in sys.path if 'site-packages' not in p]
sys.path.insert(0, '/Users/nathanramia/Documents/Code/LifeOS')
sys.path.insert(0, '/Users/nathanramia/Documents/Code/LifeOS/venv/lib/python3.13/site-packages')
sys.path.insert(0, '/opt/homebrew/lib/python3.13/site-packages')

import uvicorn
uvicorn.run('api.main:app', host='0.0.0.0', port=8000, log_level='info')
"
