const path = require('path');
const SCRIPT_DIR = __dirname;

module.exports = {
  apps: [
    {
      name: 'sindio-backend',
      cwd: path.join(SCRIPT_DIR, 'backend/app'),
      script: '/tmp/sindio-venv/bin/python3',
      args: '-m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload',
      interpreter: 'none',
      env: {
        PYTHONPATH: '.:..:',
        SINDIO_SKIP_RASTER: '1',
        CORE_PORT: '8080',
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      max_memory_restart: '500M',
      watch: false,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    },
    {
      name: 'sindio-frontend',
      cwd: path.join(SCRIPT_DIR, 'frontend'),
      script: 'node_modules/vite/bin/vite.js',
      args: '',
      env: {
        VITE_API_URL: 'http://localhost:8080',
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      max_memory_restart: '500M',
      watch: false,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    },
  ],
};
