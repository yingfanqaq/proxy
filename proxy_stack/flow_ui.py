from __future__ import annotations

import html
import json
from typing import Any

from .flows import flow_summary, output_formats_for_port, output_ports


def render_flow_designer(config: Any) -> str:
    flows = config.flows
    flow_json = json.dumps(flows, ensure_ascii=False, indent=2)
    flow_json_attr = html.escape(json.dumps(flows, ensure_ascii=False))
    summaries = flow_summary(config)
    summary_rows = "".join(
        f"<tr><td>{html.escape(str(row['name']))}</td><td>{'enabled' if row['enabled'] else 'disabled'}</td>"
        f"<td>{html.escape(str(row['source']))}</td><td>{html.escape(', '.join(str(item.get('format')) + ':' + str(item.get('port')) for item in row['outputs']))}</td></tr>"
        for row in summaries
    )
    port_rows = "".join(
        f"<tr><td>{port}</td><td>{html.escape(', '.join(output_formats_for_port(config, port)))}</td><td><code>http://{html.escape(config.host)}:{port}</code></td></tr>"
        for port in output_ports(config)
    )
    return f"""
  <section>
    <h2>Flow Designer</h2>
    <form method="post" action="/save">
      <input type="hidden" name="form_kind" value="flows">
    <div class="flow-toolbar">
      <button type="button" onclick="peSelectFlow('codex_to_anthropic')">Codex -> LiteLLM -> Anthropic</button>
      <button type="button" onclick="peSelectFlow('gemini_to_anthropic')">Gemini -> LiteLLM -> Anthropic</button>
      <button type="button" onclick="peSelectFlow('claude_code_to_anthropic')">Claude Code -> LiteLLM -> Anthropic</button>
      <button type="button" onclick="peSelectFlow('claude_code_to_openai')">Claude Code -> LiteLLM -> OpenAI</button>
    </div>
    <div class="flow-canvas" id="flowCanvas" data-flows="{flow_json_attr}">
      <svg id="flowLines"></svg>
    </div>
    <table><tr><th>Flow</th><th>Status</th><th>Start</th><th>Outputs</th></tr>{summary_rows}</table>
    <table><tr><th>Output Port</th><th>Formats</th><th>Base URL</th></tr>{port_rows}</table>
    <label class="wide"><span>Flow JSON</span><textarea name="flows_json" id="flowsJson" spellcheck="false">{html.escape(flow_json)}</textarea></label>
    <button name="save_action" value="save">Save Flow</button>
    <button name="save_action" value="save_restart">Save Flow & Restart Services</button>
    </form>
  </section>
  <script>
    const peCanvas = document.getElementById('flowCanvas');
    const peLines = document.getElementById('flowLines');
    const peJson = document.getElementById('flowsJson');
    let peFlows = JSON.parse(peCanvas.dataset.flows || '[]');
    let peActiveFlow = peFlows[0]?.id || null;

    function peNodeLabel(flow, kind) {{
      if (kind === 'source') {{
        const source = flow.source || {{}};
        return source.kind === 'external' ? `External ${{source.format || 'api'}}` : `${{source.provider || 'source'}} source`;
      }}
      if (kind === 'middle') return 'LiteLLM';
      return (flow.outputs || []).map(o => `${{o.format || 'api'}}:${{o.port || ''}}`).join(', ') || 'output';
    }}

    function peRenderCanvas() {{
      peCanvas.querySelectorAll('.flow-node').forEach(node => node.remove());
      const flow = peFlows.find(item => item.id === peActiveFlow) || peFlows[0];
      if (!flow) return;
      peActiveFlow = flow.id;
      ['source', 'middle', 'output'].forEach(kind => {{
        const pos = (flow.layout && flow.layout[kind]) || {{x: kind === 'source' ? 60 : kind === 'middle' ? 330 : 600, y: 120}};
        const node = document.createElement('div');
        node.className = `flow-node ${{kind}}`;
        node.dataset.kind = kind;
        node.style.left = `${{pos.x}}px`;
        node.style.top = `${{pos.y}}px`;
        node.innerHTML = `<b>${{kind}}</b><span>${{peNodeLabel(flow, kind)}}</span>`;
        node.addEventListener('pointerdown', peStartDrag);
        peCanvas.appendChild(node);
      }});
      peDrawLines();
    }}

    function peDrawLines() {{
      const nodes = [...peCanvas.querySelectorAll('.flow-node')];
      const boxes = Object.fromEntries(nodes.map(node => [node.dataset.kind, node.getBoundingClientRect()]));
      const canvasBox = peCanvas.getBoundingClientRect();
      const point = box => [box.left - canvasBox.left + box.width / 2, box.top - canvasBox.top + box.height / 2];
      peLines.innerHTML = '';
      [['source', 'middle'], ['middle', 'output']].forEach(pair => {{
        if (!boxes[pair[0]] || !boxes[pair[1]]) return;
        const [x1, y1] = point(boxes[pair[0]]);
        const [x2, y2] = point(boxes[pair[1]]);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${{x1}} ${{y1}} C ${{x1 + 80}} ${{y1}}, ${{x2 - 80}} ${{y2}}, ${{x2}} ${{y2}}`);
        path.setAttribute('stroke', '#8aa2ff');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('fill', 'none');
        peLines.appendChild(path);
      }});
    }}

    function peStartDrag(event) {{
      const node = event.currentTarget;
      node.setPointerCapture(event.pointerId);
      const startX = event.clientX;
      const startY = event.clientY;
      const left = parseFloat(node.style.left);
      const top = parseFloat(node.style.top);
      const move = moveEvent => {{
        const x = Math.max(10, left + moveEvent.clientX - startX);
        const y = Math.max(10, top + moveEvent.clientY - startY);
        node.style.left = `${{x}}px`;
        node.style.top = `${{y}}px`;
        const flow = peFlows.find(item => item.id === peActiveFlow);
        flow.layout = flow.layout || {{}};
        flow.layout[node.dataset.kind] = {{x: Math.round(x), y: Math.round(y)}};
        peJson.value = JSON.stringify(peFlows, null, 2);
        peDrawLines();
      }};
      const up = () => {{
        node.removeEventListener('pointermove', move);
        node.removeEventListener('pointerup', up);
      }};
      node.addEventListener('pointermove', move);
      node.addEventListener('pointerup', up);
    }}

    function peSelectFlow(id) {{
      peActiveFlow = id;
      peRenderCanvas();
    }}

    peJson.addEventListener('change', () => {{
      try {{
        peFlows = JSON.parse(peJson.value);
        peRenderCanvas();
      }} catch (error) {{
        alert(`Invalid flow JSON: ${{error.message}}`);
      }}
    }});
    window.addEventListener('resize', peDrawLines);
    peRenderCanvas();
  </script>
"""
