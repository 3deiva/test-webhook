"""
agents/repository_agent.py
───────────────────────────
AutoEval360 — Repository Agent

Responsibilities (6 tools in order):
──────────────────────────────────────────────────────────────────────
  Tool 1  Repository Registration Tool
  Tool 2  Webhook Commit Processor Tool
  Tool 3  Commit Evolution Analyzer Tool
  Tool 4  File Reconstruction Tool
  Tool 5  Code Structure & Dependency Graph Tool
          Writes → SharedMemory.repository_modules
          Writes → SharedMemory.dependency_graph
  Tool 6  Module Evaluation Tool
          Writes → SharedMemory.ast_features

Flask API endpoints (port 5001)
────────────────────────────────
  GET  /api/health
  GET  /api/repos
  GET  /api/events/<owner>/<repo_name>
  GET  /api/all-events
  GET  /api/evolution/<owner>/<repo_name>      ← Tool 3 data
  GET  /api/commit/<owner>/<repo_name>/<sha>
  GET  /api/modules                            ← Tool 5+6 combined
  GET  /api/dep-graph                          ← Tool 5 dependency graph
  POST /api/submit-repo   { repo_url, webhook_base_url? }
  POST /webhook           (GitHub push webhook)

SharedMemory fields written
────────────────────────────
  repo_registration_status    (dict)
  webhook_processing_result   (dict)
  evolution_report            (dict)
  file_reconstruction_result  (dict)
  code_structure_result       (dict)
  module_evaluation_result    (dict)
  repository_modules          (list)  ← Tool 5
  dependency_graph            (dict)  ← Tool 5
  ast_features                (dict)  ← Tool 6
"""

import json
import os
import re
import threading

from crewai import Agent, Crew, LLM, Task

os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"]        = "true"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = "groq/llama-3.3-70b-versatile"


class RepositoryAgent:

    def __init__(self, memory, api_key: str = ""):
        self.memory = memory
        key = api_key or GROQ_API_KEY

        from tools.repository_tools import (
            repository_registration_tool,
            webhook_commit_processor_tool,
            commit_evolution_analyzer_tool,
            file_reconstruction_tool,
            code_structure_dependency_graph_tool,
            module_evaluation_tool,
        )

        self.llm = LLM(model=GROQ_MODEL, api_key=key)
        self.agent = Agent(
            role="Repository Monitoring, Code Structure & Module Evaluation Agent",
            goal=(
                "Register the GitHub repository, process push webhooks, "
                "analyze commit evolution, reconstruct file history, "
                "walk every code file to build the actual dependency graph, "
                "and evaluate each module's implementation quality — so that "
                "ProgressAgent can compute accurate, real-data-based scores."
            ),
            backstory=(
                "You are part of AutoEval360, a multi-agent evaluation system that "
                "helps faculty monitor student software projects. You are the code "
                "archaeologist — you dig into every file, map what was actually built, "
                "measure how well each module is implemented, and produce the dependency "
                "graph + module metrics that ProgressAgent depends on to score the project."
            ),
            tools=[
                repository_registration_tool,
                webhook_commit_processor_tool,
                commit_evolution_analyzer_tool,
                file_reconstruction_tool,
                code_structure_dependency_graph_tool,
                module_evaluation_tool,
            ],
            llm=self.llm,
            verbose=True,
        )

    # ──────────────────────────────────────────────────────────
    # Task builder
    # ──────────────────────────────────────────────────────────

    def _build_task(self) -> Task:
        m = self.memory

        output_path = os.path.abspath(
            os.path.join("analysis_outputs", f"{m.repo_name or 'repo'}_analysis.json")
        )

        tool1_input = json.dumps({
            "repo_url":         m.repo_url,
            "webhook_base_url": m.webhook_base_url,
        })

        tool2_input = json.dumps({
            "owner":     m.repo_owner,
            "repo_name": m.repo_name,
            "commits":   m.pending_commits,
        })

        tool3_input = json.dumps({
            "owner":     m.repo_owner,
            "repo_name": m.repo_name,
        })

        tool4_input = json.dumps({
            "owner":      m.repo_owner,
            "repo_name":  m.repo_name,
            "commit_sha": m.target_commit_sha,
            "filename":   m.target_filename,
            "mode":       m.reconstruction_mode,
        })

        tool5_input = json.dumps({
            "repo_url":           m.repo_url,
            "expected_modules":   m.expected_modules,
            "architecture_graph": m.architecture_graph,
            "output_path":        output_path,
        })

        tool6_input_template = json.dumps({
            "repo_root":            "<repo_root from Tool 5 output>",
            "expected_modules":     m.expected_modules,
            "complexity_threshold": 4,
        })

        description = f"""
You are analysing a student GitHub repository for AutoEval360.

Repository : {m.repo_owner}/{m.repo_name}
URL        : {m.repo_url}
Expected modules: {m.expected_modules}

Run EACH tool below IN ORDER. Pass the input string EXACTLY as shown.
For Tool 6, replace <repo_root from Tool 5 output> with the actual
repo_root value returned in Tool 5's JSON response.

STEP 1 — Call tool: Repository Registration Tool
Input: {tool1_input}

STEP 2 — Call tool: Webhook Commit Processor Tool
Input: {tool2_input}

STEP 3 — Call tool: Commit Evolution Analyzer Tool
Input: {tool3_input}

STEP 4 — Call tool: File Reconstruction Tool
Input: {tool4_input}

STEP 5 — Call tool: Code Structure & Dependency Graph Tool
CRITICAL: This builds the real dependency graph for ProgressAgent.
Note the "repo_root" value from this response for use in Step 6.
Input: {tool5_input}

STEP 6 — Call tool: Module Evaluation Tool
CRITICAL: This evaluates each module's implementation quality.
Replace <repo_root from Tool 5 output> with the actual repo_root.
Input: {tool6_input_template}

FINAL STEP — Combine all results and return ONLY a valid JSON object
with EXACTLY these keys:
{{
  "repo_registration_status":   {{}},
  "webhook_processing_result":  {{}},
  "evolution_report":           {{}},
  "file_reconstruction_result": {{}},
  "code_structure_result":      {{}},
  "module_evaluation_result":   {{}}
}}
"""
        return Task(
            description=description,
            agent=self.agent,
            expected_output="A valid JSON object with all six repository evaluation fields.",
        )

    # ──────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────

    def run(self) -> dict:
        self.memory.log("RepositoryAgent", f"Starting with {GROQ_MODEL}...")
        parsed = None
        try:
            crew   = Crew(agents=[self.agent], tasks=[self._build_task()], verbose=True)
            result = crew.kickoff()
            parsed = self._parse_output(str(result))
        except Exception as e:
            self.memory.log("RepositoryAgent", f"LLM/Crew error — running fallback. Reason: {e}")
            parsed = self._fallback()

        if parsed is None:
            parsed = self._fallback()

        self._write_to_memory(parsed)
        csr = parsed.get("code_structure_result", {})
        mer = parsed.get("module_evaluation_result", {})
        self.memory.log(
            "RepositoryAgent",
            f"Done — "
            f"pattern={parsed.get('evolution_report', {}).get('development_pattern', {}).get('pattern', '?')} | "
            f"modules={csr.get('detected_modules', [])} | "
            f"dep_coverage={csr.get('dependency_coverage', 0):.1%} | "
            f"code_score={mer.get('overall_code_structure_score', 0):.1%}"
        )
        return parsed

    # ──────────────────────────────────────────────────────────
    # Write to SharedMemory
    # ──────────────────────────────────────────────────────────

    def _write_to_memory(self, parsed: dict):
        for field in [
            "repo_registration_status",
            "webhook_processing_result",
            "evolution_report",
            "file_reconstruction_result",
            "code_structure_result",
            "module_evaluation_result",
        ]:
            if field in parsed:
                self.memory.update(field, parsed[field])

        csr = parsed.get("code_structure_result", {})
        if csr.get("detected_modules"):
            self.memory.update("repository_modules", csr["detected_modules"])
        if csr.get("actual_dependency_graph"):
            self.memory.update("dependency_graph", csr["actual_dependency_graph"])

        mer = parsed.get("module_evaluation_result", {})
        if mer.get("ast_features"):
            self.memory.update("ast_features", mer["ast_features"])

    # ──────────────────────────────────────────────────────────
    # Output parser
    # ──────────────────────────────────────────────────────────

    def _parse_output(self, raw: str) -> dict:
        raw   = re.sub(r"```(?:json)?", "", raw).strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                data     = json.loads(match.group())
                required = {
                    "repo_registration_status",
                    "webhook_processing_result",
                    "evolution_report",
                    "file_reconstruction_result",
                    "code_structure_result",
                    "module_evaluation_result",
                }
                if required.issubset(data.keys()):
                    return data
            except json.JSONDecodeError:
                pass
        self.memory.log("RepositoryAgent", "WARNING: Could not parse LLM output — running fallback.")
        return None

    # ──────────────────────────────────────────────────────────
    # Python fallback (all 6 tools, no LLM)
    # ──────────────────────────────────────────────────────────

    def _fallback(self) -> dict:
        from tools.repository_tools import (
            repository_registration_tool,
            webhook_commit_processor_tool,
            commit_evolution_analyzer_tool,
            file_reconstruction_tool,
            code_structure_dependency_graph_tool,
            module_evaluation_tool,
        )

        m = self.memory
        self.memory.log("RepositoryAgent", "Running direct-Python fallback (6 steps)...")

        output_path = os.path.abspath(
            os.path.join("analysis_outputs", f"{m.repo_name or 'repo'}_analysis.json")
        )

        reg_raw  = repository_registration_tool.run(json.dumps({
            "repo_url":         m.repo_url,
            "webhook_base_url": m.webhook_base_url,
        }))

        proc_raw = webhook_commit_processor_tool.run(json.dumps({
            "owner":     m.repo_owner,
            "repo_name": m.repo_name,
            "commits":   m.pending_commits,
        }))

        evo_raw  = commit_evolution_analyzer_tool.run(json.dumps({
            "owner":     m.repo_owner,
            "repo_name": m.repo_name,
        }))

        recon_raw = file_reconstruction_tool.run(json.dumps({
            "owner":      m.repo_owner,
            "repo_name":  m.repo_name,
            "commit_sha": m.target_commit_sha,
            "filename":   m.target_filename,
            "mode":       m.reconstruction_mode,
        }))

        code_raw  = code_structure_dependency_graph_tool.run(json.dumps({
            "repo_url":           m.repo_url,
            "expected_modules":   m.expected_modules,
            "architecture_graph": m.architecture_graph,
            "output_path":        output_path,
        }))
        code_data = json.loads(code_raw)

        repo_root = code_data.get("repo_root", m.repo_url)
        eval_raw  = module_evaluation_tool.run(json.dumps({
            "repo_root":            repo_root,
            "expected_modules":     m.expected_modules,
            "complexity_threshold": 4,
        }))

        return {
            "repo_registration_status":   json.loads(reg_raw),
            "webhook_processing_result":  json.loads(proc_raw),
            "evolution_report":           json.loads(evo_raw),
            "file_reconstruction_result": json.loads(recon_raw),
            "code_structure_result":      code_data,
            "module_evaluation_result":   json.loads(eval_raw),
        }


# ══════════════════════════════════════════════════════════════
#  Flask REST API  (port 5001)
# ══════════════════════════════════════════════════════════════

def start_flask_server(memory, port: int = 5001):
    """
    Starts the RepositoryAgent Flask API in a daemon thread.

    Endpoints
    ─────────
    GET  /api/health
    GET  /api/repos
    GET  /api/events/<owner>/<repo_name>
    GET  /api/all-events
    GET  /api/evolution/<owner>/<repo_name>   ← Tool 3 evolution report
    GET  /api/commit/<owner>/<repo_name>/<sha>
    GET  /api/modules                          ← Tool 5+6: modules + dep graph
    GET  /api/dep-graph                        ← Tool 5: dependency graph only
    POST /api/submit-repo   { repo_url, webhook_base_url? }
    POST /webhook           (GitHub push webhook)
    """
    try:
        from flask import Flask, jsonify, request
        from flask_cors import CORS
    except ImportError:
        print("flask / flask-cors not installed. Run: pip install flask flask-cors")
        return

    from tools.repository_tools import (
        _load_repos,
        _load_commit_history,
        _load_commit_by_sha,
        _verify_signature,
        repository_registration_tool,
        webhook_commit_processor_tool,
        commit_evolution_analyzer_tool,
    )

    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
    flask_app      = Flask("AutoEval360-RepositoryAgent")
    CORS(flask_app)

    # ── /api/health ─────────────────────────────────────────
    @flask_app.route("/api/health")
    def health():
        return jsonify({
            "status":  "ok",
            "service": "AutoEval360-RepositoryAgent",
            "port":    port,
        })

    # ── /api/repos ──────────────────────────────────────────
    @flask_app.route("/api/repos")
    def get_repos():
        repos = _load_repos()
        return jsonify([
            {
                "id":             idx,
                "repo_url":       data["repo_url"],
                "owner":          data["owner"],
                "repo_name":      data["repo_name"],
                "webhook_active": True,
                "created_at":     data["created_at"],
            }
            for idx, (_, data) in enumerate(repos.items())
        ])

    # ── /api/submit-repo ─────────────────────────────────────
    @flask_app.route("/api/submit-repo", methods=["POST"])
    def submit_repo():
        data             = request.json or {}
        repo_url         = data.get("repo_url", "").strip()
        webhook_base_url = data.get("webhook_base_url", request.host_url.rstrip("/"))
        if not repo_url:
            return jsonify({"error": "repo_url is required"}), 400
        # FIX: use .run() — Tool objects are not directly callable in CrewAI >= 0.80
        result = json.loads(repository_registration_tool.run(json.dumps({
            "repo_url":         repo_url,
            "webhook_base_url": webhook_base_url,
        })))
        if "error" in result:
            return jsonify({"error": result["error"]}), 400
        return jsonify({"message": "Repository registered", **result})

    # ── /webhook  (GitHub push) ──────────────────────────────
    @flask_app.route("/webhook", methods=["POST"])
    def github_webhook():
        raw_body  = request.get_data()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if WEBHOOK_SECRET:
            if not signature or not _verify_signature(raw_body, signature, WEBHOOK_SECRET):
                return "", 401

        payload    = request.get_json(silent=True)
        event_type = request.headers.get("X-GitHub-Event")
        if not payload or event_type != "push":
            return "", 200

        full_name = payload.get("repository", {}).get("full_name", "")
        if not full_name or "/" not in full_name:
            return "", 200

        owner, repo_name = full_name.split("/")
        commits          = payload.get("commits", [])

        # FIX: use .run() — Tool objects are not directly callable in CrewAI >= 0.80
        result = json.loads(webhook_commit_processor_tool.run(json.dumps({
            "owner": owner, "repo_name": repo_name, "commits": commits,
        })))
        memory.log(
            "RepositoryAgent-Webhook",
            f"Processed {result.get('processed_count', 0)} commits for {owner}/{repo_name}",
        )
        return "", 200

    # ── /api/events/<owner>/<repo_name> ─────────────────────
    @flask_app.route("/api/events/<owner>/<repo_name>")
    def get_events(owner, repo_name):
        commits = _load_commit_history(owner, repo_name)
        return jsonify([
            {
                "commit_sha":      c["commit_sha"],
                "parent_sha":      c.get("parent_sha"),
                "event_type":      c["event"]["type"],
                "description":     c["event"]["description"],
                "files_changed":   c["event"]["files_changed"],
                "total_additions": c["event"].get("total_additions", 0),
                "total_deletions": c["event"].get("total_deletions", 0),
                "timestamp":       c["timestamp"],
                "message":         c.get("message", ""),
                "author":          c.get("author", {}),
            }
            for c in commits[:50]
        ])

    # ── /api/all-events ──────────────────────────────────────
    @flask_app.route("/api/all-events")
    def get_all_events():
        repos      = _load_repos()
        all_events = []
        for _, repo_data in repos.items():
            owner     = repo_data["owner"]
            repo_name = repo_data["repo_name"]
            for c in _load_commit_history(owner, repo_name):
                all_events.append({
                    "commit_sha":      c["commit_sha"],
                    "parent_sha":      c.get("parent_sha"),
                    "event_type":      c["event"]["type"],
                    "description":     c["event"]["description"],
                    "files_changed":   c["event"]["files_changed"],
                    "total_additions": c["event"].get("total_additions", 0),
                    "total_deletions": c["event"].get("total_deletions", 0),
                    "timestamp":       c["timestamp"],
                    "repo_name":       repo_name,
                    "owner":           owner,
                })
        all_events.sort(key=lambda x: x["timestamp"], reverse=True)
        return jsonify(all_events[:100])

    # ── /api/evolution/<owner>/<repo_name>  (Tool 3) ────────
    @flask_app.route("/api/evolution/<owner>/<repo_name>")
    def get_evolution(owner, repo_name):
        """
        Returns the full commit evolution report for a repository.
        Checks SharedMemory first, then regenerates from disk.
        """
        # Check SharedMemory first (fastest if already computed)
        evo = getattr(memory, "evolution_report", {})
        if evo and not evo.get("error"):
            return jsonify(evo)

        # FIX: use .run() — Tool objects are not directly callable in CrewAI >= 0.80
        result = json.loads(commit_evolution_analyzer_tool.run(json.dumps({
            "owner":     owner,
            "repo_name": repo_name,
        })))
        return jsonify(result)

    # ── /api/commit/<owner>/<repo_name>/<sha> ───────────────
    @flask_app.route("/api/commit/<owner>/<repo_name>/<sha>")
    def get_commit_detail(owner, repo_name, sha):
        commit = _load_commit_by_sha(owner, repo_name, sha)
        if not commit:
            return jsonify({"error": "Commit not found"}), 404
        return jsonify(commit)

    # ── /api/modules  (Tool 5 + Tool 6 combined) ────────────
    @flask_app.route("/api/modules")
    def get_modules():
        csr = getattr(memory, "code_structure_result",    {}) or {}
        mer = getattr(memory, "module_evaluation_result", {}) or {}
        return jsonify({
            # Tool 6
            "ast_features":                 mer.get("ast_features",                {}),
            "module_scores":                mer.get("module_scores",                {}),
            "overall_code_structure_score": mer.get("overall_code_structure_score", 0),
            "fully_implemented":            mer.get("fully_implemented",            0),
            "partially_implemented":        mer.get("partially_implemented",        0),
            "stub_or_empty":                mer.get("stub_or_empty",               0),
            # Tool 5
            "repository_modules":           csr.get("detected_modules",            []),
            "missing_modules":              csr.get("missing_modules",             []),
            "unexpected_modules":           csr.get("unexpected_modules",           []),
            "dependency_graph":             csr.get("actual_dependency_graph",      {}),
            "dependency_coverage":          csr.get("dependency_coverage",          0),
            "matched_edges":                csr.get("matched_edges",               []),
            "missing_edges":                csr.get("missing_edges",               []),
            "missing_connections":          csr.get("missing_connections",          {}),
            "files_analyzed":               csr.get("files_analyzed",               0),
            "total_functions":              csr.get("total_functions",              0),
            "files_by_language":            csr.get("files_by_language",            {}),
            "module_file_map":              csr.get("module_file_map",              {}),
            "mapping_stats":                csr.get("mapping_stats",                {}),
            # Status
            "ready": bool(mer.get("ast_features")),
        })

    # ── /api/dep-graph  (Tool 5 only) ───────────────────────
    @flask_app.route("/api/dep-graph")
    def get_dep_graph():
        csr = getattr(memory, "code_structure_result", {}) or {}
        return jsonify({
            "dependency_graph":    csr.get("actual_dependency_graph", {}),
            "repository_modules":  csr.get("detected_modules",        []),
            "dependency_coverage": csr.get("dependency_coverage",      0),
            "matched_edges":       csr.get("matched_edges",           []),
            "missing_edges":       csr.get("missing_edges",           []),
            "missing_connections": csr.get("missing_connections",      {}),
            "mapping_stats":       csr.get("mapping_stats",            {}),
        })

    # ── Start server ─────────────────────────────────────────
    print(f"\nAutoEval360 RepositoryAgent API → http://localhost:{port}")
    print(f"  Endpoints:")
    print(f"    GET  /api/health")
    print(f"    GET  /api/repos")
    print(f"    GET  /api/all-events")
    print(f"    GET  /api/events/<owner>/<repo>")
    print(f"    GET  /api/evolution/<owner>/<repo>")
    print(f"    GET  /api/modules")
    print(f"    GET  /api/dep-graph")
    print(f"    POST /api/submit-repo")
    print(f"    POST /webhook")

    t = threading.Thread(
        target=lambda: flask_app.run(debug=False, port=port, use_reloader=False),
        daemon=True,
    )
    t.start()
    return t