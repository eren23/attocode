---
name: code-review
description: Reviews code for bugs, security issues, and best practices
triggers:
  - review
  - check code
  - find bugs
---

# Code Review Skill

When reviewing code, follow these steps:

1. **Security Check**: Look for common vulnerabilities (injection, XSS, hardcoded secrets)
2. **Logic Errors**: Check for off-by-one errors, null handling, edge cases
3. **Best Practices**: Verify naming conventions, error handling, documentation
4. **Performance**: Identify inefficient loops, unnecessary allocations

Always provide:
- A severity rating (critical, warning, info)
- The specific line/location
- A suggested fix
