---
name: example-skill
description: A template for creating new skills
invokable: true
tools: [read_file, grep, glob]
tags: [example, template]
arguments:
  - name: target
    description: The target file or directory
    type: file
    required: true
  - name: focus
    description: Area to focus on
    type: string
    default: general
triggers:
  - example
  - demo
---

# Example Skill

This is a template for creating new skills. Skills provide specialized agent capabilities through prompt injection.

## Instructions

When this skill is active:

1. **Understand the Context**: Analyze what the user is trying to accomplish
2. **Apply Specialized Knowledge**: Use the expertise defined in this skill
3. **Provide Guidance**: Give specific, actionable advice

## Usage

```
/example-skill --target <file> [--focus security|perf|style]
```

## Guidelines

- Be thorough but concise
- Focus on the user's specific situation
- Provide examples when helpful
- Reference specific code locations when applicable

## Template Variables

You can use template variables in the skill content:
- `{{target}}` - The target argument value
- `{{focus}}` - The focus argument value (defaults to "general")
- `{{_cwd}}` - Current working directory
- `{{_sessionId}}` - Current session ID
