import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'ReAct Execution Engine',
    description: (
      <>
        A production-grade ReAct loop with resilient LLM calls, batched tool execution,
        budget-aware iteration, and graceful degradation under resource pressure.
      </>
    ),
  },
  {
    title: 'Multi-Agent Swarm',
    description: (
      <>
        Wave-based orchestration decomposes complex tasks into dependency graphs,
        dispatches parallel workers, and synthesizes results with quality gates.
      </>
    ),
  },
  {
    title: 'Context Engineering',
    description: (
      <>
        Five techniques (P/Q/R/S/T) for KV-cache optimization, goal recitation,
        reversible compaction, failure evidence, and serialization diversity.
      </>
    ),
  },
  {
    title: 'Full Terminal UI',
    description: (
      <>
        Ink/React-based TUI with anti-flicker rendering, approval dialogs,
        8 toggle panels, command palette, and rich diff display.
      </>
    ),
  },
  {
    title: 'Safety-First Permissions',
    description: (
      <>
        Four-tier danger classification, policy profiles, platform sandboxing
        (Seatbelt/Landlock/Docker), and interactive approval workflows.
      </>
    ),
  },
  {
    title: 'Provider Resilience',
    description: (
      <>
        Anthropic, OpenAI, and OpenRouter adapters with circuit breakers,
        fallback chains, prompt caching, and automatic cost tracking.
      </>
    ),
  },
];

function Feature({title, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center padding-horiz--md" style={{paddingTop: '2rem'}}>
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
