/**
 * Lesson 2: Multi-Provider Demo
 * 
 * Demonstrates auto-detection and usage of different LLM providers.
 */

// Import adapters to register them
import './adapters/openrouter.js';
import './adapters/anthropic.js';
import './adapters/openai.js';
import './adapters/azure.js';
import './adapters/mock.js';

import { getProvider, listProviders } from './provider.js';
import type { Message } from './types.js';

// =============================================================================
// DEMO
// =============================================================================

async function main() {
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Lesson 2: Provider Abstraction                                ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');
  
  // Show available providers
  console.log('\n📋 Available Providers:\n');
  const providers = listProviders();
  for (const p of providers) {
    const status = p.configured ? '✅ Configured' : '❌ Not configured';
    console.log(`   ${p.name.padEnd(15)} ${status} (priority: ${p.priority})`);
  }

  // Get the best available provider
  console.log('\n🔌 Auto-detecting provider...\n');
  
  try {
    const provider = await getProvider();
    
    console.log(`   Using: ${provider.name}`);
    console.log(`   Model: ${provider.defaultModel}`);
    
    // Test the provider with a simple conversation
    console.log('\n💬 Testing conversation:\n');
    
    const messages: Message[] = [
      { role: 'system', content: 'You are a helpful assistant. Be concise.' },
      { role: 'user', content: 'What is 2 + 2? Answer in one word.' },
    ];
    
    console.log('   User: What is 2 + 2? Answer in one word.');
    
    const response = await provider.chat(messages, {
      maxTokens: 100,
      temperature: 0,
    });
    
    console.log(`   Assistant: ${response.content}`);
    console.log(`\n   Stop reason: ${response.stopReason}`);
    if (response.usage) {
      console.log(`   Tokens: ${response.usage.inputTokens} in, ${response.usage.outputTokens} out`);
    }
    
    // Demonstrate provider switching
    console.log('\n════════════════════════════════════════════════════════════════');
    console.log('\n📝 Key Concepts Demonstrated:');
    console.log('   1. Providers register themselves on import');
    console.log('   2. Auto-detection picks the best available provider');
    console.log('   3. All providers share the same interface');
    console.log('   4. Provider-specific details are hidden from the caller');
    
  } catch (error) {
    console.error('\n❌ Error:', (error as Error).message);
    console.log('\n💡 Tip: Set one of these environment variables:');
    console.log('   - OPENROUTER_API_KEY for OpenRouter (100+ models)');
    console.log('   - ANTHROPIC_API_KEY for Claude');
    console.log('   - OPENAI_API_KEY for GPT-4');
    console.log('   - AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT for Azure');
    console.log('\n   Or the mock provider will be used for testing.');
  }
}

main().catch(console.error);
