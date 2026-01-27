# Lesson 20: Sandboxing & Isolation

> Secure execution of untrusted code with resource limits and isolation

## What You'll Learn

1. **Isolation Levels**: From process to container to VM
2. **Resource Limits**: CPU, memory, time, and I/O restrictions
3. **Process Sandboxing**: OS-level isolation
4. **Container Sandboxing**: Docker-based isolation
5. **Output Limiting**: Preventing memory exhaustion

## Why This Matters

Agents executing code need protection against malicious or buggy code:

```
Without Sandboxing:
┌─────────────────────────────────────────────────────────┐
│  Agent: "Running user's code..."                        │
│  Code: while(true) { fork(); }  // Fork bomb            │
│  Result: 💥 System crash, all resources consumed        │
└─────────────────────────────────────────────────────────┘

With Sandboxing:
┌─────────────────────────────────────────────────────────┐
│  Agent: "Running user's code in sandbox..."             │
│  Code: while(true) { fork(); }                          │
│  Sandbox: Process limit reached (10), killed            │
│  Result: ✓ System safe, agent continues                 │
└─────────────────────────────────────────────────────────┘
```

## Key Concepts

### Isolation Levels

| Level | Security | Overhead | Use Case |
|-------|----------|----------|----------|
| none | ❌ | None | Trusted code only |
| process | ⚠️ | Low | Basic scripts |
| container | ✓ | Medium | Untrusted code |
| vm | ✓✓ | High | Maximum security |
| wasm | ✓✓ | Low | Browser/portable |

### Resource Limits

```typescript
interface ResourceLimits {
  maxCpuSeconds: number;    // CPU time limit
  maxMemoryMB: number;      // Memory limit
  maxDiskMB: number;        // Disk usage limit
  timeoutMs: number;        // Wall-clock timeout
  maxProcesses: number;     // Process/thread limit
  maxFileDescriptors: number;
  maxOutputBytes: number;   // Output size limit
}
```

### Security Options

```typescript
interface SecurityOptions {
  dropCapabilities: boolean;      // Remove Linux capabilities
  runAsNonRoot: boolean;          // Never run as root
  readOnlyRootFilesystem: boolean;
  noNewPrivileges: boolean;       // Prevent privilege escalation
  seccompProfile?: string;        // System call filtering
}
```

## Files in This Lesson

| File | Purpose |
|------|---------|
| `types.ts` | Sandbox configuration types |
| `resource-limits.ts` | Resource monitoring and enforcement |
| `process-sandbox.ts` | OS-level process isolation |
| `docker-sandbox.ts` | Container-based isolation |
| `main.ts` | Demonstration of all concepts |

## Running This Lesson

```bash
npm run lesson:20
```

## Code Examples

### Process Sandbox

```typescript
import { createProcessSandbox } from './process-sandbox.js';

const sandbox = createProcessSandbox({
  allowedReadPaths: ['/tmp', '/usr'],
  allowedWritePaths: ['/tmp'],
  workingDirectory: '/tmp',
  resourceLimits: {
    maxCpuSeconds: 10,
    maxMemoryMB: 128,
    timeoutMs: 30000,
    maxProcesses: 5,
    maxOutputBytes: 65536,
  },
});

// Execute a command
const result = await sandbox.execute({
  command: 'python3',
  args: ['script.py'],
  env: { PYTHONPATH: '/app' },
});

if (result.exitCode === 0) {
  console.log('Output:', result.stdout);
} else {
  console.error('Error:', result.stderr);
}

// Clean up
await sandbox.cleanup();
```

### Docker Sandbox

```typescript
import { createDockerSandbox } from './docker-sandbox.js';

const sandbox = createDockerSandbox({
  isolationLevel: 'container',
  allowNetwork: false,
  resourceLimits: {
    maxMemoryMB: 64,
    maxCpuSeconds: 5,
    timeoutMs: 10000,
  },
  security: {
    dropCapabilities: true,
    runAsNonRoot: true,
    readOnlyRootFilesystem: true,
    noNewPrivileges: true,
  },
});

const result = await sandbox.execute({
  command: 'npm',
  args: ['test'],
});
```

### Resource Monitoring

```typescript
import { ResourceMonitor } from './resource-limits.js';

const monitor = new ResourceMonitor(sandboxId, limits);

// Listen for limit warnings
monitor.on((event) => {
  if (event.type === 'limit.warning') {
    console.warn(`${event.limitType}: ${event.current}/${event.max}`);
  }
});

monitor.start();
// ... execution ...
monitor.stop();

const usage = monitor.getUsage();
console.log('CPU:', usage.cpuTimeMs, 'ms');
console.log('Memory:', usage.peakMemoryMB, 'MB');
```

### Output Limiting

```typescript
import { OutputLimiter } from './resource-limits.js';

const limiter = new OutputLimiter(65536); // 64KB max

process.stdout.on('data', (chunk) => {
  if (!limiter.append(chunk.toString())) {
    // Limit reached, kill process
    process.kill();
  }
});

const output = limiter.getOutput();
if (limiter.wasTruncated()) {
  console.warn('Output was truncated');
}
```

### Timeout Wrapper

```typescript
import { withTimeout, TimeoutError } from './resource-limits.js';

try {
  const result = await withTimeout(
    longRunningOperation(),
    30000, // 30 seconds
    () => {
      // Called when timeout triggers
      cleanupResources();
    }
  );
} catch (err) {
  if (err instanceof TimeoutError) {
    console.error('Operation timed out');
  }
}
```

## Default vs Strict Configuration

| Attribute | Default | Strict |
|-----------|---------|--------|
| Isolation | process | container |
| Network | No | No |
| Memory | 256MB | 64MB |
| CPU | 30s | 5s |
| Timeout | 60s | 10s |
| Processes | 10 | 1 |
| Read-only FS | No | Yes |

## Security Layers

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│  • Command validation                                    │
│  • Path restrictions                                     │
│  • Pattern blocking                                      │
├─────────────────────────────────────────────────────────┤
│                    Resource Layer                        │
│  • CPU limits (ulimit -t)                               │
│  • Memory limits (ulimit -v, cgroups)                   │
│  • Process limits (ulimit -u)                           │
│  • Output limits (byte counting)                        │
├─────────────────────────────────────────────────────────┤
│                    Isolation Layer                       │
│  • Process: fork, exec, signals                         │
│  • Container: namespaces, cgroups, seccomp              │
│  • VM: hardware virtualization                          │
├─────────────────────────────────────────────────────────┤
│                    Kernel Layer                          │
│  • Capabilities                                          │
│  • Seccomp filters                                       │
│  • SELinux/AppArmor                                     │
└─────────────────────────────────────────────────────────┘
```

## Best Practices

### 1. Start Strict, Loosen as Needed
```typescript
// Start with STRICT_SANDBOX_CONFIG
const sandbox = createProcessSandbox(STRICT_SANDBOX_CONFIG);

// Only add permissions when necessary
const config = mergeConfig(STRICT_SANDBOX_CONFIG, {
  allowedReadPaths: ['/data'], // Only what's needed
});
```

### 2. Always Set Timeouts
```typescript
// Never trust code to terminate on its own
resourceLimits: {
  timeoutMs: 30000, // Always set
  maxCpuSeconds: 10, // Backup CPU limit
}
```

### 3. Limit Output Size
```typescript
// Prevent memory exhaustion from verbose output
maxOutputBytes: 65536, // 64KB is usually enough
```

### 4. Run as Non-Root
```typescript
security: {
  runAsNonRoot: true,
  userId: 65534, // nobody user
}
```

### 5. Minimize File Access
```typescript
// Only allow specific paths, not broad patterns
allowedReadPaths: ['/app/data'], // Good
allowedReadPaths: ['/'],         // Bad!
```

## Common Attacks and Mitigations

| Attack | Mitigation |
|--------|------------|
| Fork bomb | Process limit |
| Memory exhaustion | Memory limit |
| CPU hogging | CPU time limit |
| Disk fill | Disk quota |
| Output flood | Output limit |
| Network abuse | Network isolation |
| File system damage | Read-only FS, path restrictions |
| Privilege escalation | Drop capabilities, noNewPrivileges |

## Resource Estimation

```typescript
import { ResourceEstimator } from './resource-limits.js';

// Get recommended limits for commands
const limits = ResourceEstimator.getRecommendedLimits('cargo build');
// Returns: { maxMemoryMB: 1024, maxCpuSeconds: 60, ... }

const simple = ResourceEstimator.getRecommendedLimits('ls -la');
// Returns: { maxMemoryMB: 64, maxCpuSeconds: 10, ... }
```

## Advanced: OS-Specific Sandboxes

The production agent implements native OS sandboxing for better security without container overhead.

### Seatbelt (macOS)

macOS provides `sandbox-exec` with Seatbelt profiles for unprivileged process sandboxing:

```typescript
// Generate Seatbelt profile
function generateSeatbeltProfile(options: SandboxOptions): string {
  const rules: string[] = [
    '(version 1)',
    '(deny default)', // Deny everything by default
  ];

  // Allow process basics
  rules.push('(allow process-fork)');
  rules.push('(allow process-exec)');
  rules.push('(allow signal (target self))');

  // Allow standard system paths
  const standardPaths = ['/bin', '/usr/bin', '/usr/lib', '/System'];
  for (const path of standardPaths) {
    rules.push(`(allow file-read* (subpath "${path}"))`);
  }

  // Add user-specified writable paths
  for (const path of options.writablePaths) {
    rules.push(`(allow file-read* (subpath "${path}"))`);
    rules.push(`(allow file-write* (subpath "${path}"))`);
  }

  // Network control
  if (options.networkAllowed) {
    rules.push('(allow network*)');
  } else {
    // Allow localhost only
    rules.push('(allow network-outbound (local ip "localhost:*"))');
  }

  return rules.join('\n');
}

// Execute sandboxed command
const profile = generateSeatbeltProfile(options);
const result = spawn('sandbox-exec', ['-p', profile, 'bash', '-c', command]);
```

### Landlock (Linux)

Linux kernel 5.13+ provides Landlock LSM for unprivileged file access control:

```typescript
class LandlockSandbox implements Sandbox {
  async execute(command: string): Promise<ExecResult> {
    // Check available isolation methods
    if (await this.isLandlockAvailable()) {
      return this.executeWithLandlock(command);
    }
    if (await commandExists('bwrap')) {
      return this.executeWithBubblewrap(command);
    }
    if (await commandExists('firejail')) {
      return this.executeWithFirejail(command);
    }
    // Fallback: ulimit only
    return this.executeWithUlimit(command);
  }

  private buildBubblewrapCommand(command: string, opts: SandboxOptions) {
    const args: string[] = [];

    // Create minimal root filesystem
    args.push('--ro-bind', '/usr', '/usr');
    args.push('--ro-bind', '/lib', '/lib');
    args.push('--ro-bind', '/bin', '/bin');
    args.push('--proc', '/proc');
    args.push('--dev', '/dev');
    args.push('--tmpfs', '/tmp');

    // Add writable paths
    for (const path of opts.writablePaths) {
      args.push('--bind', resolve(path), resolve(path));
    }

    // Network isolation
    if (!opts.networkAllowed) {
      args.push('--unshare-net');
    }

    args.push('--', 'bash', '-c', command);
    return { program: 'bwrap', args };
  }
}
```

### Sandbox Mode Selection

```typescript
type SandboxMode = 'seatbelt' | 'landlock' | 'docker' | 'basic';

async function selectSandbox(): Promise<Sandbox> {
  if (platform() === 'darwin') {
    // macOS: Use Seatbelt
    const sandbox = new SeatbeltSandbox(options);
    if (await sandbox.isAvailable()) return sandbox;
  }

  if (platform() === 'linux') {
    // Linux: Try Landlock → bubblewrap → firejail → ulimit
    const sandbox = new LandlockSandbox(options);
    if (await sandbox.isAvailable()) return sandbox;
  }

  // Fallback: Docker if available
  const docker = new DockerSandbox(options);
  if (await docker.isAvailable()) return docker;

  // Last resort: Basic process sandbox
  return new BasicSandbox(options);
}
```

### Predefined Profiles

```typescript
// Strict: Pure computation, minimal access
const STRICT_PROFILE: SandboxOptions = {
  writablePaths: [],
  readablePaths: ['/usr/lib', '/System'],
  networkAllowed: false,
  timeout: 30000,
  maxMemoryMB: 256,
};

// Development: npm/node/git operations
const DEV_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'node_modules', '.git'],
  readablePaths: ['/'],
  networkAllowed: true,  // Allow npm install
  timeout: 300000,       // 5 minutes
  maxMemoryMB: 1024,
};

// Build: Compilation, no network
const BUILD_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'dist', 'build'],
  readablePaths: ['/'],
  networkAllowed: false,
  timeout: 300000,
  maxMemoryMB: 2048,
};

// Test: Test execution with coverage
const TEST_PROFILE: SandboxOptions = {
  writablePaths: ['.', 'coverage', 'test-results'],
  readablePaths: ['/'],
  networkAllowed: false,
  timeout: 600000, // 10 minutes
  maxMemoryMB: 1024,
};
```

## Advanced: Persistent PTY Shell

For interactive development workflows, a persistent shell maintains state between commands:

### Why Persistent Shell?

```
Without persistence:
┌─────────────────────────────────────────────────────────────────┐
│  $ cd /project && npm install  → works                          │
│  $ npm test                    → "npm not found" (new shell!)  │
│  (Environment variables, working directory lost between calls) │
└─────────────────────────────────────────────────────────────────┘

With persistence:
┌─────────────────────────────────────────────────────────────────┐
│  $ cd /project && npm install  → works                          │
│  $ npm test                    → works (same shell session)    │
│  (Shell maintains state across multiple tool calls)            │
└─────────────────────────────────────────────────────────────────┘
```

### PTY Shell Manager

```typescript
class PTYShellManager {
  private process: ChildProcess | null = null;
  private outputBuffer: string = '';
  private commandHistory: string[] = [];
  private currentCwd: string;
  private endMarker = '__CMD_DONE__';

  async start(): Promise<void> {
    const shell = process.env.SHELL || '/bin/bash';

    this.process = spawn(shell, [], {
      cwd: this.config.cwd,
      env: { ...process.env, PS1: '$ ' },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Handle output
    this.process.stdout?.on('data', (data) => {
      this.handleOutput(data.toString());
    });
  }

  async execute(command: string): Promise<CommandResult> {
    if (!this.process) await this.start();

    this.commandHistory.push(command);
    this.outputBuffer = '';

    return new Promise((resolve) => {
      // Set timeout
      const timeout = setTimeout(() => {
        resolve({
          output: this.outputBuffer,
          exitCode: null,
          timedOut: true,
        });
      }, this.config.timeout);

      // Write command with completion marker
      const fullCommand = `${command}\necho "${this.endMarker} $?"\n`;
      this.process!.stdin!.write(fullCommand);

      // Wait for completion marker in output
      this.commandResolve = (result) => {
        clearTimeout(timeout);
        resolve(result);
      };
    });
  }

  async cd(directory: string): Promise<CommandResult> {
    const result = await this.execute(`cd "${directory}" && pwd`);
    if (result.exitCode === 0) {
      this.currentCwd = result.output.trim();
    }
    return result;
  }

  async setEnv(key: string, value: string): Promise<void> {
    await this.execute(`export ${key}="${value}"`);
    this.currentEnv[key] = value;
  }

  getState(): ShellState {
    return {
      cwd: this.currentCwd,
      history: [...this.commandHistory],
      isRunning: this.process !== null,
      pid: this.process?.pid,
    };
  }
}
```

### Creating a PTY Shell Tool

```typescript
function createPTYShellTool(shell: PTYShellManager) {
  return {
    name: 'shell_exec',
    description: 'Execute command in persistent shell session. ' +
      'Maintains working directory and environment between calls.',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'Command to execute' },
      },
      required: ['command'],
    },
    dangerLevel: 'dangerous',
    async execute({ command }) {
      const result = await shell.execute(command);

      if (result.timedOut) {
        return `Command timed out. Partial output:\n${result.output}`;
      }

      const exitInfo = result.exitCode !== 0
        ? ` (exit code: ${result.exitCode})`
        : '';
      return `${result.output}${exitInfo}`;
    },
  };
}

// Usage
const shell = await createAndStartPTYShell({ cwd: process.cwd() });
const shellTool = createPTYShellTool(shell);
agent.registerTool(shellTool);
```

### Events

```typescript
type PTYEvent =
  | { type: 'shell.started'; pid: number; shell: string }
  | { type: 'shell.stopped'; exitCode: number | null }
  | { type: 'command.start'; command: string }
  | { type: 'command.output'; data: string }
  | { type: 'command.complete'; result: CommandResult }
  | { type: 'command.timeout'; command: string };

shell.subscribe((event) => {
  if (event.type === 'command.timeout') {
    console.warn(`Command timed out: ${event.command}`);
  }
});
```

## Next Steps

In **Lesson 21: Human-in-the-Loop Patterns**, we'll learn:
- Approval workflows
- Escalation policies
- Audit logging
- Rollback capabilities
