/**
 * Interactive setup command for attocode.
 *
 * Usage: attocode init
 */

import { createInterface } from 'readline';
import { writeFileSync, existsSync } from 'fs';
import { getConfigPath, ensureDirectories } from '../paths.js';
import { detectProviders } from '../first-run.js';

const rl = createInterface({
  input: process.stdin,
  output: process.stdout,
});

function question(prompt: string): Promise<string> {
  return new Promise(resolve => {
    rl.question(prompt, resolve);
  });
}

function select(prompt: string, options: string[]): Promise<number> {
  return new Promise(async resolve => {
    console.log(prompt);
    options.forEach((opt, i) => console.log(`  ${i + 1}) ${opt}`));
    const answer = await question('Choice: ');
    const choice = parseInt(answer, 10);
    if (choice >= 1 && choice <= options.length) {
      resolve(choice - 1);
    } else {
      resolve(0); // Default to first
    }
  });
}

export async function runInit(): Promise<void> {
  console.log('\n🚀 Attocode Setup\n');

  // Check existing config
  if (existsSync(getConfigPath())) {
    console.log(`Config already exists at ${getConfigPath()}`);
    const overwrite = await question('Overwrite? (y/N): ');
    if (overwrite.toLowerCase() !== 'y') {
      console.log('Setup cancelled.');
      rl.close();
      return;
    }
  }

  // Detect existing providers
  const detected = detectProviders();
  if (detected.length > 0) {
    console.log('✓ Detected API keys from environment:');
    detected.forEach(p => console.log(`  - ${p.name.toUpperCase()}`));
    console.log('');
  }

  // Select provider
  const providerChoice = await select('Select default provider:', [
    'Anthropic (Claude)',
    'OpenRouter (access to 100+ models)',
    'OpenAI',
  ]);

  const providerMap = ['anthropic', 'openrouter', 'openai'] as const;
  const provider = providerMap[providerChoice];

  // Check for API key
  const envVars = {
    anthropic: 'ANTHROPIC_API_KEY',
    openrouter: 'OPENROUTER_API_KEY',
    openai: 'OPENAI_API_KEY',
  };

  const envVar = envVars[provider];
  if (!process.env[envVar]) {
    console.log(`\n⚠️  No ${envVar} found in environment.`);
    console.log(`Set it before running attocode:`);
    console.log(`  export ${envVar}="your-api-key-here"\n`);
  }

  // Model selection - with custom option
  let model: string;

  const suggestedModels = {
    anthropic: [
      { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4 (recommended)' },
      { id: 'claude-opus-4-20250514', name: 'Claude Opus 4' },
      { id: 'claude-3-5-haiku-20241022', name: 'Claude 3.5 Haiku (fast)' },
    ],
    openrouter: [
      { id: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4' },
      { id: 'anthropic/claude-opus-4', name: 'Claude Opus 4' },
      { id: 'google/gemini-2.5-pro-preview', name: 'Gemini 2.5 Pro' },
      { id: 'openai/gpt-4o', name: 'GPT-4o' },
      { id: 'deepseek/deepseek-r1', name: 'DeepSeek R1' },
    ],
    openai: [
      { id: 'gpt-4o', name: 'GPT-4o (recommended)' },
      { id: 'gpt-4-turbo', name: 'GPT-4 Turbo' },
      { id: 'gpt-4', name: 'GPT-4' },
      { id: 'o1', name: 'o1 (reasoning)' },
    ],
  };

  const models = suggestedModels[provider];
  const modelOptions = [...models.map(m => m.name), '✏️  Enter custom model'];

  console.log('\nSelect model:');
  modelOptions.forEach((opt, i) => console.log(`  ${i + 1}) ${opt}`));

  if (provider === 'openrouter') {
    console.log('\n  💡 Browse all models: https://openrouter.ai/models');
  }

  const modelAnswer = await question('\nChoice (or type model ID directly): ');
  const modelChoice = parseInt(modelAnswer, 10);

  if (modelChoice >= 1 && modelChoice <= models.length) {
    // Selected from list
    model = models[modelChoice - 1].id;
  } else if (modelChoice === models.length + 1) {
    // Custom option selected
    const customModel = await question('Enter model ID: ');
    model = customModel.trim();
  } else if (modelAnswer.includes('/') || modelAnswer.includes('-')) {
    // Looks like they typed a model ID directly
    model = modelAnswer.trim();
  } else {
    // Default to first option
    model = models[0].id;
    console.log(`Using default: ${model}`);
  }

  console.log(`\n✓ Selected model: ${model}`);

  // Create config
  await ensureDirectories();

  const config = {
    "$schema": "https://attocode.dev/schema/config.json",
    "version": 1,
    "providers": {
      "default": provider
    },
    "model": model,
    "maxIterations": 50,
    "timeout": 300000,
    "features": {
      "memory": true,
      "planning": true,
      "sandbox": true
    }
  };

  writeFileSync(getConfigPath(), JSON.stringify(config, null, 2));
  console.log(`✓ Config saved to ${getConfigPath()}`);

  // Show next steps
  console.log('\n📋 Next steps:');
  if (!process.env[envVar]) {
    console.log(`  1. Set your API key: export ${envVar}="..."`);
    console.log('  2. Run: attocode');
  } else {
    console.log('  Run: attocode');
  }
  console.log('');

  rl.close();
}
