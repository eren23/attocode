/**
 * AgentGraph - Main SVG canvas with hierarchical agent layout + animated packets.
 *
 * Layout: hierarchical top-down
 * - Root agent / orchestrator at top center
 * - Subagents in second row
 * - Workers in bottom rows (grouped)
 * - Judge/manager nodes offset to sides
 *
 * Animation: requestAnimationFrame-based packets flowing along edges.
 */

import { useMemo, useRef, useCallback, useEffect, useState } from 'react';
import type { AgentGraphData, AgentNode as AgentNodeType, DataFlow } from '../../lib/agent-graph-types';
import { FLOW_TYPE_STYLES } from '../../lib/agent-graph-types';
import { AgentNode, AGENT_NODE_WIDTH, AGENT_NODE_HEIGHT } from './AgentNode';
import { DataFlowEdge } from './DataFlowEdge';
import { DataPacket } from './DataPacket';
import { SvgFilters } from '../shared/SvgFilters';
import { useAnimationLoop } from '../../hooks/useAnimationLoop';

interface AgentGraphProps {
  data: AgentGraphData;
  selectedAgentId: string | null;
  onSelectAgent: (id: string | null) => void;
  /** Live mode: continuously receive new data flows to animate */
  liveFlows?: DataFlow[];
  /** Post-mortem mode: flows filtered by current time window */
  replayFlows?: DataFlow[];
  replayTime?: number;
}

// Layout constants
const H_GAP = 60;
const V_GAP = 50;
const PADDING = 40;

const PACKET_DURATION_MS = 1500;
const MAX_CONCURRENT_PACKETS = 10;
const TRAIL_LENGTH = 3;

interface NodePosition {
  id: string;
  x: number;
  y: number;
}

interface ActivePacket {
  id: string;
  flowId: string;
  sourceId: string;
  targetId: string;
  color: string;
  filterId: string;
  startTime: number;
  progress: number; // 0-1
  // Cached source/target centers for interpolation
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  // Trail positions
  trail: Array<{ x: number; y: number }>;
}

/** Map flow type color to glow filter ID */
function colorToFilterId(color: string): string {
  const map: Record<string, string> = {
    '#3b82f6': 'glow-blue',
    '#6b7280': 'glow-gray',
    '#22c55e': 'glow-green',
    '#f59e0b': 'glow-amber',
    '#10b981': 'glow-emerald',
    '#8b5cf6': 'glow-violet',
  };
  return map[color] || 'glow-blue';
}

/**
 * Compute hierarchical layout:
 * Row 0: root / orchestrator
 * Row 1: managers / subagents
 * Row 2+: workers (with judge offset to the side)
 */
function computeLayout(agents: AgentNodeType[]): NodePosition[] {
  if (agents.length === 0) return [];

  // Categorize by type
  const roots: AgentNodeType[] = [];
  const orchestrators: AgentNodeType[] = [];
  const managers: AgentNodeType[] = [];
  const subagents: AgentNodeType[] = [];
  const workers: AgentNodeType[] = [];
  const judges: AgentNodeType[] = [];

  for (const agent of agents) {
    switch (agent.type) {
      case 'root': roots.push(agent); break;
      case 'orchestrator': orchestrators.push(agent); break;
      case 'manager': managers.push(agent); break;
      case 'subagent': subagents.push(agent); break;
      case 'worker': workers.push(agent); break;
      case 'judge': judges.push(agent); break;
    }
  }

  // Build rows
  const rows: AgentNodeType[][] = [];

  // Row 0: root + orchestrator
  const row0 = [...roots, ...orchestrators];
  if (row0.length > 0) rows.push(row0);

  // Row 1: managers + subagents
  const row1 = [...managers, ...subagents];
  if (row1.length > 0) rows.push(row1);

  // Row 2+: workers (chunk into rows of max 5)
  const workerChunkSize = 5;
  for (let i = 0; i < workers.length; i += workerChunkSize) {
    rows.push(workers.slice(i, i + workerChunkSize));
  }

  // Place judges in a separate column alongside the worker rows
  // If no worker rows, add judges as their own row
  if (judges.length > 0 && rows.length <= 2) {
    rows.push(judges);
  }

  // Calculate positions
  const positions: NodePosition[] = [];

  // Find the widest row for centering
  const maxRowWidth = Math.max(
    ...rows.map((row) => row.length * (AGENT_NODE_WIDTH + H_GAP) - H_GAP)
  );
  const canvasWidth = maxRowWidth + PADDING * 2;

  for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
    const row = rows[rowIdx];
    const rowWidth = row.length * (AGENT_NODE_WIDTH + H_GAP) - H_GAP;
    const startX = PADDING + (canvasWidth - PADDING * 2 - rowWidth) / 2;
    const y = PADDING + rowIdx * (AGENT_NODE_HEIGHT + V_GAP);

    for (let col = 0; col < row.length; col++) {
      const x = startX + col * (AGENT_NODE_WIDTH + H_GAP);
      positions.push({ id: row[col].id, x, y });
    }
  }

  // Place judges offset to the right side if they exist and were not placed
  const placedIds = new Set(positions.map((p) => p.id));
  for (const judge of judges) {
    if (!placedIds.has(judge.id)) {
      const lastRowY = positions.length > 0
        ? Math.max(...positions.map((p) => p.y))
        : PADDING;
      const rightX = canvasWidth - PADDING;
      positions.push({
        id: judge.id,
        x: rightX,
        y: lastRowY - AGENT_NODE_HEIGHT / 2,
      });
    }
  }

  return positions;
}

/**
 * Compute the position along a cubic bezier at parameter t.
 * Uses the same curve shape as DataFlowEdge.
 */
function bezierPoint(
  sx: number, sy: number,
  tx: number, ty: number,
  t: number
): { x: number; y: number } {
  const dy = ty - sy;
  const dx = tx - sx;

  let cx1: number, cy1: number, cx2: number, cy2: number;

  if (Math.abs(dy) > Math.abs(dx) * 0.3) {
    cx1 = sx;
    cy1 = sy + dy * 0.4;
    cx2 = tx;
    cy2 = sy + dy * 0.6;
  } else {
    cx1 = sx + dx * 0.3;
    cy1 = sy;
    cx2 = sx + dx * 0.7;
    cy2 = ty;
  }

  const u = 1 - t;
  const x = u * u * u * sx + 3 * u * u * t * cx1 + 3 * u * t * t * cx2 + t * t * t * tx;
  const y = u * u * u * sy + 3 * u * u * t * cy1 + 3 * u * t * t * cy2 + t * t * t * ty;
  return { x, y };
}

export function AgentGraph({
  data,
  selectedAgentId,
  onSelectAgent,
  liveFlows,
  replayFlows,
  replayTime,
}: AgentGraphProps) {
  const positions = useMemo(() => computeLayout(data.agents), [data.agents]);

  const positionMap = useMemo(() => {
    const map = new Map<string, NodePosition>();
    for (const pos of positions) {
      map.set(pos.id, pos);
    }
    return map;
  }, [positions]);

  const agentMap = useMemo(() => {
    const map = new Map<string, AgentNodeType>();
    for (const agent of data.agents) map.set(agent.id, agent);
    return map;
  }, [data.agents]);

  // Compute unique edges (deduplicate flow pairs)
  const edges = useMemo(() => {
    const edgeSet = new Map<string, { source: string; target: string; type: DataFlow['type'] }>();
    const allFlows = [...data.dataFlows, ...(replayFlows || [])];
    for (const flow of allFlows) {
      const key = `${flow.sourceAgentId}->${flow.targetAgentId}`;
      if (!edgeSet.has(key)) {
        edgeSet.set(key, {
          source: flow.sourceAgentId,
          target: flow.targetAgentId,
          type: flow.type,
        });
      }
    }
    return Array.from(edgeSet.values());
  }, [data.dataFlows, replayFlows]);

  // --- Animation state ---
  const packetsRef = useRef<Map<string, ActivePacket>>(new Map());
  const queueRef = useRef<DataFlow[]>([]);
  const processedFlowsRef = useRef<Set<string>>(new Set());
  const [renderTick, setRenderTick] = useState(0);
  const packetIdCounter = useRef(0);

  // Schedule a new packet animation for a data flow
  const schedulePacket = useCallback(
    (flow: DataFlow) => {
      if (processedFlowsRef.current.has(flow.id)) return;
      processedFlowsRef.current.add(flow.id);

      const sourcePos = positionMap.get(flow.sourceAgentId);
      const targetPos = positionMap.get(flow.targetAgentId);
      if (!sourcePos || !targetPos) return;

      const style = FLOW_TYPE_STYLES[flow.type];

      if (packetsRef.current.size >= MAX_CONCURRENT_PACKETS) {
        queueRef.current.push(flow);
        return;
      }

      const id = `pkt-${packetIdCounter.current++}`;
      const packet: ActivePacket = {
        id,
        flowId: flow.id,
        sourceId: flow.sourceAgentId,
        targetId: flow.targetAgentId,
        color: style.color,
        filterId: colorToFilterId(style.color),
        startTime: performance.now(),
        progress: 0,
        sx: sourcePos.x + AGENT_NODE_WIDTH / 2,
        sy: sourcePos.y + AGENT_NODE_HEIGHT,
        tx: targetPos.x + AGENT_NODE_WIDTH / 2,
        ty: targetPos.y,
        trail: [],
      };
      packetsRef.current.set(id, packet);
    },
    [positionMap]
  );

  // Process live flows as they arrive
  const prevLiveFlowsLenRef = useRef(0);
  useEffect(() => {
    if (!liveFlows) return;
    const newFlows = liveFlows.slice(prevLiveFlowsLenRef.current);
    prevLiveFlowsLenRef.current = liveFlows.length;
    for (const flow of newFlows) {
      schedulePacket(flow);
    }
  }, [liveFlows, schedulePacket]);

  // Process replay flows based on replay time
  useEffect(() => {
    if (!replayFlows || replayTime === undefined) return;
    for (const flow of replayFlows) {
      if (flow.timestamp <= replayTime) {
        schedulePacket(flow);
      }
    }
  }, [replayFlows, replayTime, schedulePacket]);

  // Animation loop
  const hasPackets = packetsRef.current.size > 0 || queueRef.current.length > 0;
  useAnimationLoop(
    (_deltaMs) => {
      const now = performance.now();
      let changed = false;
      const toRemove: string[] = [];

      for (const [id, packet] of packetsRef.current) {
        const elapsed = now - packet.startTime;
        const progress = Math.min(1, elapsed / PACKET_DURATION_MS);
        const prevProgress = packet.progress;
        packet.progress = progress;

        // Update trail
        if (prevProgress !== progress) {
          const current = bezierPoint(packet.sx, packet.sy, packet.tx, packet.ty, progress);
          packet.trail.push(current);
          if (packet.trail.length > TRAIL_LENGTH) {
            packet.trail.shift();
          }
          changed = true;
        }

        if (progress >= 1) {
          toRemove.push(id);
        }
      }

      // Remove completed packets
      for (const id of toRemove) {
        packetsRef.current.delete(id);
        changed = true;
      }

      // Dequeue waiting flows
      while (
        packetsRef.current.size < MAX_CONCURRENT_PACKETS &&
        queueRef.current.length > 0
      ) {
        const flow = queueRef.current.shift()!;
        // Re-process via schedulePacket logic (inline to avoid clearing from processed set)
        const sourcePos = positionMap.get(flow.sourceAgentId);
        const targetPos = positionMap.get(flow.targetAgentId);
        if (sourcePos && targetPos) {
          const style = FLOW_TYPE_STYLES[flow.type];
          const id = `pkt-${packetIdCounter.current++}`;
          packetsRef.current.set(id, {
            id,
            flowId: flow.id,
            sourceId: flow.sourceAgentId,
            targetId: flow.targetAgentId,
            color: style.color,
            filterId: colorToFilterId(style.color),
            startTime: performance.now(),
            progress: 0,
            sx: sourcePos.x + AGENT_NODE_WIDTH / 2,
            sy: sourcePos.y + AGENT_NODE_HEIGHT,
            tx: targetPos.x + AGENT_NODE_WIDTH / 2,
            ty: targetPos.y,
            trail: [],
          });
          changed = true;
        }
      }

      if (changed) {
        setRenderTick((t) => t + 1);
      }
    },
    hasPackets || (liveFlows !== undefined && liveFlows.length > 0)
  );

  // Compute canvas dimensions
  const maxX = positions.length > 0
    ? Math.max(...positions.map((p) => p.x)) + AGENT_NODE_WIDTH + PADDING
    : 400;
  const maxY = positions.length > 0
    ? Math.max(...positions.map((p) => p.y)) + AGENT_NODE_HEIGHT + PADDING
    : 300;

  // Compute active edge set (edges that have a packet traveling on them)
  const activeEdges = useMemo(() => {
    const set = new Set<string>();
    for (const [, packet] of packetsRef.current) {
      set.add(`${packet.sourceId}->${packet.targetId}`);
    }
    return set;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderTick]);

  // Build packet render data
  const packetRenderData = useMemo(() => {
    const result: Array<{
      id: string;
      x: number;
      y: number;
      color: string;
      filterId: string;
      opacity: number;
      trail: Array<{ x: number; y: number }>;
    }> = [];
    for (const [, packet] of packetsRef.current) {
      const pos = bezierPoint(packet.sx, packet.sy, packet.tx, packet.ty, packet.progress);
      // Fade in at start, fade out at end
      let opacity = 1;
      if (packet.progress < 0.1) opacity = packet.progress / 0.1;
      if (packet.progress > 0.85) opacity = (1 - packet.progress) / 0.15;
      result.push({
        id: packet.id,
        x: pos.x,
        y: pos.y,
        color: packet.color,
        filterId: packet.filterId,
        opacity: Math.max(0.1, opacity),
        trail: [...packet.trail],
      });
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderTick]);

  if (data.agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
        No agent data available
      </div>
    );
  }

  return (
    <div className="overflow-auto" style={{ maxWidth: '100%' }}>
      <div className="relative" style={{ width: maxX, height: maxY, minWidth: '100%' }}>
        {/* SVG layer for edges and packets */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width={maxX}
          height={maxY}
        >
          <SvgFilters />

          {/* Edges */}
          {edges.map((edge) => {
            const sourcePos = positionMap.get(edge.source);
            const targetPos = positionMap.get(edge.target);
            if (!sourcePos || !targetPos) return null;

            const edgeKey = `${edge.source}->${edge.target}`;
            const isActive = activeEdges.has(edgeKey);

            return (
              <DataFlowEdge
                key={edgeKey}
                pathId={`edge-${edgeKey}`}
                sourceX={sourcePos.x + AGENT_NODE_WIDTH / 2}
                sourceY={sourcePos.y + AGENT_NODE_HEIGHT}
                targetX={targetPos.x + AGENT_NODE_WIDTH / 2}
                targetY={targetPos.y}
                type={edge.type}
                active={isActive}
              />
            );
          })}

          {/* Animated packets */}
          {packetRenderData.map((pkt) => (
            <DataPacket
              key={pkt.id}
              x={pkt.x}
              y={pkt.y}
              color={pkt.color}
              size={4}
              opacity={pkt.opacity}
              trail={pkt.trail}
              filterId={pkt.filterId}
            />
          ))}
        </svg>

        {/* Agent nodes (absolute-positioned divs) */}
        {positions.map((pos) => {
          const agent = agentMap.get(pos.id);
          if (!agent) return null;
          return (
            <div
              key={pos.id}
              className="absolute"
              style={{ left: pos.x, top: pos.y }}
            >
              <AgentNode
                agent={agent}
                onClick={onSelectAgent}
                selected={selectedAgentId === pos.id}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
