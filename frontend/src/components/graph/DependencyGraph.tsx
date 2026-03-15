import { useRef, useEffect, useState } from "react";
import * as d3 from "d3";
import dagre from "dagre";
import type {
  DependencyGraphNode,
  DependencyGraphEdge,
} from "@/api/generated/schema";
import { GraphTooltip } from "./GraphTooltip";

interface DependencyGraphProps {
  nodes: DependencyGraphNode[];
  edges: DependencyGraphEdge[];
  layoutMode?: "force" | "dagre";
  direction?: "LR" | "TB";
  onNodeClick?: (nodeId: string) => void;
  onNodeSelect?: (node: DependencyGraphNode, position: { x: number; y: number }) => void;
  searchQuery?: string;
  selectedNodeId?: string;
  communityColorMap?: Record<string, string>;
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  color: string;
  radius: number;
  connectionCount: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

// Color by file extension
const EXT_COLORS: Record<string, string> = {
  py: "#3572A5",
  ts: "#3178c6",
  tsx: "#3178c6",
  js: "#f1e05a",
  jsx: "#f1e05a",
  go: "#00ADD8",
  rs: "#dea584",
  java: "#b07219",
  rb: "#701516",
  css: "#563d7c",
  html: "#e34c26",
  json: "#292929",
  yaml: "#cb171e",
  yml: "#cb171e",
  md: "#083fa1",
};

function getNodeColor(label: string): string {
  const ext = label.split(".").pop()?.toLowerCase() || "";
  return EXT_COLORS[ext] || "#6366f1";
}

function getFileName(label: string): string {
  const parts = label.split("/");
  return parts[parts.length - 1] || label;
}

function getNodeRadius(connectionCount: number): number {
  return Math.max(8, Math.min(22, 8 + Math.sqrt(connectionCount) * 3));
}

// Build legend entries from active extensions
function getLegendEntries(labels: string[]): { ext: string; color: string }[] {
  const seen = new Set<string>();
  const entries: { ext: string; color: string }[] = [];
  for (const label of labels) {
    const ext = label.split(".").pop()?.toLowerCase() || "";
    if (ext && EXT_COLORS[ext] && !seen.has(ext)) {
      seen.add(ext);
      entries.push({ ext: `.${ext}`, color: EXT_COLORS[ext] });
    }
  }
  // Add "other" if any node has no matching extension
  if (labels.some((l) => !EXT_COLORS[l.split(".").pop()?.toLowerCase() || ""])) {
    entries.push({ ext: "other", color: "#6366f1" });
  }
  return entries;
}

interface TooltipState {
  node: DependencyGraphNode;
  x: number;
  y: number;
  connectionCount: number;
  incomingCount: number;
  outgoingCount: number;
}

const MINIMAP_W = 120;
const MINIMAP_H = 80;

export function DependencyGraph({
  nodes,
  edges,
  layoutMode = "force",
  direction = "LR",
  onNodeClick,
  onNodeSelect,
  searchQuery,
  selectedNodeId,
  communityColorMap,
}: DependencyGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const minimapRef = useRef<SVGSVGElement>(null);
  const nodeSelRef = useRef<d3.Selection<SVGGElement, SimNode, SVGGElement, unknown> | null>(null);
  const linkSelRef = useRef<d3.Selection<SVGPathElement, SimLink, SVGGElement, unknown> | null>(null);
  const positionCacheRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  // Main render effect
  useEffect(() => {
    if (!svgRef.current || !nodes.length) return;

    const svgEl = svgRef.current;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    const positionCache = positionCacheRef.current;

    const width = svgEl.clientWidth;
    const height = svgEl.clientHeight;

    // Build adjacency info
    const incomingMap = new Map<string, number>();
    const outgoingMap = new Map<string, number>();
    const connectionMap = new Map<string, number>();
    const neighborMap = new Map<string, Set<string>>();

    for (const edge of edges) {
      outgoingMap.set(edge.source, (outgoingMap.get(edge.source) || 0) + 1);
      incomingMap.set(edge.target, (incomingMap.get(edge.target) || 0) + 1);
      connectionMap.set(edge.source, (connectionMap.get(edge.source) || 0) + 1);
      connectionMap.set(edge.target, (connectionMap.get(edge.target) || 0) + 1);
      if (!neighborMap.has(edge.source)) neighborMap.set(edge.source, new Set());
      if (!neighborMap.has(edge.target)) neighborMap.set(edge.target, new Set());
      neighborMap.get(edge.source)!.add(edge.target);
      neighborMap.get(edge.target)!.add(edge.source);
    }

    // Build SimNodes
    const simNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      color: communityColorMap?.[n.id] ?? getNodeColor(n.label),
      radius: getNodeRadius(connectionMap.get(n.id) || 0),
      connectionCount: connectionMap.get(n.id) || 0,
    }));

    const nodeIdSet = new Set(simNodes.map((n) => n.id));

    // Restore cached positions for nodes that still exist
    const hasCachedPositions = simNodes.some((n) => positionCache.has(n.id));
    if (hasCachedPositions) {
      // Clean up stale cache entries
      for (const key of positionCache.keys()) {
        if (!nodeIdSet.has(key)) positionCache.delete(key);
      }
      for (const n of simNodes) {
        const cached = positionCache.get(n.id);
        if (cached) {
          n.x = cached.x;
          n.y = cached.y;
        }
      }
    }

    // Build SimLinks (filter out edges referencing missing nodes)
    const simLinks: SimLink[] = edges
      .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, type: e.type }));

    // Unique colors for glow filters
    const uniqueColors = [...new Set(simNodes.map((n) => n.color))];

    // --- SVG defs ---
    const defs = svg.append("defs");

    // Glow filters per color
    for (const color of uniqueColors) {
      const hex = color.replace("#", "");
      const filter = defs
        .append("filter")
        .attr("id", `glow-${hex}`)
        .attr("x", "-50%")
        .attr("y", "-50%")
        .attr("width", "200%")
        .attr("height", "200%");

      filter
        .append("feGaussianBlur")
        .attr("stdDeviation", "4")
        .attr("result", "blur");
      filter
        .append("feFlood")
        .attr("flood-color", color)
        .attr("flood-opacity", "0.2")
        .attr("result", "color");
      filter
        .append("feComposite")
        .attr("in", "color")
        .attr("in2", "blur")
        .attr("operator", "in")
        .attr("result", "glow");
      const merge = filter.append("feMerge");
      merge.append("feMergeNode").attr("in", "glow");
      merge.append("feMergeNode").attr("in", "SourceGraphic");
    }

    // Arrow marker
    defs
      .append("marker")
      .attr("id", "arrowhead")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 10)
      .attr("refY", 5)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M 0 0 L 10 5 L 0 10 Z")
      .attr("fill", "#52525b");

    // --- Legend ---
    const legendEntries = getLegendEntries(nodes.map((n) => n.label));
    const legend = svg
      .append("g")
      .attr("class", "legend")
      .attr("transform", "translate(16, 16)");

    legend
      .append("rect")
      .attr("width", 80)
      .attr("height", legendEntries.length * 20 + 8)
      .attr("rx", 4)
      .attr("fill", "rgba(15, 15, 23, 0.85)")
      .attr("stroke", "#27272a")
      .attr("stroke-width", 1);

    legendEntries.forEach((entry, i) => {
      const row = legend.append("g").attr("transform", `translate(10, ${i * 20 + 14})`);
      row.append("circle").attr("r", 5).attr("fill", entry.color);
      row
        .append("text")
        .attr("x", 12)
        .attr("dy", "0.35em")
        .attr("fill", "#a1a1aa")
        .attr("font-size", "10px")
        .attr("font-family", "monospace")
        .text(entry.ext);
    });

    // Container group (zoom target)
    const container = svg.append("g");

    // --- Edges (curved paths) ---
    const linkGroup = container.append("g").attr("class", "links");
    const linkElements = linkGroup
      .selectAll<SVGPathElement, SimLink>("path")
      .data(simLinks)
      .enter()
      .append("path")
      .attr("stroke", "#52525b")
      .attr("stroke-opacity", 0.4)
      .attr("stroke-width", 1.5)
      .attr("fill", "none")
      .attr("marker-end", "url(#arrowhead)");

    linkSelRef.current = linkElements;

    // --- Nodes ---
    const nodeGroup = container.append("g").attr("class", "nodes");
    const nodeElements = nodeGroup
      .selectAll<SVGGElement, SimNode>("g")
      .data(simNodes)
      .enter()
      .append("g")
      .style("cursor", "pointer");

    nodeSelRef.current = nodeElements;

    // Circle -- short fade-in on first render, instant on subsequent
    const isFirstRender = !hasCachedPositions;
    const nodeCount = simNodes.length;
    // Cap total stagger to 800ms regardless of node count
    const staggerMs = nodeCount > 1 ? Math.min(15, 800 / nodeCount) : 0;

    nodeElements
      .append("circle")
      .attr("r", (d) => d.id === selectedNodeId ? d.radius * 1.2 : d.radius)
      .attr("fill", (d) => d.id === selectedNodeId ? `${d.color}44` : `${d.color}22`)
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", (d) => d.id === selectedNodeId ? 3 : 1.5)
      .attr("filter", (d) => `url(#glow-${d.color.replace("#", "")})`)
      .style("opacity", isFirstRender ? 0 : 1);

    if (isFirstRender) {
      nodeElements.select("circle")
        .transition()
        .duration(300)
        .delay((_d, i) => i * staggerMs)
        .style("opacity", 1);
    }

    // Label below circle
    nodeElements
      .append("text")
      .text((d) => getFileName(d.label))
      .attr("text-anchor", "middle")
      .attr("dy", (d) => d.radius + 14)
      .attr("fill", "#e4e4e7")
      .attr("font-size", "11px")
      .attr("font-family", "monospace")
      .attr("pointer-events", "none")
      .style("opacity", isFirstRender ? 0 : 1);

    if (isFirstRender) {
      nodeElements.select("text")
        .transition()
        .duration(300)
        .delay((_d, i) => i * staggerMs)
        .style("opacity", 1);
    }

    // --- Hover ---
    nodeElements
      .on("mouseenter", function (_event, d) {
        d3.select(this)
          .select("circle")
          .transition()
          .duration(200)
          .attr("r", d.radius * 1.3)
          .attr("fill", `${d.color}44`);

        const neighbors = neighborMap.get(d.id) || new Set<string>();
        nodeElements
          .transition()
          .duration(200)
          .style("opacity", (n) =>
            n.id === d.id || neighbors.has(n.id) ? 1 : 0.15,
          );
        linkElements
          .transition()
          .duration(200)
          .attr("stroke-opacity", (l) => {
            const src =
              typeof l.source === "object"
                ? (l.source as SimNode).id
                : l.source;
            const tgt =
              typeof l.target === "object"
                ? (l.target as SimNode).id
                : l.target;
            return src === d.id || tgt === d.id ? 0.8 : 0.05;
          });

        // Tooltip position in SVG coordinates
        const transform = d3.zoomTransform(svgEl);
        setTooltip({
          node: { id: d.id, label: d.label, type: d.type },
          x: d.x! * transform.k + transform.x,
          y: d.y! * transform.k + transform.y,
          connectionCount: d.connectionCount,
          incomingCount: incomingMap.get(d.id) || 0,
          outgoingCount: outgoingMap.get(d.id) || 0,
        });
      })
      .on("mouseleave", function (_event, d) {
        d3.select(this)
          .select("circle")
          .transition()
          .duration(200)
          .attr("r", d.radius)
          .attr("fill", `${d.color}22`);

        nodeElements.transition().duration(200).style("opacity", 1);
        linkElements
          .transition()
          .duration(200)
          .attr("stroke-opacity", 0.4);

        setTooltip(null);
      })
      .on("click", (_event, d) => {
        if (onNodeSelect) {
          const transform = d3.zoomTransform(svgEl);
          onNodeSelect(
            { id: d.id, label: d.label, type: d.type },
            {
              x: d.x! * transform.k + transform.x,
              y: d.y! * transform.k + transform.y,
            },
          );
        } else {
          onNodeClick?.(d.id);
        }
      });

    // --- Drag ---
    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeElements.call(drag);

    // --- Zoom ---
    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        container.attr("transform", event.transform.toString());
        renderMinimap(simNodes, event.transform, width, height);
      });

    svg.call(zoomBehavior);

    // --- Minimap helper ---
    const renderMinimap = (
      mNodes: SimNode[],
      transform: d3.ZoomTransform,
      svgW: number,
      svgH: number,
    ) => {
      if (!minimapRef.current) return;
      const mmSvg = d3.select(minimapRef.current);
      mmSvg.selectAll("*").remove();

      if (!mNodes.length || mNodes[0]?.x == null) return;

      const xs = mNodes.map((n) => n.x!);
      const ys = mNodes.map((n) => n.y!);
      const minX = Math.min(...xs) - 20;
      const maxX = Math.max(...xs) + 20;
      const minY = Math.min(...ys) - 20;
      const maxY = Math.max(...ys) + 20;
      const gw = maxX - minX;
      const gh = maxY - minY;

      const scale = Math.min(
        (MINIMAP_W - 8) / gw,
        (MINIMAP_H - 8) / gh,
      );

      // Background
      mmSvg
        .append("rect")
        .attr("width", MINIMAP_W)
        .attr("height", MINIMAP_H)
        .attr("rx", 4)
        .attr("fill", "#0f0f17")
        .attr("stroke", "#27272a")
        .attr("stroke-width", 1);

      const mg = mmSvg
        .append("g")
        .attr(
          "transform",
          `translate(${MINIMAP_W / 2 - (minX + gw / 2) * scale}, ${MINIMAP_H / 2 - (minY + gh / 2) * scale}) scale(${scale})`,
        );

      // Dots
      mg.selectAll("circle")
        .data(mNodes)
        .enter()
        .append("circle")
        .attr("cx", (d) => d.x!)
        .attr("cy", (d) => d.y!)
        .attr("r", 3 / scale)
        .attr("fill", (d) => d.color)
        .attr("opacity", 0.8);

      // Viewport rect
      const vx = -transform.x / transform.k;
      const vy = -transform.y / transform.k;
      const vw = svgW / transform.k;
      const vh = svgH / transform.k;

      mg.append("rect")
        .attr("x", vx)
        .attr("y", vy)
        .attr("width", vw)
        .attr("height", vh)
        .attr("stroke", "rgba(124, 140, 248, 0.6)")
        .attr("stroke-width", 2 / scale)
        .attr("fill", "rgba(124, 140, 248, 0.08)");
    };

    // --- Tick helper (curved edges with quadratic bezier) ---
    const tickPositions = () => {
      linkElements.attr("d", (d) => {
        const src = d.source as SimNode;
        const tgt = d.target as SimNode;
        const dx = tgt.x! - src.x!;
        const dy = tgt.y! - src.y!;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist === 0) return `M ${src.x},${src.y} L ${tgt.x},${tgt.y}`;
        // Shorten to node boundary
        const endX = tgt.x! - (dx / dist) * tgt.radius;
        const endY = tgt.y! - (dy / dist) * tgt.radius;
        // Slight curve offset perpendicular to the line
        const curvature = 0.15;
        const mx = (src.x! + endX) / 2 - dy * curvature;
        const my = (src.y! + endY) / 2 + dx * curvature;
        return `M ${src.x},${src.y} Q ${mx},${my} ${endX},${endY}`;
      });

      nodeElements.attr("transform", (d) => `translate(${d.x},${d.y})`);
    };

    // --- Simulation ---
    let simulation: d3.Simulation<SimNode, SimLink>;

    if (layoutMode === "force") {
      simulation = d3
        .forceSimulation(simNodes)
        .force(
          "link",
          d3
            .forceLink<SimNode, SimLink>(simLinks)
            .id((d) => d.id)
            .distance(120)
            .strength(0.7),
        )
        .force(
          "charge",
          d3.forceManyBody<SimNode>().strength(-500).distanceMax(600),
        )
        .force(
          "center",
          d3.forceCenter(width / 2, height / 2).strength(0.05),
        )
        .force(
          "collide",
          d3
            .forceCollide<SimNode>()
            .radius((d) => d.radius + 8)
            .strength(0.8),
        )
        .force("x", d3.forceX(width / 2).strength(0.02))
        .force("y", d3.forceY(height / 2).strength(0.02))
        .alphaDecay(0.028)
        .alphaMin(0.001)
        .velocityDecay(0.4);

      // Start with lower alpha if restoring from cache
      if (hasCachedPositions) {
        simulation.alpha(0.3);
      }

      simulation.on("tick", tickPositions);

      // Auto-fit once simulation settles
      simulation.on("end", () => {
        const xs = simNodes.map((n) => n.x!);
        const ys = simNodes.map((n) => n.y!);
        const pad = 40;
        const minX = Math.min(...xs) - pad;
        const maxX = Math.max(...xs) + pad;
        const minY = Math.min(...ys) - pad;
        const maxY = Math.max(...ys) + pad;
        const bw = maxX - minX;
        const bh = maxY - minY;
        const fitScale = Math.min(width / bw, height / bh, 1.5);
        const tx = width / 2 - (minX + bw / 2) * fitScale;
        const ty = height / 2 - (minY + bh / 2) * fitScale;

        const fitTransform = d3.zoomIdentity
          .translate(tx, ty)
          .scale(fitScale);
        svg
          .transition()
          .duration(750)
          .call(zoomBehavior.transform, fitTransform);
      });
    } else {
      // --- Dagre layout ---
      const g = new dagre.graphlib.Graph();
      g.setGraph({
        rankdir: direction,
        nodesep: 50,
        ranksep: 120,
        marginx: 40,
        marginy: 40,
      });
      g.setDefaultEdgeLabel(() => ({}));

      for (const n of simNodes) {
        g.setNode(n.id, {
          width: n.radius * 2 + 20,
          height: n.radius * 2 + 20,
        });
      }
      for (const e of edges) {
        if (nodeIdSet.has(e.source) && nodeIdSet.has(e.target)) {
          g.setEdge(e.source, e.target);
        }
      }
      dagre.layout(g);

      // Set fixed positions from dagre
      for (const n of simNodes) {
        const dn = g.node(n.id);
        if (dn) {
          n.x = dn.x;
          n.y = dn.y;
          n.fx = dn.x;
          n.fy = dn.y;
        }
      }

      // Minimal simulation just to resolve link node references
      simulation = d3
        .forceSimulation(simNodes)
        .force(
          "link",
          d3
            .forceLink<SimNode, SimLink>(simLinks)
            .id((d) => d.id),
        )
        .stop();
      simulation.tick();

      tickPositions();

      // Fit to view
      const graphWidth = (g.graph().width || width) + 80;
      const graphHeight = (g.graph().height || height) + 80;
      const scaleX = width / graphWidth;
      const scaleY = height / graphHeight;
      const fitScale = Math.min(scaleX, scaleY, 1);
      const tx = (width - graphWidth * fitScale) / 2;
      const ty = (height - graphHeight * fitScale) / 2;
      svg.call(
        zoomBehavior.transform,
        d3.zoomIdentity.translate(tx, ty).scale(fitScale),
      );

      renderMinimap(
        simNodes,
        d3.zoomTransform(svgEl),
        width,
        height,
      );
    }

    return () => {
      // Save positions to cache before cleanup
      for (const n of simNodes) {
        if (n.x != null && n.y != null) {
          positionCache.set(n.id, { x: n.x, y: n.y });
        }
      }
      simulation?.stop();
    };
  }, [nodes, edges, layoutMode, direction, onNodeClick, onNodeSelect, communityColorMap]);

  // Search highlighting (separate effect to avoid full rebuild)
  useEffect(() => {
    const nodeSel = nodeSelRef.current;
    const linkSel = linkSelRef.current;
    if (!nodeSel || !linkSel) return;

    if (!searchQuery) {
      nodeSel.interrupt().transition().duration(200).style("opacity", 1);
      nodeSel.each(function () {
        d3.select(this).select("circle").interrupt().attr("stroke-width", 1.5);
      });
      linkSel.interrupt().transition().duration(200).attr("stroke-opacity", 0.4);
      return;
    }

    const q = searchQuery.toLowerCase();

    nodeSel
      .transition()
      .duration(200)
      .style("opacity", (d) =>
        d.label.toLowerCase().includes(q) ? 1 : 0.15,
      );

    linkSel
      .transition()
      .duration(200)
      .attr("stroke-opacity", (l) => {
        const src =
          typeof l.source === "object"
            ? (l.source as SimNode).id
            : l.source;
        const tgt =
          typeof l.target === "object"
            ? (l.target as SimNode).id
            : l.target;
        const srcMatch = (
          nodeSelRef.current
            ?.data()
            .find((n) => n.id === src)
            ?.label.toLowerCase() || ""
        ).includes(q);
        const tgtMatch = (
          nodeSelRef.current
            ?.data()
            .find((n) => n.id === tgt)
            ?.label.toLowerCase() || ""
        ).includes(q);
        return srcMatch || tgtMatch ? 0.6 : 0.05;
      });

    // Pulse effect on matching nodes
    nodeSel.each(function (d) {
      const circle = d3.select(this).select("circle");
      if (d.label.toLowerCase().includes(q)) {
        const pulse = () => {
          circle
            .transition()
            .duration(600)
            .attr("stroke-width", 3)
            .transition()
            .duration(600)
            .attr("stroke-width", 1.5)
            .on("end", pulse);
        };
        pulse();
      } else {
        circle.interrupt().attr("stroke-width", 1.5);
      }
    });
  }, [searchQuery]);

  return (
    <div className="relative h-full w-full" style={{ minHeight: "400px" }}>
      <svg ref={svgRef} className="h-full w-full" />
      <GraphTooltip
        node={tooltip?.node ?? null}
        position={{ x: tooltip?.x ?? 0, y: tooltip?.y ?? 0 }}
        connectionCount={tooltip?.connectionCount ?? 0}
        incomingCount={tooltip?.incomingCount ?? 0}
        outgoingCount={tooltip?.outgoingCount ?? 0}
      />
      {/* Minimap */}
      <svg
        ref={minimapRef}
        width={MINIMAP_W}
        height={MINIMAP_H}
        className="absolute bottom-3 right-3 rounded"
        style={{ opacity: 0.9 }}
      />
    </div>
  );
}
