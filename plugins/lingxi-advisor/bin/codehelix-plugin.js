#!/usr/bin/env node
'use strict';

const path = require('node:path');
const { spawnSync } = require('node:child_process');
const pluginRoot = path.resolve(__dirname, '..');

if (process.argv[2] === 'config-ui') {
  const result = spawnSync(process.execPath, [path.join(pluginRoot, 'source/bin/codehelix-lingxi-advisor.js'), ...process.argv.slice(2)], {
    stdio: 'inherit',
  });
  process.exit(result.status ?? 1);
}

let cli;
try {
  cli = require('../../../plugin-kit/cli/plugin-cli.js');
} catch (error) {
  process.stderr.write('\nInstall failed: the plugin root entry requires a complete repository checkout.\n');
  if (process.env.CODEHELIX_DEBUG) process.stderr.write(`${error.message}\n`);
  process.exit(1);
}

cli.main(pluginRoot);
