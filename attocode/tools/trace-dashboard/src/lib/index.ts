/**
 * Trace Viewer Library
 *
 * Library for visualizing and analyzing agent execution traces.
 * Consolidated from the standalone trace-viewer tool.
 */

// Types
export * from './types.js';

// Parser
export { JSONLParser, createJSONLParser } from './parser/jsonl-parser.js';

// Analyzers
export {
  SessionAnalyzer,
  createSessionAnalyzer,
  InefficiencyDetector,
  createInefficiencyDetector,
  TokenAnalyzer,
  createTokenAnalyzer,
} from './analyzer/index.js';

// Views
export {
  SummaryView,
  createSummaryView,
  TimelineView,
  createTimelineView,
  TreeView,
  createTreeView,
  TokenFlowView,
  createTokenFlowView,
} from './views/index.js';

// Output
export {
  TerminalRenderer,
  createTerminalRenderer,
  JSONExporter,
  createJSONExporter,
  HTMLGenerator,
  createHTMLGenerator,
} from './output/index.js';
