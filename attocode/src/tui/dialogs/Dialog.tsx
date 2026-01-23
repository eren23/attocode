/**
 * Dialog Component
 *
 * Base dialog component for modal interactions.
 */

import React, { useCallback } from 'react';
import { Box, Text, useInput } from 'ink';
import type { DialogConfig, DialogOption } from '../types.js';
import type { Theme } from '../theme/index.js';

export interface DialogProps {
  theme: Theme;
  config: DialogConfig;
  onConfirm: (value: unknown) => void;
  onCancel: () => void;
}

export interface BaseDialogProps {
  theme: Theme;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}

/**
 * Base dialog wrapper with consistent styling.
 */
export function BaseDialog({
  theme,
  title,
  children,
  footer,
  width = 50,
}: BaseDialogProps) {
  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor={theme.colors.borderFocus}
      paddingX={2}
      paddingY={1}
      width={width}
    >
      {/* Header */}
      <Box marginBottom={1} justifyContent="center">
        <Text bold color={theme.colors.primary}>
          {title}
        </Text>
      </Box>

      {/* Divider */}
      <Box marginBottom={1}>
        <Text color={theme.colors.border}>
          {'─'.repeat(width - 6)}
        </Text>
      </Box>

      {/* Content */}
      <Box flexDirection="column" marginBottom={1}>
        {children}
      </Box>

      {/* Footer */}
      {footer && (
        <>
          <Box marginTop={1}>
            <Text color={theme.colors.border}>
              {'─'.repeat(width - 6)}
            </Text>
          </Box>
          <Box marginTop={1} justifyContent="center">
            {footer}
          </Box>
        </>
      )}
    </Box>
  );
}

/**
 * Confirm dialog with Yes/No options.
 */
export interface ConfirmDialogProps {
  theme: Theme;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
}

export function ConfirmDialog({
  theme,
  title,
  message,
  confirmLabel = 'Yes',
  cancelLabel = 'No',
  onConfirm,
  onCancel,
  danger = false,
}: ConfirmDialogProps) {
  const [selected, setSelected] = React.useState<'confirm' | 'cancel'>('cancel');

  useInput((input, key) => {
    if (key.leftArrow || key.rightArrow || key.tab) {
      setSelected(s => s === 'confirm' ? 'cancel' : 'confirm');
    } else if (key.return) {
      if (selected === 'confirm') {
        onConfirm();
      } else {
        onCancel();
      }
    } else if (key.escape) {
      onCancel();
    } else if (input === 'y' || input === 'Y') {
      onConfirm();
    } else if (input === 'n' || input === 'N') {
      onCancel();
    }
  });

  return (
    <BaseDialog theme={theme} title={title}>
      <Text wrap="wrap">{message}</Text>

      <Box marginTop={2} justifyContent="center" gap={2}>
        <Box
          borderStyle={selected === 'confirm' ? 'single' : undefined}
          borderColor={danger ? theme.colors.error : theme.colors.primary}
          paddingX={2}
        >
          <Text
            color={selected === 'confirm'
              ? (danger ? theme.colors.error : theme.colors.primary)
              : theme.colors.textMuted
            }
            bold={selected === 'confirm'}
          >
            [{confirmLabel}]
          </Text>
        </Box>

        <Box
          borderStyle={selected === 'cancel' ? 'single' : undefined}
          borderColor={theme.colors.primary}
          paddingX={2}
        >
          <Text
            color={selected === 'cancel' ? theme.colors.primary : theme.colors.textMuted}
            bold={selected === 'cancel'}
          >
            [{cancelLabel}]
          </Text>
        </Box>
      </Box>

      <Box marginTop={2} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>Y</Text>/{cancelLabel[0]} or <Text color={theme.colors.accent}>Enter</Text> to select
        </Text>
      </Box>
    </BaseDialog>
  );
}

/**
 * Prompt dialog for text input.
 */
export interface PromptDialogProps {
  theme: Theme;
  title: string;
  message?: string;
  placeholder?: string;
  defaultValue?: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}

export function PromptDialog({
  theme,
  title,
  message,
  placeholder = 'Enter value...',
  defaultValue = '',
  onSubmit,
  onCancel,
}: PromptDialogProps) {
  const [value, setValue] = React.useState(defaultValue);

  useInput((input, key) => {
    if (key.return) {
      onSubmit(value);
    } else if (key.escape) {
      onCancel();
    } else if (key.backspace || key.delete) {
      setValue(v => v.slice(0, -1));
    } else if (input && !key.ctrl && !key.meta) {
      setValue(v => v + input);
    }
  });

  return (
    <BaseDialog theme={theme} title={title}>
      {message && (
        <Box marginBottom={1}>
          <Text wrap="wrap">{message}</Text>
        </Box>
      )}

      <Box
        borderStyle="single"
        borderColor={theme.colors.borderFocus}
        paddingX={1}
      >
        <Text color={theme.colors.primary}>{'>'} </Text>
        {value ? (
          <Text>{value}</Text>
        ) : (
          <Text color={theme.colors.textMuted}>{placeholder}</Text>
        )}
        <Text backgroundColor={theme.colors.primary} color={theme.colors.textInverse}>
          {' '}
        </Text>
      </Box>

      <Box marginTop={2} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>Enter</Text> to submit | <Text color={theme.colors.accent}>Esc</Text> to cancel
        </Text>
      </Box>
    </BaseDialog>
  );
}

/**
 * Select dialog for choosing from options.
 */
export interface SelectDialogProps {
  theme: Theme;
  title: string;
  message?: string;
  options: DialogOption[];
  defaultValue?: string;
  onSelect: (value: string) => void;
  onCancel: () => void;
}

export function SelectDialog({
  theme,
  title,
  message,
  options,
  defaultValue,
  onSelect,
  onCancel,
}: SelectDialogProps) {
  const defaultIndex = defaultValue
    ? options.findIndex(o => o.value === defaultValue)
    : 0;
  const [selectedIndex, setSelectedIndex] = React.useState(Math.max(0, defaultIndex));

  useInput((input, key) => {
    if (key.upArrow) {
      setSelectedIndex(i => Math.max(0, i - 1));
    } else if (key.downArrow) {
      setSelectedIndex(i => Math.min(options.length - 1, i + 1));
    } else if (key.return) {
      onSelect(options[selectedIndex].value);
    } else if (key.escape) {
      onCancel();
    } else {
      // Check for shortcut keys
      const option = options.find(o => o.shortcut?.toLowerCase() === input?.toLowerCase());
      if (option) {
        onSelect(option.value);
      }
    }
  });

  return (
    <BaseDialog theme={theme} title={title}>
      {message && (
        <Box marginBottom={1}>
          <Text wrap="wrap">{message}</Text>
        </Box>
      )}

      <Box flexDirection="column">
        {options.map((option, index) => {
          const isSelected = index === selectedIndex;
          return (
            <Box key={option.value} paddingX={1}>
              <Text color={isSelected ? theme.colors.primary : theme.colors.textMuted}>
                {isSelected ? '>' : ' '}{' '}
              </Text>
              <Text
                color={isSelected ? theme.colors.primary : theme.colors.text}
                bold={isSelected}
              >
                {option.label}
              </Text>
              {option.shortcut && (
                <Text color={theme.colors.accent}> [{option.shortcut}]</Text>
              )}
              {option.description && (
                <Text color={theme.colors.textMuted}> - {option.description}</Text>
              )}
            </Box>
          );
        })}
      </Box>

      <Box marginTop={2} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>↑↓</Text> navigate | <Text color={theme.colors.accent}>Enter</Text> select | <Text color={theme.colors.accent}>Esc</Text> cancel
        </Text>
      </Box>
    </BaseDialog>
  );
}

export default BaseDialog;
