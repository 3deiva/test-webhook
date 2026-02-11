from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from google import genai
from collections import defaultdict, deque
import base64, json
import re

app = Flask(__name__)
CORS(app)

# 🔑 Put your Gemini API key here
client = genai.Client(api_key="AIzaSyBwpNU2Oc0ahA23HCEFnw_hD7RZ4lASiGA")


@app.route('/')
def home():
    return render_template("index.html")


# ---------- Helper to Extract JSON from Response ----------
def extract_json(text):
    """Extract JSON from text that might contain markdown code blocks or extra text"""
    # Try to find JSON in markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    # Try to find JSON object directly
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))
    
    # If all else fails, try to parse the entire text
    return json.loads(text)


# ---------- Graph Helpers ----------
def build_graph(edges):
    graph = defaultdict(list)
    for src, dst in edges:
        graph[src].append(dst)
    return dict(graph)


def detect_cycle(graph):
    visited, stack = set(), set()

    def dfs(v):
        visited.add(v)
        stack.add(v)
        for n in graph.get(v, []):
            if n not in visited:
                if dfs(n):
                    return True
            elif n in stack:
                return True
        stack.remove(v)
        return False

    return any(dfs(n) for n in graph if n not in visited)


def bfs_flow(graph, start):
    q, seen, order = deque([start]), set(), []
    while q:
        n = q.popleft()
        if n not in seen:
            seen.add(n)
            order.append(n)
            q.extend(graph.get(n, []))
    return order


# ---------- Step 1: Extract Architecture from Diagram ----------
def extract_architecture(proposal, base64_img):
    prompt = f"""
Extract components and connections from this architecture diagram.

Return ONLY a valid JSON object with no markdown formatting, no code blocks, no explanations.
Just the raw JSON in this exact format:

{{
  "components": ["Component1", "Component2", "Component3"],
  "connections": [["Component1", "Component2"], ["Component2", "Component3"]],
  "layers": ["Layer1", "Layer2"]
}}

Proposal:
{proposal}
"""

    img_data = base64_img.split(",")[1]

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"text": prompt},
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": img_data
                }
            }
        ]
    )

    # Extract and parse JSON from response
    try:
        return extract_json(response.text)
    except Exception as e:
        print(f"Error parsing JSON from response: {response.text}")
        raise e


# ---------- Step 2: Evaluate Architecture ----------
def evaluate_architecture(proposal, arch_data, graph, algo_facts):
    prompt = f"""
You are a senior software architect.

Proposal:
{proposal}

Extracted Components:
{arch_data["components"]}

Connections:
{arch_data["connections"]}

Algorithm Facts:
{algo_facts}

Evaluate this architecture and return ONLY a valid JSON object with no markdown formatting, no code blocks, no explanations.
Just the raw JSON in this exact format:

{{
  "issues": ["Issue 1", "Issue 2"],
  "score": 85,
  "verdict": "APPROVED"
}}

The verdict must be one of: APPROVED, NEEDS REVISION, or REJECTED
The score must be a number between 0 and 100.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    # Extract and parse JSON from response
    try:
        return extract_json(response.text)
    except Exception as e:
        print(f"Error parsing JSON from response: {response.text}")
        raise e


# ---------- API ----------
@app.route('/evaluate', methods=['POST'])
def evaluate():
    try:
        data = request.json
        proposal = data.get("content")
        image = data.get("image")

        arch_data = extract_architecture(proposal, image)

        # Handle case where components might be empty
        if not arch_data.get("components"):
            return jsonify({
                "error": "No components found in architecture diagram"
            }), 400

        graph = build_graph(arch_data.get("connections", []))
        start = arch_data["components"][0]

        algo_facts = {
            "cycle_detected": detect_cycle(graph),
            "bfs_flow": bfs_flow(graph, start)
        }

        report = evaluate_architecture(proposal, arch_data, graph, algo_facts)

        return jsonify({
            "extracted_architecture": arch_data,
            "graph": graph,
            "algorithm_facts": algo_facts,
            "evaluation": report
        })
    
    except Exception as e:
        print(f"Error in evaluate endpoint: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(debug=True)