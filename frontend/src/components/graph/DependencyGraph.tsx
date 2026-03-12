import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type {
  DependencyGraphNode,
  DependencyGraphEdge,
} from "@/api/generated/schema";

interface DependencyGraphProps {
  nodes: DependencyGraphNode[];
  edges: DependencyGraphEdge[];
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

export function DependencyGraph({ nodes, edges }: DependencyGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || !nodes.length) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    const simNodes: SimNode[] = nodes.map((n) => ({ ...n }));
    const simLinks: SimLink[] = edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }));

    const simulation = d3
      .forceSimulation(simNodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(80),
      )
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30));

    const g = svg.append("g");

    // Zoom
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        g.attr("transform", event.transform.toString());
      });
    svg.call(zoom);

    // Edges
    const link = g
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", "#3f3f46")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.6);

    // Nodes
    const node = g
      .selectAll<SVGGElement, SimNode>("g.node")
      .data(simNodes)
      .join("g")
      .attr("class", "node")
      .call(
        d3
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
          }),
      );

    node
      .append("circle")
      .attr("r", 6)
      .attr("fill", "#8b5cf6")
      .attr("stroke", "#a78bfa")
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .text((d) => d.label.split("/").pop() ?? d.label)
      .attr("x", 10)
      .attr("y", 4)
      .attr("fill", "#a1a1aa")
      .attr("font-size", "10px");

    // Tooltip
    node.append("title").text((d) => d.label);

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x!)
        .attr("y1", (d) => (d.source as SimNode).y!)
        .attr("x2", (d) => (d.target as SimNode).x!)
        .attr("y2", (d) => (d.target as SimNode).y!);

      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, edges]);

  return (
    <svg
      ref={svgRef}
      className="h-full w-full"
      style={{ minHeight: "400px" }}
    />
  );
}
