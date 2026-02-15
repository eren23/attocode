/**
 * CodeMapGraph - Force-directed graph visualization for code map
 *
 * Uses a simple custom force simulation (no external deps):
 * - Repulsion between all nodes (Coulomb-like)
 * - Attraction along edges (spring-like)
 * - Gravity toward center
 *
 * Runs ~100 iterations on mount to find stable positions.
 * Supports force layout and directory-based layout modes.
 */

import { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import type { CodeMapData, CodeMapFile } from '../../lib/codemap-types';
import { FileNode } from './FileNode';
import { DependencyEdge } from './DependencyEdge';
import type { LayoutMode } from './CodeMapControls';

interface CodeMapGraphProps {
  data: CodeMapData;
  selectedFile: string | null;
  onSelectFile: (filePath: string | null) => void;
  layoutMode: LayoutMode;
  zoom: number;
  typeFilters: Set<CodeMapFile['type']>;
  minImportance: number;
}

// --- Force simulation types ---

interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  file: CodeMapFile;
  width: number;
  height: number;
}

// --- Layout constants ---

const NODE_BASE_WIDTH = 70;
const NODE_HEIGHT = 36;
const PADDING = 40;

// --- Force simulation ---

function computeNodeSize(file: CodeMapFile): { width: number; height: number } {
  const scale = Math.log2(file.tokenCount + 1) * 8;
  const width = Math.max(NODE_BASE_WIDTH, Math.min(120, NODE_BASE_WIDTH + scale * 0.4));
  return { width, height: NODE_HEIGHT };
}

function initializeNodes(files: CodeMapFile[], canvasWidth: number, canvasHeight: number): SimNode[] {
  const cx = canvasWidth / 2;
  const cy = canvasHeight / 2;
  const radius = Math.min(canvasWidth, canvasHeight) * 0.35;

  return files.map((file, i) => {
    // Place nodes in a circle initially for a nice starting position
    const angle = (i / files.length) * Math.PI * 2;
    const r = radius * (0.3 + Math.random() * 0.7);
    const size = computeNodeSize(file);
    return {
      id: file.filePath,
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle) * r,
      vx: 0,
      vy: 0,
      file,
      ...size,
    };
  });
}

function runForceSimulation(
  nodes: SimNode[],
  edges: { source: string; target: string }[],
  canvasWidth: number,
  canvasHeight: number,
  iterations: number = 120
): SimNode[] {
  const cx = canvasWidth / 2;
  const cy = canvasHeight / 2;

  // Build adjacency for fast lookups
  const nodeMap = new Map<string, number>();
  for (let i = 0; i < nodes.length; i++) {
    nodeMap.set(nodes[i].id, i);
  }

  const edgeIndices = edges
    .map((e) => {
      const si = nodeMap.get(e.source);
      const ti = nodeMap.get(e.target);
      if (si !== undefined && ti !== undefined) return [si, ti] as [number, number];
      return null;
    })
    .filter((e): e is [number, number] => e !== null);

  // Simulation parameters
  const repulsionStrength = 2000;
  const attractionStrength = 0.008;
  const gravityStrength = 0.02;
  const dampening = 0.85;
  const minDistance = 30;

  for (let iter = 0; iter < iterations; iter++) {
    const temperature = 1 - iter / iterations; // Cool down over time

    // Repulsion between all pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x;
        const dy = nodes[j].y - nodes[i].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), minDistance);
        const force = (repulsionStrength * temperature) / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        nodes[i].vx -= fx;
        nodes[i].vy -= fy;
        nodes[j].vx += fx;
        nodes[j].vy += fy;
      }
    }

    // Attraction along edges
    for (const [si, ti] of edgeIndices) {
      const dx = nodes[ti].x - nodes[si].x;
      const dy = nodes[ti].y - nodes[si].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 1) continue;
      const idealDist = 150;
      const force = attractionStrength * (dist - idealDist) * temperature;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      nodes[si].vx += fx;
      nodes[si].vy += fy;
      nodes[ti].vx -= fx;
      nodes[ti].vy -= fy;
    }

    // Gravity toward center
    for (const node of nodes) {
      const dx = cx - node.x;
      const dy = cy - node.y;
      node.vx += dx * gravityStrength * temperature;
      node.vy += dy * gravityStrength * temperature;
    }

    // Apply velocities with dampening
    for (const node of nodes) {
      node.vx *= dampening;
      node.vy *= dampening;
      node.x += node.vx;
      node.y += node.vy;
    }
  }

  // Normalize positions to fit within canvas with padding
  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;
  for (const node of nodes) {
    minX = Math.min(minX, node.x);
    maxX = Math.max(maxX, node.x + node.width);
    minY = Math.min(minY, node.y);
    maxY = Math.max(maxY, node.y + node.height);
  }

  const graphWidth = maxX - minX;
  const graphHeight = maxY - minY;
  const availableWidth = canvasWidth - PADDING * 2;
  const availableHeight = canvasHeight - PADDING * 2;

  if (graphWidth > 0 && graphHeight > 0) {
    const scaleX = availableWidth / graphWidth;
    const scaleY = availableHeight / graphHeight;
    const scale = Math.min(scaleX, scaleY, 1); // Don't scale up beyond 1

    for (const node of nodes) {
      node.x = PADDING + (node.x - minX) * scale;
      node.y = PADDING + (node.y - minY) * scale;
    }
  }

  return nodes;
}

function computeDirectoryLayout(
  files: CodeMapFile[],
  canvasWidth: number,
  _canvasHeight: number
): SimNode[] {
  // Group files by directory
  const dirGroups = new Map<string, CodeMapFile[]>();
  for (const file of files) {
    const dir = file.directory || '.';
    if (!dirGroups.has(dir)) dirGroups.set(dir, []);
    dirGroups.get(dir)!.push(file);
  }

  // Sort directories
  const sortedDirs = [...dirGroups.keys()].sort();

  const nodes: SimNode[] = [];
  const DIR_HEADER = 24;
  const ROW_GAP = 6;
  const COL_GAP = 8;
  const DIR_GAP = 20;
  const maxColWidth = canvasWidth - PADDING * 2;

  let yOffset = PADDING;

  for (const dir of sortedDirs) {
    const dirFiles = dirGroups.get(dir)!;
    yOffset += DIR_HEADER;

    let xOffset = PADDING;
    let rowMaxHeight = 0;

    for (const file of dirFiles) {
      const size = computeNodeSize(file);

      // Wrap to next row if needed
      if (xOffset + size.width > maxColWidth + PADDING && xOffset > PADDING) {
        yOffset += rowMaxHeight + ROW_GAP;
        xOffset = PADDING;
        rowMaxHeight = 0;
      }

      nodes.push({
        id: file.filePath,
        x: xOffset,
        y: yOffset,
        vx: 0,
        vy: 0,
        file,
        ...size,
      });

      xOffset += size.width + COL_GAP;
      rowMaxHeight = Math.max(rowMaxHeight, size.height);
    }

    yOffset += rowMaxHeight + DIR_GAP;
  }

  return nodes;
}

// --- Component ---

export function CodeMapGraph({
  data,
  selectedFile,
  onSelectFile,
  layoutMode,
  zoom,
  typeFilters,
  minImportance,
}: CodeMapGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 900, height: 600 });
  const [hoveredFile, setHoveredFile] = useState<string | null>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  // Measure container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Filter files
  const visibleFiles = useMemo(() => {
    return data.files.filter((f) => {
      if (!typeFilters.has(f.type)) return false;
      if (f.importance < minImportance) return false;
      return true;
    });
  }, [data.files, typeFilters, minImportance]);

  // Filter edges to only include visible files
  const visibleEdges = useMemo(() => {
    const visibleSet = new Set(visibleFiles.map((f) => f.filePath));
    return data.dependencyEdges.filter(
      (e) => visibleSet.has(e.source) && visibleSet.has(e.target)
    );
  }, [data.dependencyEdges, visibleFiles]);

  // Build file type map for edge rendering
  const fileTypeMap = useMemo(() => {
    const map = new Map<string, CodeMapFile['type']>();
    for (const f of data.files) {
      map.set(f.filePath, f.type);
    }
    return map;
  }, [data.files]);

  // Compute layout
  const simNodes = useMemo(() => {
    if (visibleFiles.length === 0) return [];

    const canvasWidth = Math.max(containerSize.width, 600);
    const canvasHeight = Math.max(containerSize.height, 400);

    if (layoutMode === 'directory') {
      return computeDirectoryLayout(visibleFiles, canvasWidth, canvasHeight);
    }

    const nodes = initializeNodes(visibleFiles, canvasWidth, canvasHeight);
    return runForceSimulation(nodes, visibleEdges, canvasWidth, canvasHeight);
  }, [visibleFiles, visibleEdges, layoutMode, containerSize]);

  // Node position map for edge rendering
  const nodePositionMap = useMemo(() => {
    const map = new Map<string, SimNode>();
    for (const node of simNodes) {
      map.set(node.id, node);
    }
    return map;
  }, [simNodes]);

  // Connected files (for highlighting)
  const connectedFiles = useMemo(() => {
    const target = hoveredFile || selectedFile;
    if (!target) return new Set<string>();

    const connected = new Set<string>();
    connected.add(target);
    for (const edge of data.dependencyEdges) {
      if (edge.source === target) connected.add(edge.target);
      if (edge.target === target) connected.add(edge.source);
    }
    return connected;
  }, [hoveredFile, selectedFile, data.dependencyEdges]);

  // Connected edges (for highlighting)
  const connectedEdgeSet = useMemo(() => {
    const target = hoveredFile || selectedFile;
    if (!target) return new Set<string>();

    const set = new Set<string>();
    for (const edge of visibleEdges) {
      if (edge.source === target || edge.target === target) {
        set.add(`${edge.source}->${edge.target}`);
      }
    }
    return set;
  }, [hoveredFile, selectedFile, visibleEdges]);

  // Directory labels for directory layout
  const directoryLabels = useMemo(() => {
    if (layoutMode !== 'directory') return [];

    const dirs = new Map<string, { dir: string; y: number }>();
    for (const node of simNodes) {
      const dir = node.file.directory || '.';
      if (!dirs.has(dir)) {
        dirs.set(dir, { dir, y: node.y - 20 });
      } else {
        const existing = dirs.get(dir)!;
        existing.y = Math.min(existing.y, node.y - 20);
      }
    }
    return [...dirs.values()];
  }, [simNodes, layoutMode]);

  // Compute canvas bounds
  const canvasBounds = useMemo(() => {
    if (simNodes.length === 0) {
      return { width: containerSize.width, height: containerSize.height };
    }
    let maxX = 0;
    let maxY = 0;
    for (const node of simNodes) {
      maxX = Math.max(maxX, node.x + node.width + PADDING);
      maxY = Math.max(maxY, node.y + node.height + PADDING);
    }
    return {
      width: Math.max(maxX, containerSize.width),
      height: Math.max(maxY, containerSize.height),
    };
  }, [simNodes, containerSize]);

  // Pan handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      // Only allow panning on the background (not on nodes)
      if ((e.target as HTMLElement).closest('[data-file-node]')) return;
      isPanning.current = true;
      panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    },
    [pan]
  );

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning.current) return;
    const dx = e.clientX - panStart.current.x;
    const dy = e.clientY - panStart.current.y;
    setPan({ x: panStart.current.panX + dx, y: panStart.current.panY + dy });
  }, []);

  const handleMouseUp = useCallback(() => {
    isPanning.current = false;
  }, []);

  const handleFileClick = useCallback(
    (filePath: string) => {
      onSelectFile(selectedFile === filePath ? null : filePath);
    },
    [selectedFile, onSelectFile]
  );

  if (visibleFiles.length === 0) {
    return (
      <div
        ref={containerRef}
        className="bg-gray-900 border border-gray-800 rounded-lg flex items-center justify-center"
        style={{ height: '100%', minHeight: 400 }}
      >
        <div className="text-gray-500 text-sm">
          No files match the current filters
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden flex-1"
      style={{ height: '100%', minHeight: 400, cursor: isPanning.current ? 'grabbing' : 'grab' }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div
        className="relative"
        style={{
          width: canvasBounds.width,
          height: canvasBounds.height,
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          transformOrigin: '0 0',
        }}
      >
        {/* SVG layer for edges */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width={canvasBounds.width}
          height={canvasBounds.height}
          style={{ overflow: 'visible' }}
        >
          {visibleEdges.map((edge, i) => {
            const sourceNode = nodePositionMap.get(edge.source);
            const targetNode = nodePositionMap.get(edge.target);
            if (!sourceNode || !targetNode) return null;

            const x1 = sourceNode.x + sourceNode.width / 2;
            const y1 = sourceNode.y + sourceNode.height / 2;
            const x2 = targetNode.x + targetNode.width / 2;
            const y2 = targetNode.y + targetNode.height / 2;

            const edgeKey = `${edge.source}->${edge.target}`;
            const isHighlighted = connectedEdgeSet.has(edgeKey);
            const sourceType = fileTypeMap.get(edge.source);
            const targetType = fileTypeMap.get(edge.target);
            const isTestEdge =
              sourceType === 'test' && targetType !== 'test';

            return (
              <DependencyEdge
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                highlighted={isHighlighted}
                isTestEdge={isTestEdge}
                markerId={`arrow-${i}`}
              />
            );
          })}
        </svg>

        {/* Directory labels (only in directory layout) */}
        {directoryLabels.map((label) => (
          <div
            key={label.dir}
            className="absolute text-[10px] text-gray-600 font-mono truncate"
            style={{
              left: PADDING,
              top: label.y,
              maxWidth: canvasBounds.width - PADDING * 2,
            }}
          >
            {label.dir}/
          </div>
        ))}

        {/* File nodes */}
        {simNodes.map((node) => {
          const hasConnection = connectedFiles.size > 0;
          const isConnected = connectedFiles.has(node.id);
          const opacity = hasConnection
            ? isConnected
              ? 1
              : 0.25
            : Math.max(0.4, node.file.importance);

          return (
            <div
              key={node.id}
              data-file-node
              onMouseEnter={() => setHoveredFile(node.id)}
              onMouseLeave={() => setHoveredFile(null)}
            >
              <FileNode
                file={node.file}
                x={node.x}
                y={node.y}
                width={node.width}
                height={node.height}
                selected={selectedFile === node.id}
                highlighted={isConnected}
                opacity={opacity}
                onClick={handleFileClick}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
