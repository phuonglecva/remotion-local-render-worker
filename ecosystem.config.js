const path = require('node:path');

module.exports = {
  apps: [
    {
      name: 'render-worker',
      cwd: __dirname,
      script: path.join(__dirname, '.venv', 'bin', 'render-worker'),
      args: ['run'],
      interpreter: path.join(__dirname, '.venv', 'bin', 'python'),
      exec_mode: 'fork',
      instances: 1,
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      kill_timeout: 60000,
      env: {
        PYTHONUNBUFFERED: '1',
      },
    },
  ],
};
