#!/usr/bin/env python3
"""TokenWise MCP classifier + agent generator.

Enumerates and classifies every available MCP tool by asking an UNRESTRICTED,
already-authenticated headless Claude session (`claude -p --agent claude`) — the
only path that reaches OAuth/remote/plugin-provided servers, since it uses the
live tokens. That headless enumeration is the SOURCE OF TRUTH for tool NAMES
(exact, verbatim, runtime names — including plugin-provided servers' real
`mcp__plugin_<plugin>_<server>__` prefix); the stdio protocol path is only ever
trusted to synthesize a name for servers it can directly confirm the prefix of
(plain ~/.claude.json / .mcp.json stdio servers), and otherwise only supplies
read/write annotations. Each tool is tagged read or write, then written into
the generated agents:
  read  -> scout     (read-only recon tier)
  write -> mechanic  (execution tier)
The orchestrator holds no MCP tools; it reads TOOL-ROUTING.md to route.

Regenerates agents into ~/.claude/agents/ from templates on each run. Cheap:
re-enumerates (one Haiku call) ONLY when the set of configured MCP servers
changed since last run; otherwise regenerates from cache. Run at SessionStart
and on install.

Reentrancy: enumerating spawns `claude -p`, which fires SessionStart again — so
this exits immediately if TOKENWISE_CLASSIFYING is set, and it sets that var for
the child. The SessionStart hook also guards on it.

Usage: classify-mcp.py [--templates DIR] [--agents DIR] [--force] [--print]
"""
import json, os, re, subprocess, sys, hashlib

if os.environ.get("TOKENWISE_CLASSIFYING"):
    sys.exit(0)  # reentrancy guard: we're inside the enumeration child

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", "tokenwise")
CACHE = os.path.join(STATE_DIR, "cache.json")
ROUTING = os.path.join(STATE_DIR, "TOOL-ROUTING.md")
POLICY = os.path.join(STATE_DIR, "mcp-policy.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag)+1] if flag in sys.argv else default

TEMPLATES = arg("--templates", os.path.normpath(os.path.join(SCRIPT_DIR, "..", "templates")))
AGENTS_DIR = arg("--agents", os.path.join(HOME, ".claude", "agents"))

def run(cmd, timeout=180, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=env or os.environ).stdout
    except Exception:
        return ""

def server_hash():
    """Hash just the set of configured server names (ignore transient health)."""
    out = run(["claude","mcp","list"], timeout=30)
    servers = sorted(set(re.findall(r'^([A-Za-z0-9._-]+):', out, re.M)) - {"Checking"})
    return hashlib.sha256("\n".join(servers).encode()).hexdigest(), servers

READ_RE  = re.compile(r'(^|_)(get|list|search|read|fetch|describe|inspect|view|find|count|status|overview|export|download|check)(_|$)', re.I)
WRITE_RE = re.compile(r'(^|_)(create|update|delete|send|write|move|remove|set|add|edit|compose|save|manage|trash|reply|forward|upload|modify|patch|put|post|run|exec|apply|import|sync|copy|rename|archive|fill|click|navigate|type|drag|press|emulate|resize|handle)(_|$)', re.I)

def load_servers():
    """Full server specs (command/args/ENV or url) from MCP config — reading the
    config, not `claude mcp get`, is what gives us env secrets to launch
    auth'd stdio servers."""
    servers = {}
    for p in (os.path.join(HOME, ".claude.json"), os.path.join(os.getcwd(), ".mcp.json")):
        if not os.path.exists(p): continue
        try: cfg = json.load(open(p))
        except Exception: continue
        for name, spec in (cfg.get("mcpServers") or {}).items():
            servers.setdefault(name, spec)
    return servers

def classify_proto(tool):
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is True: return "read"
    if ann.get("destructiveHint") is True: return "write"
    n = tool.get("name","")
    if WRITE_RE.search(n): return "write"
    if READ_RE.search(n):  return "read"
    return "write"   # unknown -> safe (execution tier)

def list_tools_stdio(command, args, env=None):
    """Speak MCP tools/list over stdio, launched WITH the server's env. Never raises."""
    full_env = dict(os.environ)
    if env: full_env.update({k: str(v) for k, v in env.items()})
    try:
        p = subprocess.Popen([command,*args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1, env=full_env)
    except Exception:
        return []
    def send(o):
        try: p.stdin.write(json.dumps(o)+"\n"); p.stdin.flush(); return True
        except Exception: return False
    try:
        import time
        if not send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"tokenwise","version":"0"}}}): return []
        p.stdout.readline()
        send({"jsonrpc":"2.0","method":"notifications/initialized"})
        if not send({"jsonrpc":"2.0","id":2,"method":"tools/list"}): return []
        deadline = time.time()+15
        while time.time() < deadline:
            if p.poll() is not None: break
            line = p.stdout.readline()
            if not line: break
            try: msg = json.loads(line)
            except Exception: continue
            if msg.get("id") == 2: return msg.get("result",{}).get("tools",[])
    except Exception:
        return []
    finally:
        try: p.terminate()
        except Exception: pass
    return []

def enumerate_headless():
    """Authed headless Claude — the ONLY path that reaches OAuth/remote/plugin-provided
    servers, and therefore the SOURCE OF TRUTH for tool NAMES (they must exactly match
    the runtime names granted to generated agents)."""
    prompt = ("Output ONLY a JSON array — no prose, no markdown fence. First call ToolSearch to "
              "load any deferred MCP tools. Then for EVERY tool available to you whose name starts "
              'with "mcp__", output {"name":"<tool name>","tier":"read" or "write"}. '
              'The "name" field MUST be the EXACT, verbatim, case-sensitive tool name as it appears '
              "in your own tool list right now — copy it character-for-character. Do NOT normalize, "
              "retitle, guess, abbreviate, or reformat it, and do NOT alter, add, or drop any part of "
              'its prefix (for example a plugin-provided server\'s prefix like "mcp__plugin_<plugin>_'
              '<server>__" must be reproduced exactly as-is, not simplified to "mcp__<server>__"). '
              "tier=read when the tool only observes/queries and never changes state; tier=write "
              "when it creates, modifies, sends, deletes, uploads, or executes. Be exhaustive.")
    env = dict(os.environ); env["TOKENWISE_CLASSIFYING"] = "1"
    txt = run(["claude","-p","--agent","claude","--model","haiku",prompt], timeout=240, env=env)
    m = re.search(r'\[.*\]', txt, re.S)
    if not m: return []
    try:
        return [t for t in json.loads(m.group(0))
                if isinstance(t, dict) and str(t.get("name","")).startswith("mcp__")]
    except Exception:
        return []

def enumerate_tools():
    """Hybrid, but with a strict trust order: headless enumeration is the ONLY source
    of truth for tool NAMES, since it reflects real runtime names (including
    plugin-provided servers, whose prefix is `mcp__plugin_<plugin>_<server>__`, NOT
    `mcp__<server>__`). The stdio protocol path only ever confirms the runtime prefix
    for servers it can directly see in ~/.claude.json / .mcp.json — those are always
    plain stdio servers with a confirmed `mcp__<server>__` prefix (plugins declare
    their own servers elsewhere and never appear here), so it is safe to synthesize
    names for them. Protocol is used to (a) supply read/write annotations for tools
    headless also reported, and (b) backfill confirmed-prefix stdio tools headless
    missed. It NEVER overrides or supersedes a name headless actually reported, and
    it never contributes a name for a server it can't confirm the prefix for."""
    proto = {}   # full_name -> {"name","tier"}, confirmed-prefix stdio tools only
    for name, spec in load_servers().items():
        if spec.get("command"):
            for t in list_tools_stdio(spec["command"], spec.get("args",[]), spec.get("env")):
                full = f"mcp__{name}__{t.get('name','')}"
                proto[full] = {"name": full, "tier": classify_proto(t)}

    headless = enumerate_headless()      # authoritative runtime tool NAMES
    if not headless and not proto:
        return None

    tools = {}
    for t in headless:                   # names as reported by the runtime, verbatim
        name = t["name"]
        tier = proto[name]["tier"] if name in proto else t.get("tier", "write")
        tools[name] = {"name": name, "tier": tier}
    for full, t in proto.items():         # backfill confirmed stdio tools headless missed
        tools.setdefault(full, t)
    return list(tools.values()) or None

def load_policy():
    if os.path.exists(POLICY):
        try: return json.load(open(POLICY))
        except Exception: pass
    return {}

def assign(tools, policy):
    tiers = policy.get("tiers", {"read":"scout","write":"mechanic"})
    tool_over = policy.get("tools", {})     # {full_name: read|write|skip}
    server_over = policy.get("servers", {}) # {server: read|write|skip}
    out = {"scout": [], "mechanic": []}
    for t in tools:
        name = t.get("name","")
        parts = name.split("__")
        server = parts[1] if len(parts) >= 3 else ""
        tier = tool_over.get(name) or server_over.get(server) or (t.get("tier") or "write")
        if tier == "skip": continue
        agent = tiers.get(tier, "mechanic")
        out.setdefault(agent, []).append(name)
    for k in out: out[k] = sorted(set(out[k]))
    return out

def generate_agents(assignment):
    os.makedirs(AGENTS_DIR, exist_ok=True)
    for base in ["orchestrator","scout","mechanic","builder"]:
        tpl = os.path.join(TEMPLATES, base+".md")
        if not os.path.exists(tpl): continue
        content = open(tpl).read()
        add = assignment.get(base, [])
        if add:
            content = re.sub(r'^(tools:.*)$',
                             lambda m: m.group(1).rstrip() + ", " + ", ".join(add),
                             content, count=1, flags=re.M)
        open(os.path.join(AGENTS_DIR, base+".md"), "w").write(content)

def write_routing(tools, assignment, servers):
    os.makedirs(STATE_DIR, exist_ok=True)
    by_server = {}
    for t in tools:
        parts = t.get("name","").split("__")
        if len(parts) < 3: continue
        s = parts[1]; by_server.setdefault(s, {"read":0,"write":0})
        by_server[s]["read" if t.get("tier")=="read" else "write"] += 1
    lines = ["# MCP tool routing (generated by tokenwise — do not edit by hand)\n",
             "read tools -> scout · write tools -> mechanic · orchestrator delegates, holds none.\n",
             "| Server | read→scout | write→mechanic |", "|---|---|---|"]
    for s in sorted(by_server):
        lines.append(f"| {s} | {by_server[s]['read']} | {by_server[s]['write']} |")
    unseen = [s for s in servers if s not in by_server]
    if unseen:
        lines.append("")
        lines.append("Configured but no tools enumerated (not authorized / not connected): "
                     + ", ".join(unseen) + ". Authorize them, or declare a tier in mcp-policy.json.")
    open(ROUTING, "w").write("\n".join(lines) + "\n")

def main():
    policy = load_policy()
    h, servers = server_hash()
    cache = {}
    if os.path.exists(CACHE):
        try: cache = json.load(open(CACHE))
        except Exception: cache = {}

    tools = None
    if "--force" not in sys.argv and cache.get("hash") == h and cache.get("tools"):
        tools = cache["tools"]          # servers unchanged -> reuse (no model call)
    else:
        tools = enumerate_tools()
        if tools is None:               # enumeration failed -> keep last known
            tools = cache.get("tools")
        if tools is None:
            tools = []

    assignment = assign(tools, policy)

    if "--print" in sys.argv:
        write_routing(tools, assignment, servers)
        print(open(ROUTING).read()); return

    generate_agents(assignment)
    write_routing(tools, assignment, servers)
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"hash": h, "tools": tools, "assignment": assignment}, open(CACHE,"w"), indent=2)
    n = sum(len(v) for v in assignment.values())
    print(f"tokenwise: {n} MCP tools classified across {len(servers)} servers "
          f"(scout {len(assignment.get('scout',[]))}, mechanic {len(assignment.get('mechanic',[]))}); "
          f"agents regenerated in {AGENTS_DIR}")

if __name__ == "__main__":
    main()
