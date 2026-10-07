#!/usr/bin/env node
'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);

function pythonInterpreter() {
  const candidates = [process.env.PYTHON, 'python3', 'python'].filter(Boolean);
  const found = spawnSync('uv', ['python', 'find', '3.12'], { encoding: 'utf8' });
  if (found.status === 0 && found.stdout.trim()) candidates.push(found.stdout.trim());
  for (const candidate of [...new Set(candidates)]) {
    const checked = spawnSync(candidate, ['-I', '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'], { stdio: 'ignore' });
    if (checked.status === 0) return candidate;
  }
  return null;
}

if (args[0] === 'config-ui') {
  const interpreter = pythonInterpreter();
  if (!interpreter) {
    process.stderr.write('Lingxi Advisor configuration UI requires Python >= 3.11\n');
    process.exitCode = 2;
  } else {
    const result = spawnSync(interpreter, ['-B', '-m', 'config_ui', ...args.slice(1)], {
      cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' },
    });
    process.exitCode = result.status ?? 1;
  }
} else if (args[0] !== 'protocol') {
  // Standalone Delivery and repository CLI use the identical managed lifecycle.
  require('../kit/plugin-kit/cli/plugin-cli.js').main(root, args);
} else {
  const interpreter = pythonInterpreter();
  if (!interpreter) {
    process.stdout.write(JSON.stringify({ status: 'blocked', message: 'Lingxi Advisor installer requires Python >= 3.11', changes: [], evidence: [] }) + '\n');
    process.exitCode = 2;
  } else {
    const result = spawnSync(interpreter, ['-B', '-m', 'installer.installer', ...args], {
      cwd: root, stdio: 'inherit', env: { ...process.env, CODEHELIX_INVOKE_CWD: process.cwd(), PYTHONDONTWRITEBYTECODE: '1' },
    });
    process.exitCode = result.status ?? 1;
  }
}
