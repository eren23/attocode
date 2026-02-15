/**
 * Config Manager Tests
 *
 * Tests the unified config loader: file loading, merging, and validation.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdir, writeFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { loadConfig } from '../../src/config/config-manager.js';

// We need to mock the paths module to control where config files are loaded from
vi.mock('../../src/paths.js', async () => {
  const actual = await vi.importActual<typeof import('../../src/paths.js')>('../../src/paths.js');
  return {
    ...actual,
    getConfigPath: vi.fn(),
    getProjectDir: vi.fn(),
  };
});

import { getConfigPath, getProjectDir } from '../../src/paths.js';

const mockedGetConfigPath = vi.mocked(getConfigPath);
const mockedGetProjectDir = vi.mocked(getProjectDir);

describe('loadConfig', () => {
  let testDir: string;
  let userConfigDir: string;
  let projectDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `attocode-config-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    userConfigDir = join(testDir, 'user');
    projectDir = join(testDir, 'project', '.attocode');

    await mkdir(userConfigDir, { recursive: true });
    await mkdir(projectDir, { recursive: true });

    mockedGetConfigPath.mockReturnValue(join(userConfigDir, 'config.json'));
    mockedGetProjectDir.mockReturnValue(join(testDir, 'project', '.attocode'));
  });

  afterEach(async () => {
    await rm(testDir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it('returns empty config when no files exist', () => {
    mockedGetConfigPath.mockReturnValue(join(testDir, 'nonexistent', 'config.json'));
    mockedGetProjectDir.mockReturnValue(join(testDir, 'nonexistent', '.attocode'));

    const result = loadConfig();

    expect(result.config).toEqual({});
    expect(result.warnings).toHaveLength(0);
    expect(result.sources).toHaveLength(2);
    expect(result.sources[0].loaded).toBe(false);
    expect(result.sources[1].loaded).toBe(false);
  });

  it('loads user-level config', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({ model: 'gpt-4', maxIterations: 25 }),
    );

    const result = loadConfig();

    expect(result.config.model).toBe('gpt-4');
    expect(result.config.maxIterations).toBe(25);
    expect(result.warnings).toHaveLength(0);
    expect(result.sources[0].loaded).toBe(true);
  });

  it('loads project-level config', async () => {
    await writeFile(
      join(projectDir, 'config.json'),
      JSON.stringify({ model: 'claude-sonnet', planning: false }),
    );

    const result = loadConfig();

    expect(result.config.model).toBe('claude-sonnet');
    expect(result.config.planning).toBe(false);
    expect(result.sources[1].loaded).toBe(true);
  });

  it('project config overrides user config (deep merge)', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({
        model: 'gpt-4',
        maxIterations: 50,
        providers: { default: 'openrouter' },
      }),
    );
    await writeFile(
      join(projectDir, 'config.json'),
      JSON.stringify({
        model: 'claude-sonnet',
        providers: { default: 'anthropic' },
      }),
    );

    const result = loadConfig();

    // Project overrides
    expect(result.config.model).toBe('claude-sonnet');
    expect(result.config.providers?.default).toBe('anthropic');
    // User value preserved when not overridden
    expect(result.config.maxIterations).toBe(50);
  });

  it('returns validation warnings for invalid fields', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({ maxIterations: -5, temperature: 3.0 }),
    );

    const result = loadConfig();

    expect(result.warnings.length).toBeGreaterThan(0);
    expect(result.warnings.some((w) => w.includes('maxIterations'))).toBe(true);
    expect(result.warnings.some((w) => w.includes('temperature'))).toBe(true);
  });

  it('handles malformed JSON gracefully', async () => {
    await writeFile(join(userConfigDir, 'config.json'), '{ not valid json }');

    const result = loadConfig();

    expect(result.config).toEqual({});
    expect(result.warnings.length).toBeGreaterThan(0);
    expect(result.warnings[0]).toContain('failed to parse JSON');
    expect(result.sources[0].loaded).toBe(false);
  });

  it('handles non-object JSON gracefully', async () => {
    await writeFile(join(userConfigDir, 'config.json'), '"just a string"');

    const result = loadConfig();

    expect(result.config).toEqual({});
    expect(result.warnings[0]).toContain('expected a JSON object');
    expect(result.sources[0].loaded).toBe(false);
  });

  it('handles JSON array gracefully', async () => {
    await writeFile(join(userConfigDir, 'config.json'), '[1, 2, 3]');

    const result = loadConfig();

    expect(result.config).toEqual({});
    expect(result.warnings[0]).toContain('expected a JSON object');
  });

  it('skips project config when skipProject is true', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({ model: 'gpt-4' }),
    );
    await writeFile(
      join(projectDir, 'config.json'),
      JSON.stringify({ model: 'claude-sonnet' }),
    );

    const result = loadConfig({ skipProject: true });

    expect(result.config.model).toBe('gpt-4');
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0].level).toBe('user');
  });

  it('supports feature: false to disable', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({ planning: false, sandbox: false }),
    );

    const result = loadConfig();

    expect(result.config.planning).toBe(false);
    expect(result.config.sandbox).toBe(false);
    expect(result.warnings).toHaveLength(0);
  });

  it('deep merges nested objects (1-level)', async () => {
    await writeFile(
      join(userConfigDir, 'config.json'),
      JSON.stringify({
        providerResilience: {
          enabled: true,
          circuitBreaker: { failureThreshold: 5 },
          fallbackProviders: ['openai'],
        },
      }),
    );
    await writeFile(
      join(projectDir, 'config.json'),
      JSON.stringify({
        providerResilience: {
          circuitBreaker: { resetTimeout: 60000 },
          fallbackProviders: ['anthropic'],
        },
      }),
    );

    const result = loadConfig();

    const pr = result.config.providerResilience;
    expect(pr).toBeDefined();
    if (pr && typeof pr === 'object') {
      // enabled preserved from user (1-level merge within providerResilience)
      expect(pr.enabled).toBe(true);
      // circuitBreaker replaced entirely (2nd level objects replace, not merge)
      const cb = pr.circuitBreaker;
      expect(cb).toBeDefined();
      if (cb && typeof cb === 'object') {
        expect(cb.resetTimeout).toBe(60000);
        // failureThreshold NOT preserved — project's circuitBreaker replaces user's
        expect(cb.failureThreshold).toBeUndefined();
      }
      // arrays replace, not concat
      expect(pr.fallbackProviders).toEqual(['anthropic']);
    }
  });

  it('handles missing files gracefully', () => {
    mockedGetConfigPath.mockReturnValue('/nonexistent/path/config.json');
    mockedGetProjectDir.mockReturnValue('/nonexistent/project/.attocode');

    const result = loadConfig();

    expect(result.config).toEqual({});
    expect(result.warnings).toHaveLength(0);
    expect(result.sources.every((s) => !s.loaded)).toBe(true);
  });
});
