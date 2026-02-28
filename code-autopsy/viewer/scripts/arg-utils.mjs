import path from 'node:path';

export function parseArgs(argv = process.argv.slice(2)) {
  const result = {
    source: '',
    target: ''
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--source') {
      result.source = argv[i + 1] || '';
      i += 1;
    } else if (token === '--target') {
      result.target = argv[i + 1] || '';
      i += 1;
    }
  }

  return result;
}

export function ensureAbsolutePath(value, cwd = process.cwd()) {
  if (!value) {
    return '';
  }
  return path.isAbsolute(value) ? value : path.join(cwd, value);
}
