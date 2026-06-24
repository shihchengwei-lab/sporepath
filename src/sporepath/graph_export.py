from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .models import ThoughtAtom
from .store import MemoryStore


def graph_payload(store: MemoryStore, *, limit: int = 160) -> dict:
    atoms = sorted(
        store.list_atoms(),
        key=lambda atom: (atom.activation, atom.importance, atom.timestamp or ""),
        reverse=True,
    )[:limit]
    atom_ids = {atom.id for atom in atoms}
    edges = [
        edge
        for edge in store.list_edges()
        if edge.from_id in atom_ids and edge.to_id in atom_ids
    ]
    return {
        "nodes": [_node_payload(atom) for atom in atoms],
        "edges": [
            {
                "from": edge.from_id,
                "to": edge.to_id,
                "relation": edge.relation,
                "weight": edge.weight,
            }
            for edge in edges
        ],
        "stats": {
            "nodes": len(atoms),
            "edges": len(edges),
            "focus": sum(1 for atom in atoms if atom.activation >= 0.55),
            "latent": sum(1 for atom in atoms if atom.activation <= 0.35),
        },
    }


def export_graph_html(store: MemoryStore, out_path: str | Path, *, limit: int = 160) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = graph_payload(store, limit=limit)
    html = render_graph_html(payload, title="Sporepath Graph")
    out.write_text(html, encoding="utf-8")
    return out


def render_graph_html(payload: dict, *, title: str) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{
  --bg: #101418;
  --panel: #171d22;
  --panel-2: #20272d;
  --text: #e8edf0;
  --muted: #94a0a8;
  --line: #39444d;
  --focus: #63c7b2;
  --latent: #d6a55f;
  --idea: #78a9ff;
  --objection: #ff7b72;
  --decision: #a6e3a1;
  --question: #f5c2e7;
  --analogy: #f9e2af;
  --note: #cdd6f4;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif;
}}
.app {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  min-height: 100vh;
}}
.workspace {{
  position: relative;
  min-height: 100vh;
  border-right: 1px solid var(--line);
}}
header {{
  position: absolute;
  z-index: 3;
  top: 16px;
  left: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  pointer-events: none;
}}
.title {{
  pointer-events: auto;
  padding: 10px 12px;
  background: rgba(16, 20, 24, 0.78);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
}}
h1 {{
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: 0;
}}
.subtitle {{
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}}
.toolbar {{
  pointer-events: auto;
  display: flex;
  gap: 8px;
  padding: 8px;
  background: rgba(16, 20, 24, 0.78);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
}}
button {{
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel-2);
  color: var(--text);
  min-height: 34px;
  padding: 0 10px;
  font-size: 13px;
  cursor: pointer;
}}
button[aria-pressed="true"] {{
  border-color: var(--focus);
  color: var(--focus);
}}
canvas {{
  display: block;
  width: 100%;
  height: 100vh;
}}
aside {{
  min-width: 0;
  background: var(--panel);
  padding: 18px;
  overflow: auto;
}}
.stats {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}}
.metric {{
  background: var(--panel-2);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 10px;
}}
.metric strong {{
  display: block;
  font-size: 20px;
  line-height: 1.2;
}}
.metric span {{
  color: var(--muted);
  font-size: 12px;
}}
.legend {{
  display: grid;
  gap: 8px;
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 13px;
}}
.legend-row {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.swatch {{
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex: 0 0 auto;
}}
.details {{
  border-top: 1px solid var(--line);
  padding-top: 16px;
}}
.details h2 {{
  margin: 0 0 8px;
  font-size: 16px;
  letter-spacing: 0;
}}
.meta {{
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}}
.summary {{
  margin: 14px 0;
  line-height: 1.5;
}}
.text {{
  white-space: pre-wrap;
  color: #d9e2e7;
  background: #11161a;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.5;
  max-height: 36vh;
  overflow: auto;
}}
@media (max-width: 860px) {{
  .app {{ grid-template-columns: 1fr; }}
  .workspace {{ min-height: 68vh; border-right: 0; border-bottom: 1px solid var(--line); }}
  canvas {{ height: 68vh; }}
  header {{ position: static; padding: 12px; align-items: stretch; flex-direction: column; background: var(--bg); }}
  aside {{ max-height: none; }}
}}
</style>
</head>
<body>
<div class="app">
  <main class="workspace">
    <header>
      <div class="title">
        <h1>Sporepath Graph</h1>
        <div class="subtitle">Thick focus paths, faded latent paths, clickable thought atoms.</div>
      </div>
      <div class="toolbar" role="toolbar" aria-label="Graph view">
        <button id="viewAll" aria-pressed="true">All</button>
        <button id="viewFocus" aria-pressed="false">Focus</button>
        <button id="viewLatent" aria-pressed="false">Latent</button>
      </div>
    </header>
    <canvas id="graphCanvas" aria-label="Latent brain graph"></canvas>
  </main>
  <aside>
    <section class="stats" aria-label="Graph statistics">
      <div class="metric"><strong id="nodeCount">0</strong><span>nodes</span></div>
      <div class="metric"><strong id="edgeCount">0</strong><span>edges</span></div>
      <div class="metric"><strong id="focusCount">0</strong><span>focus</span></div>
      <div class="metric"><strong id="latentCount">0</strong><span>latent</span></div>
    </section>
    <section class="legend" aria-label="Legend">
      <div class="legend-row"><span class="swatch" style="background: var(--focus)"></span>Focus nodes: high activation</div>
      <div class="legend-row"><span class="swatch" style="background: var(--latent)"></span>Latent nodes: low activation</div>
      <div class="legend-row"><span class="swatch" style="background: var(--line)"></span>Line thickness: relation weight</div>
    </section>
    <section class="details" id="details">
      <h2>Select a node</h2>
      <div class="meta">Click any circle to inspect the original thought atom.</div>
    </section>
  </aside>
</div>
<script>
window.LATENT_BRAIN_GRAPH = {data_json};
</script>
<script>
const payload = window.LATENT_BRAIN_GRAPH;
const canvas = document.getElementById("graphCanvas");
const ctx = canvas.getContext("2d");
const details = document.getElementById("details");
const state = {{
  mode: "all",
  selected: null,
  dragging: null,
  pointer: {{ x: 0, y: 0 }},
}};
const colorByKind = {{
  idea: "#78a9ff",
  objection: "#ff7b72",
  decision: "#a6e3a1",
  question: "#f5c2e7",
  analogy: "#f9e2af",
  preference: "#63c7b2",
  note: "#cdd6f4",
}};
const nodes = payload.nodes.map((node, index) => ({{
  ...node,
  x: 120 + (index % 12) * 52,
  y: 120 + Math.floor(index / 12) * 44,
  vx: 0,
  vy: 0,
}}));
const nodeMap = new Map(nodes.map(node => [node.id, node]));
const edges = payload.edges
  .map(edge => ({{ ...edge, fromNode: nodeMap.get(edge.from), toNode: nodeMap.get(edge.to) }}))
  .filter(edge => edge.fromNode && edge.toNode);

document.getElementById("nodeCount").textContent = payload.stats.nodes;
document.getElementById("edgeCount").textContent = payload.stats.edges;
document.getElementById("focusCount").textContent = payload.stats.focus;
document.getElementById("latentCount").textContent = payload.stats.latent;

function resize() {{
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
}}

function visibleNode(node) {{
  if (state.mode === "focus") return node.state === "focus";
  if (state.mode === "latent") return node.state === "latent";
  return true;
}}

function nodeRadius(node) {{
  return 6 + node.activation * 10 + node.importance * 3;
}}

function nodeOpacity(node) {{
  if (!visibleNode(node)) return 0.08;
  if (node.state === "latent") return 0.58;
  return 0.92;
}}

function runLayout() {{
  const rect = canvas.getBoundingClientRect();
  const cx = rect.width / 2;
  const cy = rect.height / 2;
  for (const edge of edges) {{
    const a = edge.fromNode;
    const b = edge.toNode;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.max(1, Math.hypot(dx, dy));
    const target = 84 + (1 - edge.weight) * 120;
    const force = (dist - target) * 0.0025 * edge.weight;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    a.vx += fx; a.vy += fy;
    b.vx -= fx; b.vy -= fy;
  }}
  for (let i = 0; i < nodes.length; i++) {{
    const a = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {{
      const b = nodes[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(1, Math.hypot(dx, dy));
      const minDist = nodeRadius(a) + nodeRadius(b) + 18;
      if (dist < minDist) {{
        const force = (minDist - dist) * 0.006;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }}
    }}
  }}
  for (const node of nodes) {{
    if (node === state.dragging) continue;
    node.vx += (cx - node.x) * 0.0008;
    node.vy += (cy - node.y) * 0.0008;
    node.x += node.vx;
    node.y += node.vy;
    node.vx *= 0.84;
    node.vy *= 0.84;
    node.x = Math.max(24, Math.min(rect.width - 24, node.x));
    node.y = Math.max(72, Math.min(rect.height - 24, node.y));
  }}
}}

function draw() {{
  const rect = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  runLayout();
  for (const edge of edges) {{
    const visible = visibleNode(edge.fromNode) && visibleNode(edge.toNode);
    ctx.globalAlpha = visible ? 0.34 : 0.05;
    ctx.strokeStyle = "#76838c";
    ctx.lineWidth = 0.6 + edge.weight * 4;
    ctx.beginPath();
    ctx.moveTo(edge.fromNode.x, edge.fromNode.y);
    ctx.lineTo(edge.toNode.x, edge.toNode.y);
    ctx.stroke();
  }}
  for (const node of nodes) {{
    const radius = nodeRadius(node);
    const color = node.state === "latent" ? "#d6a55f" : (colorByKind[node.kind] || "#cdd6f4");
    ctx.globalAlpha = nodeOpacity(node);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
    ctx.fill();
    if (state.selected && state.selected.id === node.id) {{
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius + 4, 0, Math.PI * 2);
      ctx.stroke();
    }}
    if (visibleNode(node) && radius > 12) {{
      ctx.globalAlpha = 0.82;
      ctx.fillStyle = "#e8edf0";
      ctx.font = "12px Segoe UI, sans-serif";
      const label = node.summary.length > 26 ? node.summary.slice(0, 25) + "..." : node.summary;
      ctx.fillText(label, node.x + radius + 6, node.y + 4);
    }}
  }}
  ctx.globalAlpha = 1;
  requestAnimationFrame(draw);
}}

function pickNode(x, y) {{
  for (let i = nodes.length - 1; i >= 0; i--) {{
    const node = nodes[i];
    if (Math.hypot(node.x - x, node.y - y) <= nodeRadius(node) + 4) return node;
  }}
  return null;
}}

function showDetails(node) {{
  if (!node) return;
  state.selected = node;
  details.innerHTML = `
    <h2>${{escapeHtml(node.summary)}}</h2>
    <div class="meta">
      id: ${{escapeHtml(node.id)}}<br>
      source: ${{escapeHtml(node.source)}}<br>
      kind: ${{escapeHtml(node.kind)}}<br>
      state: ${{escapeHtml(node.state)}}<br>
      activation: ${{node.activation.toFixed(2)}} / importance: ${{node.importance.toFixed(2)}}<br>
      tags: ${{escapeHtml(node.tags.join(", "))}}
    </div>
    <div class="summary">${{escapeHtml(node.summary)}}</div>
    <div class="text">${{escapeHtml(node.text)}}</div>
  `;
}}

function escapeHtml(value) {{
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}}

canvas.addEventListener("pointerdown", event => {{
  const rect = canvas.getBoundingClientRect();
  const node = pickNode(event.clientX - rect.left, event.clientY - rect.top);
  if (node) {{
    state.dragging = node;
    state.selected = node;
    showDetails(node);
    canvas.setPointerCapture(event.pointerId);
  }}
}});
canvas.addEventListener("pointermove", event => {{
  const rect = canvas.getBoundingClientRect();
  state.pointer.x = event.clientX - rect.left;
  state.pointer.y = event.clientY - rect.top;
  if (state.dragging) {{
    state.dragging.x = state.pointer.x;
    state.dragging.y = state.pointer.y;
    state.dragging.vx = 0;
    state.dragging.vy = 0;
  }}
}});
canvas.addEventListener("pointerup", event => {{
  state.dragging = null;
  try {{ canvas.releasePointerCapture(event.pointerId); }} catch (_err) {{}}
}});

for (const [id, mode] of [["viewAll", "all"], ["viewFocus", "focus"], ["viewLatent", "latent"]]) {{
  document.getElementById(id).addEventListener("click", () => {{
    state.mode = mode;
    for (const button of document.querySelectorAll(".toolbar button")) {{
      button.setAttribute("aria-pressed", button.id === id ? "true" : "false");
    }}
  }});
}}

window.addEventListener("resize", resize);
resize();
if (nodes[0]) showDetails(nodes[0]);
draw();
</script>
</body>
</html>
"""


def _node_payload(atom: ThoughtAtom) -> dict:
    if atom.activation >= 0.55:
        state = "focus"
    elif atom.activation <= 0.35:
        state = "latent"
    else:
        state = "active"
    return {
        "id": atom.id,
        "source": atom.source,
        "role": atom.role,
        "text": atom.text,
        "summary": atom.summary,
        "kind": atom.kind,
        "tags": atom.tags,
        "timestamp": atom.timestamp,
        "importance": atom.importance,
        "activation": atom.activation,
        "state": state,
    }
