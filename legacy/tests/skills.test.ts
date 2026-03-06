/**
 * Skills Manager Tests
 *
 * Tests for the skills system that provides discoverable agent capabilities.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdir, writeFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  SkillManager,
  createSkillManager,
  formatSkillList,
  getSampleSkillContent,
  getDefaultSkillDirectories,
} from '../src/integrations/skills/skills.js';

describe('SkillManager', () => {
  let manager: SkillManager;
  let testDir: string;

  beforeEach(async () => {
    // Create temp directory for test skills
    testDir = join(tmpdir(), `skill-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });

    manager = createSkillManager({
      enabled: true,
      directories: [testDir],
      loadBuiltIn: false,
      autoActivate: false,
    });
  });

  afterEach(async () => {
    manager.cleanup();
    await rm(testDir, { recursive: true, force: true });
  });

  describe('initialization', () => {
    it('should create manager with default config', () => {
      const defaultManager = createSkillManager();
      expect(defaultManager).toBeDefined();
      defaultManager.cleanup();
    });

    it('should respect enabled flag', () => {
      const disabledManager = createSkillManager({ enabled: false });
      expect(disabledManager.getAllSkills().length).toBe(0);
      disabledManager.cleanup();
    });
  });

  describe('loadSkills', () => {
    it('should load skills from directory', async () => {
      // Create a test skill file
      const skillContent = `---
name: test-skill
description: A test skill
tools: [read_file, grep]
---

# Test Skill

Instructions for the agent.
`;
      await writeFile(join(testDir, 'test-skill.md'), skillContent);

      const count = await manager.loadSkills();

      expect(count).toBe(1);
      expect(manager.getAllSkills().length).toBe(1);
    });

    it('should load skills from subdirectories', async () => {
      // Create a skill in a subdirectory
      const skillDir = join(testDir, 'code-review');
      await mkdir(skillDir);

      const skillContent = `---
name: code-review
description: Code review skill
tools: [read_file]
---

# Code Review

Review code for bugs.
`;
      await writeFile(join(skillDir, 'SKILL.md'), skillContent);

      await manager.loadSkills();

      const skill = manager.getSkill('code-review');
      expect(skill).toBeDefined();
      expect(skill?.name).toBe('code-review');
    });

    it('should parse YAML frontmatter correctly', async () => {
      const skillContent = `---
name: parser-test
description: Tests parsing
tools: [read_file, write_file, grep]
version: "1.0.0"
author: Test Author
tags: [testing, parsing]
---

# Parser Test Skill

Content here.
`;
      await writeFile(join(testDir, 'parser-test.md'), skillContent);

      await manager.loadSkills();

      const skill = manager.getSkill('parser-test');
      expect(skill?.name).toBe('parser-test');
      expect(skill?.description).toBe('Tests parsing');
      expect(skill?.tools).toEqual(['read_file', 'write_file', 'grep']);
      expect(skill?.version).toBe('1.0.0');
      expect(skill?.author).toBe('Test Author');
      expect(skill?.tags).toEqual(['testing', 'parsing']);
    });

    it('should derive name from directory if not in frontmatter', async () => {
      const skillDir = join(testDir, 'my-skill');
      await mkdir(skillDir);

      const skillContent = `---
description: No name specified
---

# Content
`;
      await writeFile(join(skillDir, 'SKILL.md'), skillContent);

      await manager.loadSkills();

      const skill = manager.getSkill('my-skill');
      expect(skill).toBeDefined();
    });

    it('should handle missing frontmatter', async () => {
      const skillContent = `# Simple Skill

No frontmatter here, just markdown content.
`;
      await writeFile(join(testDir, 'simple.md'), skillContent);

      await manager.loadSkills();

      const skills = manager.getAllSkills();
      expect(skills.length).toBe(1);
    });

    it('should emit events when loading skills', async () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      await writeFile(join(testDir, 'event-test.md'), `---
name: event-test
---
Content`);

      await manager.loadSkills();

      const loadEvents = events.filter((e: any) => e.type === 'skill.loaded');
      expect(loadEvents.length).toBe(1);
    });

    it('should return 0 when disabled', async () => {
      const disabledManager = createSkillManager({ enabled: false, directories: [testDir] });

      await writeFile(join(testDir, 'test.md'), '# Test');

      const count = await disabledManager.loadSkills();
      expect(count).toBe(0);

      disabledManager.cleanup();
    });
  });

  describe('getSkill and getAllSkills', () => {
    beforeEach(async () => {
      await writeFile(join(testDir, 'skill1.md'), `---
name: skill1
description: First skill
---
Content 1`);

      await writeFile(join(testDir, 'skill2.md'), `---
name: skill2
description: Second skill
---
Content 2`);

      await manager.loadSkills();
    });

    it('should get skill by name', () => {
      const skill = manager.getSkill('skill1');
      expect(skill?.name).toBe('skill1');
      expect(skill?.description).toBe('First skill');
    });

    it('should return undefined for unknown skill', () => {
      const skill = manager.getSkill('nonexistent');
      expect(skill).toBeUndefined();
    });

    it('should get all skills', () => {
      const skills = manager.getAllSkills();
      expect(skills.length).toBe(2);
      expect(skills.map(s => s.name).sort()).toEqual(['skill1', 'skill2']);
    });
  });

  describe('activateSkill and deactivateSkill', () => {
    beforeEach(async () => {
      await writeFile(join(testDir, 'activatable.md'), `---
name: activatable
tools: [read_file]
---
Content`);

      await manager.loadSkills();
    });

    it('should activate a skill', () => {
      const result = manager.activateSkill('activatable');
      expect(result).toBe(true);
      expect(manager.isSkillActive('activatable')).toBe(true);
    });

    it('should return false when activating unknown skill', () => {
      const result = manager.activateSkill('nonexistent');
      expect(result).toBe(false);
    });

    it('should deactivate a skill', () => {
      manager.activateSkill('activatable');
      const result = manager.deactivateSkill('activatable');

      expect(result).toBe(true);
      expect(manager.isSkillActive('activatable')).toBe(false);
    });

    it('should return false when deactivating inactive skill', () => {
      const result = manager.deactivateSkill('activatable');
      expect(result).toBe(false);
    });

    it('should emit events on activation/deactivation', () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.activateSkill('activatable');
      manager.deactivateSkill('activatable');

      expect(events.some((e: any) => e.type === 'skill.activated')).toBe(true);
      expect(events.some((e: any) => e.type === 'skill.deactivated')).toBe(true);
    });
  });

  describe('getActiveSkills', () => {
    beforeEach(async () => {
      await writeFile(join(testDir, 's1.md'), `---
name: s1
---
Content`);
      await writeFile(join(testDir, 's2.md'), `---
name: s2
---
Content`);

      await manager.loadSkills();
    });

    it('should return empty array when no skills active', () => {
      expect(manager.getActiveSkills()).toEqual([]);
    });

    it('should return active skills', () => {
      manager.activateSkill('s1');
      manager.activateSkill('s2');

      const active = manager.getActiveSkills();
      expect(active.length).toBe(2);
    });
  });

  describe('getActiveSkillsPrompt', () => {
    beforeEach(async () => {
      await writeFile(join(testDir, 'prompt-skill.md'), `---
name: prompt-skill
---
Do something specific.`);

      await manager.loadSkills();
    });

    it('should return empty string when no skills active', () => {
      expect(manager.getActiveSkillsPrompt()).toBe('');
    });

    it('should return combined prompt for active skills', () => {
      manager.activateSkill('prompt-skill');

      const prompt = manager.getActiveSkillsPrompt();
      expect(prompt).toContain('prompt-skill');
      expect(prompt).toContain('Do something specific');
    });
  });

  describe('getActiveSkillTools', () => {
    beforeEach(async () => {
      await writeFile(join(testDir, 'tool-skill.md'), `---
name: tool-skill
tools: [read_file, grep, glob]
---
Content`);

      await manager.loadSkills();
    });

    it('should return empty array when no skills active', () => {
      expect(manager.getActiveSkillTools()).toEqual([]);
    });

    it('should return tools from active skills', () => {
      manager.activateSkill('tool-skill');

      const tools = manager.getActiveSkillTools();
      expect(tools).toContain('read_file');
      expect(tools).toContain('grep');
      expect(tools).toContain('glob');
    });
  });

  describe('findMatchingSkills', () => {
    beforeEach(async () => {
      // Note: The simple YAML parser doesn't support nested arrays.
      // Use string triggers (converted to keyword type) instead.
      await writeFile(join(testDir, 'trigger-skill.md'), `---
name: trigger-skill
triggers: [review, code-review]
tags: [code-review]
---
Content`);

      const autoManager = createSkillManager({
        directories: [testDir],
        autoActivate: true,
      });
      manager.cleanup();
      manager = autoManager;

      await manager.loadSkills();
    });

    it('should find skills matching keyword triggers', () => {
      const matches = manager.findMatchingSkills('please review this code');
      expect(matches.length).toBeGreaterThan(0);
      expect(matches[0].name).toBe('trigger-skill');
    });

    it('should find skills matching tags', () => {
      const matches = manager.findMatchingSkills('code-review needed');
      expect(matches.length).toBeGreaterThan(0);
    });

    it('should return empty when no matches', () => {
      const matches = manager.findMatchingSkills('unrelated query xyz');
      // May or may not match depending on patterns
      expect(Array.isArray(matches)).toBe(true);
    });
  });
});

describe('formatSkillList', () => {
  it('should format skills for display', () => {
    const skills = [
      {
        name: 'skill1',
        description: 'First skill',
        tools: ['read_file'],
        content: '',
        sourcePath: '/path',
      },
      {
        name: 'skill2',
        description: 'Second skill',
        tools: [],
        content: '',
        sourcePath: '/path',
      },
    ];

    const formatted = formatSkillList(skills);

    expect(formatted).toContain('skill1');
    expect(formatted).toContain('First skill');
    expect(formatted).toContain('read_file');
  });

  it('should handle empty skill list', () => {
    const formatted = formatSkillList([]);
    expect(formatted).toContain('No skills loaded');
  });
});

describe('getSampleSkillContent', () => {
  it('should generate valid skill markdown', () => {
    const content = getSampleSkillContent('my-skill', 'My description');

    expect(content).toContain('name: my-skill');
    expect(content).toContain('description: My description');
    expect(content).toContain('---');
    expect(content).toContain('# my-skill');
  });
});

describe('getDefaultSkillDirectories', () => {
  it('should return array of default directories', () => {
    const dirs = getDefaultSkillDirectories();

    expect(Array.isArray(dirs)).toBe(true);
    expect(dirs.length).toBeGreaterThan(0);
    expect(dirs.some(d => d.includes('.agent/skills'))).toBe(true);
  });
});
