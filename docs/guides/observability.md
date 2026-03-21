# Observability

The code-intel HTTP API includes a built-in metrics endpoint that tracks request latencies, search performance, and tool call statistics. Metrics are available in both JSON and Prometheus text exposition format, making it straightforward to integrate with existing monitoring infrastructure.

## Metrics Endpoint

```
GET /api/v1/metrics?format=json|prometheus
```

The metrics endpoint is **unauthenticated** by design --- it is intended for monitoring infrastructure (Prometheus, Grafana, Datadog, etc.) that may not have API credentials.

### JSON Format (default)

```bash
curl http://localhost:8080/api/v1/metrics
```

Response:

```json
{
  "requests": {
    "total": 1234,
    "by_category": {
      "search": {
        "count": 245,
        "avg_ms": 42.5,
        "p50": 35.0,
        "p95": 120.0,
        "p99": 250.0
      },
      "analysis": {
        "count": 180,
        "avg_ms": 28.3,
        "p50": 22.0,
        "p95": 85.0,
        "p99": 150.0
      },
      "graph": {
        "count": 95,
        "avg_ms": 15.2,
        "p50": 12.0,
        "p95": 45.0,
        "p99": 80.0
      },
      "health": {
        "count": 500,
        "avg_ms": 1.2,
        "p50": 1.0,
        "p95": 2.0,
        "p99": 5.0
      }
    },
    "by_status": {
      "200": 1180,
      "400": 30,
      "404": 15,
      "429": 5,
      "500": 4
    }
  },
  "search": {
    "total": 245,
    "cache_hits": 82,
    "cache_misses": 163,
    "cache_hit_rate": 0.3347,
    "latency": {
      "p50": 35.0,
      "p95": 120.0,
      "p99": 250.0
    },
    "avg_result_count": 8.3
  },
  "tools": {
    "semantic_search": {
      "count": 120,
      "success": 118,
      "failure": 2,
      "avg_ms": 48.5,
      "p50": 40.0,
      "p95": 130.0,
      "p99": 260.0
    },
    "impact_analysis": {
      "count": 45,
      "success": 45,
      "failure": 0,
      "avg_ms": 22.1,
      "p50": 18.0,
      "p95": 55.0,
      "p99": 90.0
    }
  }
}
```

### Prometheus Format

```bash
curl "http://localhost:8080/api/v1/metrics?format=prometheus"
```

Response:

```
# HELP code_intel_requests_total Total HTTP requests
# TYPE code_intel_requests_total counter
code_intel_requests_total 1234

code_intel_requests_by_category{category="search"} 245
code_intel_requests_by_category{category="analysis"} 180
code_intel_requests_by_category{category="graph"} 95
code_intel_requests_by_category{category="health"} 500

# HELP code_intel_request_duration_ms Request latency in milliseconds
# TYPE code_intel_request_duration_ms summary
code_intel_request_duration_ms{category="search",quantile="0.5"} 35.0
code_intel_request_duration_ms{category="search",quantile="0.95"} 120.0
code_intel_request_duration_ms{category="search",quantile="0.99"} 250.0
code_intel_request_duration_ms{category="analysis",quantile="0.5"} 22.0
code_intel_request_duration_ms{category="analysis",quantile="0.95"} 85.0
code_intel_request_duration_ms{category="analysis",quantile="0.99"} 150.0

code_intel_requests_by_status{status="200"} 1180
code_intel_requests_by_status{status="400"} 30
code_intel_requests_by_status{status="429"} 5

# HELP code_intel_search_total Total search queries
# TYPE code_intel_search_total counter
code_intel_search_total 245

code_intel_search_cache_hits 82
code_intel_search_cache_misses 163
code_intel_search_cache_hit_rate 0.3347

# HELP code_intel_search_duration_ms Search latency in milliseconds
# TYPE code_intel_search_duration_ms summary
code_intel_search_duration_ms{quantile="0.5"} 35.0
code_intel_search_duration_ms{quantile="0.95"} 120.0
code_intel_search_duration_ms{quantile="0.99"} 250.0

# HELP code_intel_tool_calls_total Tool invocations
# TYPE code_intel_tool_calls_total counter
code_intel_tool_calls{tool="semantic_search",status="success"} 118
code_intel_tool_calls{tool="semantic_search",status="failure"} 2
code_intel_tool_calls{tool="impact_analysis",status="success"} 45
```

## What's Tracked

The metrics collector uses an in-memory ring buffer (max 10,000 entries per category) and is fully thread-safe.

### Request Categories

Every HTTP request is categorized for latency tracking:

| Category | Matching paths |
|----------|---------------|
| `search` | `/search`, `/semantic`, `/symbols` |
| `analysis` | `/analysis`, `/impact`, `/hotspots`, `/cross-ref` |
| `graph` | `/graph`, `/dependencies`, `/deps` |
| `lsp` | `/lsp` |
| `learning` | `/learning` |
| `files` | `/files` |
| `projects` | `/projects`, `/repos` |
| `embeddings` | `/embeddings` |
| `auth` | `/auth`, `/register` |
| `notify` | `/notify` |
| `health` | `/health`, `/ready`, `/metrics` |
| `other` | Everything else |

### Search Metrics

For every search query, the collector tracks:

- Query latency (with p50/p95/p99 percentiles)
- Result count
- Cache hit/miss (with hit rate)

### Tool Call Metrics

For every MCP tool invocation, the collector tracks:

- Tool name
- Call duration (with p50/p95/p99 percentiles)
- Success/failure count

## Setting Up Monitoring

### Prometheus Scrape Config

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "code-intel"
    scrape_interval: 15s
    metrics_path: "/api/v1/metrics"
    params:
      format: ["prometheus"]
    static_configs:
      - targets: ["localhost:8080"]
```

### Grafana Dashboard

Key panels to set up:

1. **Request rate** --- `rate(code_intel_requests_total[5m])`
2. **Request latency (p95)** --- `code_intel_request_duration_ms{quantile="0.95"}` by category
3. **Error rate** --- `code_intel_requests_by_status{status=~"5.."}` / `code_intel_requests_total`
4. **Search cache hit rate** --- `code_intel_search_cache_hit_rate`
5. **Tool success rate** --- per-tool success vs failure counts

### Health Check Integration

Use the existing health and readiness endpoints for orchestration:

```bash
# Liveness probe
curl http://localhost:8080/health
# {"status": "ok"}

# Readiness probe (checks for registered projects)
curl http://localhost:8080/ready
# {"status": "ready", "projects": 3}
```

### Docker Health Check

```yaml
services:
  code-intel:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## Architecture Notes

- Metrics are stored **in-memory only** --- they reset on server restart. This is by design: the ring buffer has bounded memory usage and no persistence overhead.
- The `MetricsCollector` is a module-level singleton initialized at import time.
- Percentiles are computed on read (not pre-aggregated), so `/api/v1/metrics` performs a snapshot of the ring buffer each call.
- The ring buffer caps at 10,000 entries per category. Older entries are silently dropped when the buffer is full.
