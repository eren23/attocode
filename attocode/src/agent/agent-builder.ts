/**
 * Builder pattern for creating ProductionAgent instances.
 *
 * Extracted from agent.ts to reduce file size while maintaining
 * backward-compatible re-exports.
 */

import type {
  ProductionAgentConfig,
  LLMProvider,
  ToolDefinition,
  AgentRoleConfig,
  MultiAgentConfig,
} from '../types.js';

import { ProductionAgent } from '../agent.js';

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a production agent with the given configuration.
 */
export function createProductionAgent(
  config: Partial<ProductionAgentConfig> & { provider: LLMProvider },
): ProductionAgent {
  return new ProductionAgent(config);
}

// =============================================================================
// BUILDER PATTERN
// =============================================================================

/**
 * Builder for creating customized production agents.
 */
export class ProductionAgentBuilder {
  private config: Partial<ProductionAgentConfig> = {};

  /**
   * Set the LLM provider.
   */
  provider(provider: LLMProvider): this {
    this.config.provider = provider;
    return this;
  }

  /**
   * Set the model.
   */
  model(model: string): this {
    this.config.model = model;
    return this;
  }

  /**
   * Set the system prompt.
   */
  systemPrompt(prompt: string): this {
    this.config.systemPrompt = prompt;
    return this;
  }

  /**
   * Add tools.
   */
  tools(tools: ToolDefinition[]): this {
    this.config.tools = tools;
    return this;
  }

  /**
   * Configure hooks.
   */
  hooks(config: ProductionAgentConfig['hooks']): this {
    this.config.hooks = config;
    return this;
  }

  /**
   * Configure plugins.
   */
  plugins(config: ProductionAgentConfig['plugins']): this {
    this.config.plugins = config;
    return this;
  }

  /**
   * Configure memory.
   */
  memory(config: ProductionAgentConfig['memory']): this {
    this.config.memory = config;
    return this;
  }

  /**
   * Configure planning.
   */
  planning(config: ProductionAgentConfig['planning']): this {
    this.config.planning = config;
    return this;
  }

  /**
   * Configure reflection.
   */
  reflection(config: ProductionAgentConfig['reflection']): this {
    this.config.reflection = config;
    return this;
  }

  /**
   * Configure observability.
   */
  observability(config: ProductionAgentConfig['observability']): this {
    this.config.observability = config;
    return this;
  }

  /**
   * Configure sandbox.
   */
  sandbox(config: ProductionAgentConfig['sandbox']): this {
    this.config.sandbox = config;
    return this;
  }

  /**
   * Configure human-in-the-loop.
   */
  humanInLoop(config: ProductionAgentConfig['humanInLoop']): this {
    this.config.humanInLoop = config;
    return this;
  }

  /**
   * Configure routing.
   */
  routing(config: ProductionAgentConfig['routing']): this {
    this.config.routing = config;
    return this;
  }

  /**
   * Configure multi-agent coordination (Lesson 17).
   */
  multiAgent(config: ProductionAgentConfig['multiAgent']): this {
    this.config.multiAgent = config;
    return this;
  }

  /**
   * Add a role to multi-agent config.
   */
  addRole(role: AgentRoleConfig): this {
    // Handle undefined, false, or disabled config
    if (!this.config.multiAgent) {
      this.config.multiAgent = { enabled: true, roles: [] };
    }
    // Ensure roles array exists
    const multiAgentConfig = this.config.multiAgent as MultiAgentConfig;
    if (!multiAgentConfig.roles) {
      multiAgentConfig.roles = [];
    }
    multiAgentConfig.roles.push(role);
    return this;
  }

  /**
   * Configure ReAct pattern (Lesson 18).
   */
  react(config: ProductionAgentConfig['react']): this {
    this.config.react = config;
    return this;
  }

  /**
   * Configure execution policies (Lesson 23).
   */
  executionPolicy(config: ProductionAgentConfig['executionPolicy']): this {
    this.config.executionPolicy = config;
    return this;
  }

  /**
   * Configure thread management (Lesson 24).
   */
  threads(config: ProductionAgentConfig['threads']): this {
    this.config.threads = config;
    return this;
  }

  /**
   * Configure skills system.
   */
  skills(config: ProductionAgentConfig['skills']): this {
    this.config.skills = config;
    return this;
  }

  /**
   * Set max iterations.
   */
  maxIterations(max: number): this {
    this.config.maxIterations = max;
    return this;
  }

  /**
   * Set timeout.
   */
  timeout(ms: number): this {
    this.config.timeout = ms;
    return this;
  }

  /**
   * Disable a feature.
   */
  disable(
    feature: keyof Omit<
      ProductionAgentConfig,
      'provider' | 'tools' | 'systemPrompt' | 'model' | 'maxIterations' | 'timeout'
    >,
  ): this {
    (this.config as Record<string, unknown>)[feature] = false;
    return this;
  }

  /**
   * Build the agent.
   */
  build(): ProductionAgent {
    if (!this.config.provider) {
      throw new Error('Provider is required');
    }
    return new ProductionAgent(
      this.config as Partial<ProductionAgentConfig> & { provider: LLMProvider },
    );
  }
}

/**
 * Start building a production agent.
 */
export function buildAgent(): ProductionAgentBuilder {
  return new ProductionAgentBuilder();
}
