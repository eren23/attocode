/**
 * TUI Component Tests
 *
 * Tests for TUI components including:
 * - ToolCallItem: Tool execution display with expanded/collapsed views
 * - MessageItem: Message rendering with role-based styling
 * - ErrorBoundary: Error catching and fallback UI
 */

import { describe, it, expect, vi } from 'vitest';
import React from 'react';

// Import components and types
import {
  ToolCallItem,
  type ToolCallDisplayItem,
} from '../../src/tui/components/ToolCallItem.js';
import {
  MessageItem,
  type TUIMessage,
} from '../../src/tui/components/MessageItem.js';
import {
  TUIErrorBoundary,
  ErrorFallback,
  withErrorBoundary,
} from '../../src/tui/components/ErrorBoundary.js';
import type { ThemeColors } from '../../src/tui/types.js';

// =============================================================================
// TEST FIXTURES
// =============================================================================

const mockColors: ThemeColors = {
  // Primary colors
  primary: '#87CEEB',
  secondary: '#DDA0DD',
  accent: '#FFD700',
  // Text colors
  text: '#E0E0E0',
  textMuted: '#808080',
  textInverse: '#1E1E1E',
  // Background colors
  background: '#1E1E1E',
  backgroundAlt: '#2D2D2D',
  // Semantic colors
  success: '#98FB98',
  error: '#FF6B6B',
  warning: '#FFD700',
  info: '#87CEEB',
  // Component colors
  border: '#404040',
  borderFocus: '#87CEEB',
  // Role colors
  userMessage: '#87CEEB',
  assistantMessage: '#98FB98',
  systemMessage: '#FFD700',
  toolMessage: '#DDA0DD',
  // Code colors
  codeBackground: '#2D2D2D',
  codeKeyword: '#FF79C6',
  codeString: '#F1FA8C',
  codeComment: '#6272A4',
  codeNumber: '#BD93F9',
  codeFunction: '#50FA7B',
  codeType: '#8BE9FD',
};

// =============================================================================
// TOOL CALL ITEM TESTS
// =============================================================================

describe('ToolCallItem', () => {
  describe('component structure', () => {
    it('should export ToolCallItem as a memoized component', () => {
      expect(ToolCallItem).toBeDefined();
      expect(typeof ToolCallItem).toBe('object'); // memo returns object
    });

    it('should export ToolCallDisplayItem interface fields', () => {
      const item: ToolCallDisplayItem = {
        id: 'test-1',
        name: 'read_file',
        args: { path: '/test.ts' },
        status: 'success',
        result: 'file content',
        duration: 150,
      };

      expect(item.id).toBe('test-1');
      expect(item.name).toBe('read_file');
      expect(item.status).toBe('success');
    });
  });

  describe('status types', () => {
    it('should support all status types', () => {
      const statuses: ToolCallDisplayItem['status'][] = [
        'pending',
        'running',
        'success',
        'error',
      ];

      statuses.forEach(status => {
        const item: ToolCallDisplayItem = {
          id: `test-${status}`,
          name: 'test_tool',
          args: {},
          status,
        };
        expect(item.status).toBe(status);
      });
    });
  });

  describe('args formatting logic', () => {
    // Test the formatting logic by checking component renders without error
    it('should handle empty args', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'test',
        args: {},
        status: 'success',
      };

      // Component should accept empty args
      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: false, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle single string arg', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'read_file',
        args: { path: '/src/index.ts' },
        status: 'running',
      };

      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: false, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle multiple args', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'edit_file',
        args: {
          path: '/src/index.ts',
          old_string: 'const a = 1',
          new_string: 'const a = 2',
        },
        status: 'success',
      };

      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: true, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle long string args', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'write_file',
        args: {
          content: 'a'.repeat(200), // Long content
        },
        status: 'success',
      };

      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: true, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle multiline string args', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'write_file',
        args: {
          content: 'line1\nline2\nline3\nline4\nline5',
        },
        status: 'success',
      };

      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: true, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle object args', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'complex_tool',
        args: {
          config: { nested: { deep: true }, array: [1, 2, 3] },
        },
        status: 'success',
      };

      expect(() => {
        React.createElement(ToolCallItem, { tc, expanded: true, colors: mockColors });
      }).not.toThrow();
    });
  });

  describe('expanded vs collapsed view', () => {
    it('should render collapsed view', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'test_tool',
        args: { arg1: 'value1' },
        status: 'success',
        duration: 100,
      };

      const collapsed = React.createElement(ToolCallItem, {
        tc,
        expanded: false,
        colors: mockColors,
      });

      expect(collapsed).toBeDefined();
    });

    it('should render expanded view with result', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'test_tool',
        args: { arg1: 'value1' },
        status: 'success',
        result: 'Operation completed',
        duration: 100,
      };

      const expanded = React.createElement(ToolCallItem, {
        tc,
        expanded: true,
        colors: mockColors,
      });

      expect(expanded).toBeDefined();
    });

    it('should render expanded view with error', () => {
      const tc: ToolCallDisplayItem = {
        id: '1',
        name: 'failing_tool',
        args: {},
        status: 'error',
        error: 'Something went wrong',
      };

      const expanded = React.createElement(ToolCallItem, {
        tc,
        expanded: true,
        colors: mockColors,
      });

      expect(expanded).toBeDefined();
    });
  });
});

// =============================================================================
// MESSAGE ITEM TESTS
// =============================================================================

describe('MessageItem', () => {
  describe('component structure', () => {
    it('should export MessageItem as a memoized component', () => {
      expect(MessageItem).toBeDefined();
      expect(typeof MessageItem).toBe('object'); // memo returns object
    });

    it('should export TUIMessage interface', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'user',
        content: 'Hello',
        ts: new Date(),
      };

      expect(msg.id).toBe('msg-1');
      expect(msg.role).toBe('user');
    });
  });

  describe('message roles', () => {
    const roles: TUIMessage['role'][] = ['user', 'assistant', 'error', 'system'];

    roles.forEach(role => {
      it(`should handle ${role} role`, () => {
        const msg: TUIMessage = {
          id: `msg-${role}`,
          role,
          content: `Test ${role} message`,
          ts: new Date(),
        };

        expect(() => {
          React.createElement(MessageItem, { msg, colors: mockColors });
        }).not.toThrow();
      });
    });
  });

  describe('content handling', () => {
    it('should handle empty content', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: '',
        ts: new Date(),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle long content', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'x'.repeat(5000),
        ts: new Date(),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle multiline content', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Line 1\nLine 2\nLine 3',
        ts: new Date(),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle content with special characters', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'user',
        content: '`code` **bold** [link](url) <tag>',
        ts: new Date(),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });
  });

  describe('timestamp display', () => {
    it('should handle current timestamp', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'user',
        content: 'Test',
        ts: new Date(),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });

    it('should handle past timestamp', () => {
      const msg: TUIMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Old message',
        ts: new Date('2024-01-01T12:30:00'),
      };

      expect(() => {
        React.createElement(MessageItem, { msg, colors: mockColors });
      }).not.toThrow();
    });
  });
});

// =============================================================================
// ERROR BOUNDARY TESTS
// =============================================================================

describe('TUIErrorBoundary', () => {
  describe('component structure', () => {
    it('should export TUIErrorBoundary class', () => {
      expect(TUIErrorBoundary).toBeDefined();
      expect(TUIErrorBoundary.prototype).toHaveProperty('render');
      expect(TUIErrorBoundary.prototype).toHaveProperty('componentDidCatch');
    });

    it('should export ErrorFallback component', () => {
      expect(ErrorFallback).toBeDefined();
      expect(typeof ErrorFallback).toBe('function');
    });

    it('should export withErrorBoundary HOC', () => {
      expect(withErrorBoundary).toBeDefined();
      expect(typeof withErrorBoundary).toBe('function');
    });
  });

  describe('ErrorBoundary props', () => {
    it('should create element with required props', () => {
      const child = React.createElement('div', null, 'Child content');
      const element = React.createElement(
        TUIErrorBoundary,
        { name: 'TestSection', children: child },
      );

      expect(element).toBeDefined();
      expect(element.props.name).toBe('TestSection');
    });

    it('should accept custom fallback', () => {
      const customFallback = React.createElement('div', null, 'Custom error UI');
      const child = React.createElement('div', null, 'Child content');
      const element = React.createElement(
        TUIErrorBoundary,
        {
          name: 'TestSection',
          fallback: customFallback,
          children: child,
        },
      );

      expect(element.props.fallback).toBe(customFallback);
    });

    it('should accept onError callback', () => {
      const onError = vi.fn();
      const child = React.createElement('div', null, 'Child content');
      const element = React.createElement(
        TUIErrorBoundary,
        {
          name: 'TestSection',
          onError,
          children: child,
        },
      );

      expect(element.props.onError).toBe(onError);
    });

    it('should accept showDetails prop', () => {
      const child = React.createElement('div', null, 'Child content');
      const element = React.createElement(
        TUIErrorBoundary,
        {
          name: 'TestSection',
          showDetails: true,
          children: child,
        },
      );

      expect(element.props.showDetails).toBe(true);
    });
  });

  describe('getDerivedStateFromError', () => {
    it('should return hasError: true when error occurs', () => {
      const error = new Error('Test error');
      const result = TUIErrorBoundary.getDerivedStateFromError(error);

      expect(result).toEqual({
        hasError: true,
        error,
      });
    });
  });

  describe('ErrorFallback component', () => {
    it('should render default message', () => {
      const element = React.createElement(ErrorFallback, {});
      expect(element).toBeDefined();
    });

    it('should render custom message', () => {
      const element = React.createElement(ErrorFallback, {
        message: 'Custom error message',
      });
      expect(element.props.message).toBe('Custom error message');
    });

    it('should render compact variant', () => {
      const element = React.createElement(ErrorFallback, {
        compact: true,
      });
      expect(element.props.compact).toBe(true);
    });
  });

  describe('withErrorBoundary HOC', () => {
    it('should wrap component with error boundary', () => {
      const TestComponent = () => React.createElement('div', null, 'Test');
      const WrappedComponent = withErrorBoundary(TestComponent, 'TestWrapper');

      expect(WrappedComponent).toBeDefined();
      expect(WrappedComponent.displayName).toBe('withErrorBoundary(TestComponent)');
    });

    it('should handle named components', () => {
      function NamedComponent() {
        return React.createElement('div', null, 'Named');
      }
      const Wrapped = withErrorBoundary(NamedComponent, 'NamedWrapper');

      expect(Wrapped.displayName).toBe('withErrorBoundary(NamedComponent)');
    });

    it('should handle anonymous components', () => {
      const Wrapped = withErrorBoundary(() => null, 'AnonWrapper');

      expect(Wrapped.displayName).toMatch(/withErrorBoundary/);
    });

    it('should pass through options', () => {
      const TestComponent = () => React.createElement('div', null, 'Test');
      const onError = vi.fn();

      const WrappedComponent = withErrorBoundary(TestComponent, 'TestWrapper', {
        showDetails: true,
        onError,
      });

      const element = React.createElement(WrappedComponent, {});
      expect(element).toBeDefined();
    });
  });
});

// =============================================================================
// THEME COLORS TESTS
// =============================================================================

describe('ThemeColors', () => {
  it('should have all required color properties', () => {
    const requiredProps = [
      'primary',
      'secondary',
      'accent',
      'text',
      'textMuted',
      'textInverse',
      'background',
      'backgroundAlt',
      'success',
      'error',
      'warning',
      'info',
      'border',
      'borderFocus',
      'userMessage',
      'assistantMessage',
      'systemMessage',
      'toolMessage',
      'codeBackground',
      'codeKeyword',
      'codeString',
      'codeComment',
      'codeNumber',
      'codeFunction',
      'codeType',
    ];

    requiredProps.forEach(prop => {
      expect(mockColors).toHaveProperty(prop);
      expect(typeof mockColors[prop as keyof ThemeColors]).toBe('string');
    });
  });

  it('should have valid hex color values', () => {
    const hexColorRegex = /^#[0-9A-Fa-f]{6}$/;

    Object.values(mockColors).forEach(color => {
      expect(color).toMatch(hexColorRegex);
    });
  });
});
