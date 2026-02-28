import test from 'node:test';
import assert from 'node:assert/strict';

import { ensureAbsolutePath, parseArgs } from '../scripts/arg-utils.mjs';

test('parseArgs reads source and target', () => {
  const parsed = parseArgs(['--source', '/tmp/source', '--target', '/tmp/target']);
  assert.equal(parsed.source, '/tmp/source');
  assert.equal(parsed.target, '/tmp/target');
});

test('ensureAbsolutePath joins relative paths', () => {
  const value = ensureAbsolutePath('data/output', '/repo');
  assert.equal(value, '/repo/data/output');
});

test('ensureAbsolutePath keeps absolute paths unchanged', () => {
  const value = ensureAbsolutePath('/tmp/output', '/repo');
  assert.equal(value, '/tmp/output');
});
