/**
 * Lesson 7: MCP Integration Demo
 * 
 * Demonstrates connecting to MCP servers and using MCP tools.
 */

import chalk from 'chalk';
import { MCPClient } from './mcp-client.js';
import { MCPToolManager, getMCPTools } from './mcp-tools.js';
import * as path from 'node:path';

// =============================================================================
// DEMO
// =============================================================================

async function demoMCPClient() {
  console.log(chalk.bold('\n🔌 Demo: MCP Client Connection\n'));

  const client = new MCPClient();

  // Set up event logging
  client.on(event => {
    switch (event.type) {
      case 'connected':
        console.log(chalk.green(`   ✓ Connected to ${event.server}`));
        break;
      case 'disconnected':
        console.log(chalk.yellow(`   ✓ Disconnected: ${event.reason}`));
        break;
      case 'tool_called':
        console.log(chalk.cyan(`   → Calling tool: ${event.tool}`));
        break;
      case 'tool_result':
        const preview = JSON.stringify(event.result).slice(0, 50);
        console.log(chalk.cyan(`   ← Result: ${preview}...`));
        break;
      case 'error':
        console.log(chalk.red(`   ✗ Error: ${event.error.message}`));
        break;
    }
  });

  try {
    // Connect to our example server
    console.log('   Connecting to example MCP server...');
    const serverPath = path.join(import.meta.dirname, 'example-server', 'server.ts');
    
    const initResult = await client.connect({
      type: 'stdio',
      command: 'npx',
      args: ['tsx', serverPath],
    });

    console.log(`   Server: ${initResult.serverInfo.name} v${initResult.serverInfo.version}`);
    console.log(`   Protocol: ${initResult.protocolVersion}`);

    // List available tools
    console.log(chalk.cyan('\n   Available tools:'));
    const tools = await client.listTools();
    for (const tool of tools) {
      console.log(`     - ${tool.name}: ${tool.description}`);
    }

    // Call some tools
    console.log(chalk.cyan('\n   Calling tools:'));
    
    const echoResult = await client.callTool('echo', { message: 'Hello, MCP!' });
    console.log(`     echo: ${echoResult.content[0].type === 'text' ? echoResult.content[0].text : '?'}`);
    
    const calcResult = await client.callTool('calculate', { operation: 'multiply', a: 7, b: 6 });
    console.log(`     calculate: ${calcResult.content[0].type === 'text' ? calcResult.content[0].text : '?'}`);
    
    const timeResult = await client.callTool('get_time', { timezone: 'UTC' });
    console.log(`     get_time: ${timeResult.content[0].type === 'text' ? timeResult.content[0].text : '?'}`);

    // Disconnect
    await client.disconnect();
    console.log(chalk.green('\n   ✓ Demo complete'));

  } catch (error) {
    console.log(chalk.red(`\n   ✗ Error: ${(error as Error).message}`));
    console.log(chalk.yellow('   Make sure you have tsx installed: npm install -g tsx'));
    await client.disconnect();
  }
}

async function demoMCPToolManager() {
  console.log(chalk.bold('\n🧰 Demo: MCP Tool Manager\n'));

  const manager = new MCPToolManager();

  // Create and connect a client
  const client = new MCPClient();
  
  try {
    const serverPath = path.join(import.meta.dirname, 'example-server', 'server.ts');
    
    await client.connect({
      type: 'stdio',
      command: 'npx',
      args: ['tsx', serverPath],
    });

    // Add client to manager
    await manager.addClient('example', client);

    // List all tools
    console.log(chalk.cyan('   All tools from all servers:'));
    const tools = manager.listTools();
    for (const tool of tools) {
      console.log(`     - ${tool}`);
    }

    // Get tool descriptions (for LLM)
    console.log(chalk.cyan('\n   Tool descriptions for LLM:'));
    const descriptions = manager.getToolDescriptions();
    console.log(`     ${descriptions.length} tools available`);

    // Call a tool through the manager
    console.log(chalk.cyan('\n   Calling tool through manager:'));
    const result = await manager.callTool('random_number', { min: 1, max: 100 });
    console.log(`     Result: ${result.output}`);

    // Get as agent tools
    console.log(chalk.cyan('\n   Converting to agent tools:'));
    const agentTools = manager.getAgentTools();
    console.log(`     ${agentTools.length} agent-compatible tools created`);

    // Test an agent tool
    const echoTool = agentTools.find(t => t.name === 'echo');
    if (echoTool) {
      const toolResult = await echoTool.execute({ message: 'Agent calling MCP!' });
      console.log(`     Agent tool result: ${toolResult.output}`);
    }

    await client.disconnect();
    console.log(chalk.green('\n   ✓ Demo complete'));

  } catch (error) {
    console.log(chalk.red(`\n   ✗ Error: ${(error as Error).message}`));
    await client.disconnect();
  }
}

async function demoIntegrationPattern() {
  console.log(chalk.bold('\n🔄 Demo: Agent + MCP Integration Pattern\n'));

  console.log(chalk.cyan('   Typical integration flow:'));
  console.log(`
   1. Agent initializes
      ↓
   2. Connect to MCP servers (from config)
      ↓
   3. Collect all tools (built-in + MCP)
      ↓
   4. Run agent loop
      │
      ├─ LLM decides to use tool
      │  ↓
      ├─ Check if MCP tool → route to MCP client
      │  ↓
      └─ Return result to LLM
`);

  console.log(chalk.cyan('   Code pattern:'));
  console.log(chalk.gray(`
   // Initialize
   const mcpManager = new MCPToolManager();
   
   // Connect to servers from config
   for (const server of config.mcpServers) {
     const client = new MCPClient();
     await client.connect(server);
     await mcpManager.addClient(server.name, client);
   }
   
   // Combine with built-in tools
   const allTools = [
     ...builtInTools,
     ...mcpManager.getAgentTools(),
   ];
   
   // Use in agent
   const agent = new Agent({ tools: allTools });
`));
}

// =============================================================================
// MAIN
// =============================================================================

async function main() {
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Lesson 7: MCP Integration                                     ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');

  const demo = process.argv[2] || 'all';

  switch (demo) {
    case 'client':
      await demoMCPClient();
      break;
    case 'manager':
      await demoMCPToolManager();
      break;
    case 'pattern':
      await demoIntegrationPattern();
      break;
    case 'all':
    default:
      await demoMCPClient();
      await demoMCPToolManager();
      await demoIntegrationPattern();
  }

  console.log('\n════════════════════════════════════════════════════════════════');
  console.log('\n📝 Key Concepts Demonstrated:');
  console.log('   1. MCP client connects to servers via stdio');
  console.log('   2. Tools are discovered dynamically from servers');
  console.log('   3. MCPToolManager aggregates tools from multiple servers');
  console.log('   4. MCP tools convert to agent-compatible format');
  console.log('\nTry individual demos:');
  console.log('   npx tsx 07-mcp-integration/main.ts client');
  console.log('   npx tsx 07-mcp-integration/main.ts manager');
  console.log('   npx tsx 07-mcp-integration/main.ts pattern');
}

main().catch(console.error);
