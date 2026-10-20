'use strict';

const { packager } = require('@electron/packager');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const root = __dirname;
  const backend = path.join(root, 'dist', 'backend', 'VMA-Backend');
  if (!fs.existsSync(path.join(backend, 'VMA-Backend.exe'))) {
    throw new Error('Build the frozen backend before packaging Electron.');
  }
  const output = await packager({
    dir: root,
    name: 'VMA',
    executableName: 'VMA',
    platform: 'win32',
    arch: 'x64',
    out: path.join(root, 'dist', 'app'),
    overwrite: true,
    asar: true,
    ignore: [/[/\\]dist[/\\]/, /[/\\]docs[/\\]/, /[/\\]\.venv-build[/\\]/],
  });
  const resources = path.join(output[0], 'resources', 'backend');
  fs.cpSync(backend, resources, { recursive: true });
  process.stdout.write(`${output[0]}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
