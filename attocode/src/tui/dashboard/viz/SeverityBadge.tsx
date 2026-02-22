import { Text } from 'ink';
import React from 'react';

interface SeverityBadgeProps {
  severity: 'critical' | 'high' | 'medium' | 'low';
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'red',
  high: 'redBright',
  medium: 'yellow',
  low: 'blue',
};

export function SeverityBadge({ severity }: SeverityBadgeProps): React.ReactElement {
  return (
    <Text color={SEVERITY_COLORS[severity]} bold>
      [{severity.toUpperCase()}]
    </Text>
  );
}
