import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: [
        'getting-started/installation',
        'getting-started/quick-start',
        'getting-started/configuration',
        'getting-started/cli-reference',
      ],
    },
    {
      type: 'category',
      label: 'Architecture',
      items: [
        'architecture/overview',
        'architecture/core-agent',
        'architecture/execution-loop',
        'architecture/tool-system',
        'architecture/provider-adapters',
        'architecture/type-system',
        'architecture/data-flow',
      ],
    },
    {
      type: 'category',
      label: 'Features',
      items: [
        'features/tui-interface',
        'features/commands',
        'features/modes',
        'features/plan-mode',
        'features/sessions',
        'features/skills-and-agents',
        'features/mcp-integration',
      ],
    },
    {
      type: 'category',
      label: 'Multi-Agent',
      items: [
        'multi-agent/subagents',
        'multi-agent/swarm-mode',
        'multi-agent/task-decomposition',
        'multi-agent/shared-state',
        'multi-agent/quality-gates',
        'multi-agent/worker-pool',
      ],
    },
    {
      type: 'category',
      label: 'Context Engineering',
      items: [
        'context-engineering/overview',
        'context-engineering/kv-cache-optimization',
        'context-engineering/goal-recitation',
        'context-engineering/reversible-compaction',
        'context-engineering/failure-evidence',
        'context-engineering/auto-compaction',
        'context-engineering/codebase-context',
      ],
    },
    {
      type: 'category',
      label: 'Safety',
      items: [
        'safety/permission-model',
        'safety/policy-engine',
        'safety/sandboxing',
        'safety/bash-safety',
      ],
    },
    {
      type: 'category',
      label: 'Economics',
      items: [
        'economics/budget-system',
        'economics/loop-detection',
        'economics/phase-tracking',
        'economics/budget-pooling',
      ],
    },
    {
      type: 'category',
      label: 'Observability',
      items: [
        'observability/tracing',
        'observability/trace-dashboard',
        'observability/session-comparison',
        'observability/issue-detection',
      ],
    },
    {
      type: 'category',
      label: 'Extending Attocode',
      items: [
        'extending/custom-tools',
        'extending/custom-providers',
        'extending/custom-skills',
        'extending/custom-agents',
        'extending/integration-modules',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'reference/config-reference',
        'reference/event-catalog',
        'reference/tool-catalog',
        'reference/troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Internals',
      items: [
        'internals/persistence-schema',
        'internals/message-format',
        'internals/testing-guide',
        'internals/known-issues',
      ],
    },
  ],
};

export default sidebars;
