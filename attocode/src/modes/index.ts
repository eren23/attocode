/**
 * Mode Entry Points
 *
 * This module exports the different operational modes for the agent:
 * - TUI Mode: Full-featured terminal UI with Ink/React
 * - REPL Mode: Simple readline-based interface
 */

export { startTUIMode, type TUIModeOptions } from './tui.js';
export { startProductionREPL, type REPLOptions } from './repl.js';
