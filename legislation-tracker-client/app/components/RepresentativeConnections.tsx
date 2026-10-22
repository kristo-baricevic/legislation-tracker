"use client";
import React, { useId, useState } from "react";
import styles from "./representative-research.module.css";

export type ConnectionNode = { id: string; kind: string; label: string; url: string };
export type ConnectionEdge = { id: string; kind: string; source: string; target: string; label: string; evidence_url: string; amount?: string };
const safeUrl = (url: string) => /^https:\/\//.test(url) || /^\/(?!\/)/.test(url) ? url : undefined;

export default function RepresentativeConnections({ nodes, edges }: { nodes: ConnectionNode[]; edges: ConnectionEdge[] }) {
  const [list, setList] = useState(false);
  const marker = useId().replaceAll(":", "");
  const kinds = ["contributor", "committee", "representative", "bill", "topic"].filter(kind => nodes.some(node => node.kind === kind));
  const groups = kinds.map(kind => nodes.filter(node => node.kind === kind));
  const height = Math.max(240, ...groups.map(group => group.length * 86 + 40));
  const width = Math.max(520, kinds.length * 240);
  const positions = new Map(nodes.map(node => {
    const column = kinds.indexOf(node.kind);
    const group = groups[column];
    return [node.id, { x: column * 240 + 12, y: (height - group.length * 86) / 2 + group.indexOf(node) * 86 }];
  }));
  const byId = new Map(nodes.map(node => [node.id, node]));
  return <section aria-label="Connections diagram">
    <div className={styles.controls}>
      <button type="button" aria-pressed={!list} onClick={() => setList(false)}>Connection map</button>
      <button type="button" aria-pressed={list} onClick={() => setList(true)}>Evidence list</button>
    </div>
    {list ? <ul className={styles.connections}>{edges.map(edge => <li key={edge.id}>
      <span>{byId.get(edge.source)?.label} → {byId.get(edge.target)?.label}</span>
      <a href={safeUrl(edge.evidence_url)}>{edge.label}</a>
      {edge.amount !== undefined && <span>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(edge.amount))} in observed contributions</span>}
    </li>)}</ul> : <div className={styles.graph}>
      <svg role="img" aria-label="Recorded connections map" viewBox={`0 0 ${width} ${height}`} style={{ minWidth: width, height }}>
        <defs><marker id={marker} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="currentColor" /></marker></defs>
        {edges.map(edge => {
          const source = positions.get(edge.source), target = positions.get(edge.target);
          if (!source || !target) return null;
          const x1 = source.x + 198, y1 = source.y + 32, x2 = target.x - 4, y2 = target.y + 32;
          return <a key={edge.id} href={safeUrl(edge.evidence_url)} aria-label={`${byId.get(edge.source)?.label}: ${edge.label}: ${byId.get(edge.target)?.label}`}>
            <title>{edge.label}</title><path d={`M${x1} ${y1} C${x1 + 20} ${y1}, ${x2 - 20} ${y2}, ${x2} ${y2}`} fill="none" stroke="currentColor" strokeWidth="1.5" markerEnd={`url(#${marker})`} />
          </a>;
        })}
        {nodes.map(node => {
          const position = positions.get(node.id)!;
          return <foreignObject key={node.id} x={position.x} y={position.y} width="198" height="72">
            <a className={styles.graphNode} href={safeUrl(node.url)} title={node.label}><small>{node.kind === "representative" ? "Member" : node.kind === "contributor" ? "Contributor" : node.kind === "committee" ? "Campaign committee" : node.kind === "bill" ? "Bill" : "Topic"}</small><span>{node.label}</span></a>
          </foreignObject>;
        })}
      </svg>
    </div>}
    {!edges.length && <p>No evidenced connections are stored for this selection.</p>}
  </section>;
}
