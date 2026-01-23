/**
 * Model Dialog Component
 *
 * Dialog for selecting AI models.
 */

import React, { useState, useMemo } from 'react';
import { Box, Text, useInput } from 'ink';
import type { Theme } from '../theme/index.js';
import { BaseDialog } from './Dialog.js';

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  contextWindow: number;
  inputPrice: number;  // per 1M tokens
  outputPrice: number; // per 1M tokens
  capabilities?: string[];
  recommended?: boolean;
}

export interface ModelDialogProps {
  theme: Theme;
  models: ModelInfo[];
  currentModelId: string;
  onSelect: (modelId: string) => void;
  onClose: () => void;
}

// Default model list (can be overridden)
export const defaultModels: ModelInfo[] = [
  {
    id: 'claude-3-5-sonnet-20241022',
    name: 'Claude 3.5 Sonnet',
    provider: 'Anthropic',
    contextWindow: 200000,
    inputPrice: 3,
    outputPrice: 15,
    capabilities: ['coding', 'analysis', 'vision'],
    recommended: true,
  },
  {
    id: 'claude-3-opus-20240229',
    name: 'Claude 3 Opus',
    provider: 'Anthropic',
    contextWindow: 200000,
    inputPrice: 15,
    outputPrice: 75,
    capabilities: ['coding', 'analysis', 'vision', 'complex-reasoning'],
  },
  {
    id: 'claude-3-5-haiku-20241022',
    name: 'Claude 3.5 Haiku',
    provider: 'Anthropic',
    contextWindow: 200000,
    inputPrice: 1,
    outputPrice: 5,
    capabilities: ['coding', 'fast'],
  },
  {
    id: 'gpt-4-turbo',
    name: 'GPT-4 Turbo',
    provider: 'OpenAI',
    contextWindow: 128000,
    inputPrice: 10,
    outputPrice: 30,
    capabilities: ['coding', 'analysis', 'vision'],
  },
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'OpenAI',
    contextWindow: 128000,
    inputPrice: 5,
    outputPrice: 15,
    capabilities: ['coding', 'analysis', 'vision', 'fast'],
  },
  {
    id: 'gpt-4o-mini',
    name: 'GPT-4o Mini',
    provider: 'OpenAI',
    contextWindow: 128000,
    inputPrice: 0.15,
    outputPrice: 0.6,
    capabilities: ['coding', 'fast', 'cheap'],
  },
];

/**
 * Format context window size.
 */
function formatContext(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(0)}M`;
  return `${(tokens / 1000).toFixed(0)}k`;
}

/**
 * Format price per million tokens.
 */
function formatPrice(price: number): string {
  if (price < 1) return `$${price.toFixed(2)}`;
  return `$${price.toFixed(0)}`;
}

/**
 * Model selection dialog.
 */
export function ModelDialog({
  theme,
  models,
  currentModelId,
  onSelect,
  onClose,
}: ModelDialogProps) {
  const [selectedIndex, setSelectedIndex] = useState(
    Math.max(0, models.findIndex(m => m.id === currentModelId))
  );
  const [filterQuery, setFilterQuery] = useState('');

  // Filter models by query
  const filteredModels = useMemo(() => {
    if (!filterQuery) return models;
    const q = filterQuery.toLowerCase();
    return models.filter(m =>
      m.name.toLowerCase().includes(q) ||
      m.provider.toLowerCase().includes(q) ||
      m.id.toLowerCase().includes(q) ||
      m.capabilities?.some(c => c.toLowerCase().includes(q))
    );
  }, [models, filterQuery]);

  // Group models by provider
  const groupedModels = useMemo(() => {
    const groups = new Map<string, ModelInfo[]>();
    for (const model of filteredModels) {
      if (!groups.has(model.provider)) {
        groups.set(model.provider, []);
      }
      groups.get(model.provider)!.push(model);
    }
    return groups;
  }, [filteredModels]);

  const selectedModel = filteredModels[selectedIndex];

  useInput((input, key) => {
    if (key.upArrow) {
      setSelectedIndex(i => Math.max(0, i - 1));
    } else if (key.downArrow) {
      setSelectedIndex(i => Math.min(filteredModels.length - 1, i + 1));
    } else if (key.return) {
      if (selectedModel) {
        onSelect(selectedModel.id);
        onClose();
      }
    } else if (key.escape) {
      if (filterQuery) {
        setFilterQuery('');
        setSelectedIndex(0);
      } else {
        onClose();
      }
    } else if (key.backspace || key.delete) {
      setFilterQuery(q => q.slice(0, -1));
      setSelectedIndex(0);
    } else if (input && !key.ctrl && !key.meta) {
      setFilterQuery(q => q + input);
      setSelectedIndex(0);
    }
  });

  return (
    <BaseDialog theme={theme} title="Select Model" width={70}>
      {/* Search input */}
      <Box marginBottom={1}>
        <Text color={theme.colors.primary}>Filter: </Text>
        {filterQuery ? (
          <Text>{filterQuery}</Text>
        ) : (
          <Text color={theme.colors.textMuted}>Type to filter...</Text>
        )}
      </Box>

      {/* Model list */}
      <Box flexDirection="column" marginBottom={1}>
        {filteredModels.length === 0 ? (
          <Text color={theme.colors.textMuted}>No models match your filter</Text>
        ) : (
          Array.from(groupedModels.entries()).map(([provider, providerModels]) => (
            <Box key={provider} flexDirection="column" marginBottom={1}>
              {/* Provider header */}
              <Box marginBottom={1}>
                <Text color={theme.colors.textMuted} dimColor bold>
                  {provider}
                </Text>
              </Box>

              {/* Models in this provider */}
              {providerModels.map((model) => {
                const globalIndex = filteredModels.indexOf(model);
                const isSelected = globalIndex === selectedIndex;
                const isCurrent = model.id === currentModelId;

                return (
                  <Box key={model.id} flexDirection="column" marginLeft={2}>
                    <Box>
                      {/* Selection indicator */}
                      <Text color={isSelected ? theme.colors.primary : theme.colors.textMuted}>
                        {isSelected ? '>' : ' '}{' '}
                      </Text>

                      {/* Current indicator */}
                      <Text color={theme.colors.success}>
                        {isCurrent ? '*' : ' '}{' '}
                      </Text>

                      {/* Model name */}
                      <Text
                        color={isSelected ? theme.colors.primary : theme.colors.text}
                        bold={isSelected || isCurrent}
                      >
                        {model.name}
                      </Text>

                      {/* Recommended badge */}
                      {model.recommended && (
                        <Text color={theme.colors.accent}> [recommended]</Text>
                      )}
                    </Box>

                    {/* Model details (when selected) */}
                    {isSelected && (
                      <Box marginLeft={4} flexDirection="column">
                        <Text color={theme.colors.textMuted}>
                          Context: {formatContext(model.contextWindow)} |{' '}
                          In: {formatPrice(model.inputPrice)}/M |{' '}
                          Out: {formatPrice(model.outputPrice)}/M
                        </Text>
                        {model.capabilities && model.capabilities.length > 0 && (
                          <Box>
                            <Text color={theme.colors.textMuted}>Capabilities: </Text>
                            {model.capabilities.map((cap, i) => (
                              <React.Fragment key={cap}>
                                {i > 0 && <Text color={theme.colors.textMuted}>, </Text>}
                                <Text color={theme.colors.accent}>{cap}</Text>
                              </React.Fragment>
                            ))}
                          </Box>
                        )}
                      </Box>
                    )}
                  </Box>
                );
              })}
            </Box>
          ))
        )}
      </Box>

      {/* Footer */}
      <Box marginTop={1} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>↑↓</Text> navigate |{' '}
          <Text color={theme.colors.accent}>Enter</Text> select |{' '}
          <Text color={theme.colors.accent}>Esc</Text> {filterQuery ? 'clear filter' : 'close'}
        </Text>
      </Box>
    </BaseDialog>
  );
}

export default ModelDialog;
