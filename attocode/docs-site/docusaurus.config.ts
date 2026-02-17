import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Attocode',
  tagline: 'Production AI Coding Agent — From First Principles',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://eren23.github.io',
  baseUrl: '/attocode/',

  organizationName: 'eren23',
  projectName: 'attocode',

  onBrokenLinks: 'warn',

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },
  themes: ['@docusaurus/theme-mermaid'],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          routeBasePath: 'docs',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Attocode',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          href: 'https://github.com/eren23/attocode',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {label: 'Getting Started', to: '/docs/getting-started/installation'},
            {label: 'Architecture', to: '/docs/architecture/overview'},
            {label: 'Features', to: '/docs/features/tui-interface'},
          ],
        },
        {
          title: 'Advanced',
          items: [
            {label: 'Multi-Agent', to: '/docs/multi-agent/subagents'},
            {label: 'Context Engineering', to: '/docs/context-engineering/overview'},
            {label: 'Swarm Mode', to: '/docs/multi-agent/swarm-mode'},
          ],
        },
        {
          title: 'More',
          items: [
            {label: 'Extending Attocode', to: '/docs/extending/custom-tools'},
            {label: 'Reference', to: '/docs/reference/config-reference'},
            {label: 'GitHub', href: 'https://github.com/eren23/attocode'},
          ],
        },
      ],
      copyright: `Copyright \u00a9 ${new Date().getFullYear()} Attocode. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'yaml', 'typescript'],
    },
    mermaid: {
      theme: {light: 'neutral', dark: 'dark'},
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
