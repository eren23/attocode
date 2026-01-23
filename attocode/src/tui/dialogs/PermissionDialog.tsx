/**
 * Permission Dialog Component
 *
 * Displays tool permission requests with danger level indicators.
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import type { PermissionDialogConfig } from '../types.js';
import type { Theme } from '../theme/index.js';
import { BaseDialog } from './Dialog.js';

export interface PermissionDialogProps {
  theme: Theme;
  tool: string;
  args: Record<string, unknown>;
  dangerLevel: 'safe' | 'moderate' | 'dangerous';
  onAllow: () => void;
  onDeny: () => void;
  onAllowAlways?: () => void;
}

// Danger level configuration
const dangerConfig = {
  safe: {
    icon: '[OK]',
    label: 'Safe',
    color: 'success' as const,
    description: 'This action is considered safe.',
  },
  moderate: {
    icon: '[!]',
    label: 'Moderate',
    color: 'warning' as const,
    description: 'This action may modify files or state.',
  },
  dangerous: {
    icon: '[!!]',
    label: 'Dangerous',
    color: 'error' as const,
    description: 'This action could have significant effects.',
  },
};

/**
 * Format tool arguments for display.
 */
function formatArgs(args: Record<string, unknown>, theme: Theme): React.ReactNode {
  const entries = Object.entries(args);
  if (entries.length === 0) {
    return <Text color={theme.colors.textMuted}>No arguments</Text>;
  }

  return (
    <Box flexDirection="column">
      {entries.map(([key, value]) => {
        let displayValue: string;
        if (typeof value === 'string') {
          // Truncate long strings
          displayValue = value.length > 50 ? value.slice(0, 47) + '...' : value;
          // Escape newlines
          displayValue = displayValue.replace(/\n/g, '\\n');
        } else {
          displayValue = JSON.stringify(value);
          if (displayValue.length > 50) {
            displayValue = displayValue.slice(0, 47) + '...';
          }
        }

        return (
          <Box key={key}>
            <Text color={theme.colors.accent}>{key}</Text>
            <Text color={theme.colors.textMuted}>: </Text>
            <Text color={theme.colors.text}>{displayValue}</Text>
          </Box>
        );
      })}
    </Box>
  );
}

/**
 * Permission dialog for tool execution approval.
 */
export function PermissionDialog({
  theme,
  tool,
  args,
  dangerLevel,
  onAllow,
  onDeny,
  onAllowAlways,
}: PermissionDialogProps) {
  const [selected, setSelected] = React.useState<'allow' | 'deny' | 'always'>('allow');
  const danger = dangerConfig[dangerLevel];
  const dangerColor = theme.colors[danger.color];

  const options: Array<{ key: 'allow' | 'deny' | 'always'; label: string; shortcut: string }> = [
    { key: 'allow', label: 'Allow', shortcut: 'y' },
    { key: 'deny', label: 'Deny', shortcut: 'n' },
  ];

  if (onAllowAlways) {
    options.push({ key: 'always', label: 'Always Allow', shortcut: 'a' });
  }

  useInput((input, key) => {
    if (key.leftArrow || key.tab) {
      const currentIndex = options.findIndex(o => o.key === selected);
      const newIndex = (currentIndex - 1 + options.length) % options.length;
      setSelected(options[newIndex].key);
    } else if (key.rightArrow) {
      const currentIndex = options.findIndex(o => o.key === selected);
      const newIndex = (currentIndex + 1) % options.length;
      setSelected(options[newIndex].key);
    } else if (key.return) {
      if (selected === 'allow') onAllow();
      else if (selected === 'deny') onDeny();
      else if (selected === 'always') onAllowAlways?.();
    } else if (key.escape || input === 'n' || input === 'N') {
      onDeny();
    } else if (input === 'y' || input === 'Y') {
      onAllow();
    } else if ((input === 'a' || input === 'A') && onAllowAlways) {
      onAllowAlways();
    }
  });

  return (
    <BaseDialog theme={theme} title="Permission Request" width={60}>
      {/* Danger level indicator */}
      <Box marginBottom={1} justifyContent="center">
        <Text color={dangerColor} bold>
          {danger.icon} {danger.label}
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text color={theme.colors.textMuted}>{danger.description}</Text>
      </Box>

      {/* Tool name */}
      <Box marginBottom={1}>
        <Text>Tool: </Text>
        <Text color={theme.colors.toolMessage} bold>{tool}</Text>
      </Box>

      {/* Arguments */}
      <Box flexDirection="column" marginBottom={1}>
        <Text color={theme.colors.textMuted}>Arguments:</Text>
        <Box marginLeft={2} marginTop={1}>
          {formatArgs(args, theme)}
        </Box>
      </Box>

      {/* Action buttons */}
      <Box marginTop={2} justifyContent="center" gap={2}>
        {options.map((option) => {
          const isSelected = selected === option.key;
          const buttonColor = option.key === 'deny'
            ? theme.colors.error
            : option.key === 'always'
              ? theme.colors.warning
              : theme.colors.success;

          return (
            <Box
              key={option.key}
              borderStyle={isSelected ? 'single' : undefined}
              borderColor={buttonColor}
              paddingX={1}
            >
              <Text
                color={isSelected ? buttonColor : theme.colors.textMuted}
                bold={isSelected}
              >
                [{option.label}]
              </Text>
              <Text color={theme.colors.accent}> {option.shortcut}</Text>
            </Box>
          );
        })}
      </Box>

      {/* Keyboard hints */}
      <Box marginTop={2} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>y</Text>/n
          {onAllowAlways && <Text>/<Text color={theme.colors.accent}>a</Text></Text>}
          {' '}or <Text color={theme.colors.accent}>Tab</Text>/<Text color={theme.colors.accent}>Enter</Text>
        </Text>
      </Box>
    </BaseDialog>
  );
}

export default PermissionDialog;
