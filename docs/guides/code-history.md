# Code History

Two tools for understanding how code has evolved over time: `code_evolution` traces the change history of a specific file or symbol, and `recent_changes` aggregates recent activity across the project to identify hot development areas.

Both tools work in local mode via `git` subprocess calls and in service mode via the Commit + CommitFileStat database tables.

## `code_evolution` --- File and Symbol History

Traces how a file (or a specific symbol within it) has evolved, showing commits with line-level change statistics. Useful for understanding why code looks the way it does and who changed it.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `path` | (required) | File path, relative to project root or absolute |
| `symbol` | `""` | Optional symbol name to filter commits |
| `since` | `""` | Date filter (e.g. `"2024-01-01"`, `"3 months ago"`) |
| `max_results` | `20` | Maximum number of commits to return |

### Examples

**Track all changes to a file:**

```
code_evolution(path="src/auth/middleware.py")
```

Output:

```
Change history for src/auth/middleware.py
(12 commits shown)

    1. a1b2c3d4  2026-03-15  Alice
       Add rate limiting to auth middleware
       +45 -12  src/auth/middleware.py

    2. e5f6g7h8  2026-03-10  Bob
       Fix token expiration edge case
       +8 -3  src/auth/middleware.py

    3. i9j0k1l2  2026-02-28  Alice
       Refactor middleware to use dependency injection
       +120 -85  src/auth/middleware.py

Summary: 12 commits by 3 author(s)
Authors: Alice, Bob, Charlie
```

**Track changes to a specific symbol:**

```
code_evolution(path="src/auth/middleware.py", symbol="verify_token")
```

Output:

```
Change history for src/auth/middleware.py (symbol: verify_token)
(3 commits shown)

    1. a1b2c3d4  2026-03-15  Alice
       Add rate limiting to auth middleware
       +45 -12  src/auth/middleware.py

    2. e5f6g7h8  2026-03-10  Bob
       Fix token expiration edge case
       +8 -3  src/auth/middleware.py

Summary: 3 commits by 2 author(s)
Authors: Alice, Bob
```

Symbol filtering works by matching the symbol name against commit subjects and changed file paths. This is a heuristic filter -- it will catch commits that mention the symbol name but may miss changes where the symbol was modified without being named in the commit message.

**Filter by date range:**

```
code_evolution(path="src/auth/middleware.py", since="2026-03-01")
```

### HTTP API

```bash
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/evolution?path=src/auth/middleware.py&symbol=verify_token&since=2026-03-01" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "path": "src/auth/middleware.py",
  "symbol": "verify_token",
  "since": "2026-03-01",
  "commits": [
    {
      "sha": "a1b2c3d4e5f6g7h8",
      "author": "Alice",
      "email": "alice@example.com",
      "date": "2026-03-15T14:30:00+00:00",
      "subject": "Add rate limiting to auth middleware",
      "files": [
        {"path": "src/auth/middleware.py", "added": 45, "removed": 12}
      ]
    }
  ],
  "total": 3
}
```

---

## `recent_changes` --- Activity Aggregation

Aggregates recent git activity to identify files with the most changes. Useful for finding active development areas, understanding project velocity, and spotting potential merge conflict hotspots.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `days` | `7` | Look back this many days |
| `path` | `""` | Optional path prefix to filter (e.g. `"src/api/"`) |
| `top_n` | `20` | Number of top files to show |

### Examples

**Last 7 days of activity (default):**

```
recent_changes()
```

Output:

```
Recent changes (last 7 day(s))
42 commits, 28 files modified, 5 contributor(s)

    #  Commits   Added  Removed  Last        File
  ---  -------  ------  -------  ----------  ----------------------------------------
    1       12    +450     -120  2026-03-20  src/swarm/orchestrator.py
    2        8    +230      -45  2026-03-19  src/agent/agent.py
    3        6    +180      -60  2026-03-20  src/tui/app.py
    4        5     +95      -30  2026-03-18  src/core/execution_loop.py
    5        4     +60      -15  2026-03-17  src/auth/middleware.py

Total churn: +2,340 -890 lines
Contributors: Alice, Bob, Charlie, Dave, Eve
```

**Scoped to a directory:**

```
recent_changes(days=30, path="src/api/", top_n=10)
```

Output:

```
Recent changes (last 30 day(s) under 'src/api/')
18 commits, 12 files modified, 3 contributor(s)

    #  Commits   Added  Removed  Last        File
  ---  -------  ------  -------  ----------  ----------------------------------------
    1        6    +120      -45  2026-03-20  src/api/routes/auth.py
    2        4     +80      -20  2026-03-18  src/api/app.py
    3        3     +60      -10  2026-03-15  src/api/middleware.py

Total churn: +890 -320 lines
Contributors: Alice, Bob, Charlie
```

### HTTP API

```bash
curl "http://localhost:8080/api/v2/projects/$PROJECT_ID/recent-changes?days=14&path=src/api/&top_n=10" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "days": 14,
  "path": "src/api/",
  "commit_count": 18,
  "total_files_changed": 12,
  "files": [
    {
      "path": "src/api/routes/auth.py",
      "commits": 6,
      "added": 120,
      "removed": 45,
      "last_date": "2026-03-20"
    }
  ]
}
```

---

## Use Cases

**Understanding unfamiliar code:**

```
# What has this file been through?
code_evolution(path="src/core/execution_loop.py", max_results=30)
```

**Finding who to ask about a component:**

```
# Who has been working on auth recently?
recent_changes(days=90, path="src/auth/")
```

**Pre-merge conflict assessment:**

```
# What files are currently hot? (high conflict risk)
recent_changes(days=3)
```

**Tracking a refactor:**

```
# How has a symbol evolved since the refactor started?
code_evolution(path="src/agent/agent.py", symbol="createProductionAgent", since="2026-02-01")
```
