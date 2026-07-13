#!/usr/bin/env python3
"""Quartermaster MCP classifier + agent generator.

Enumerates and classifies every available MCP tool DETERMINISTICALLY, by
replaying `deferred_tools_delta` records that Claude Code itself writes into
session transcripts (~/.claude/projects/<slug>/*.jsonl) — the exact, verbatim,
runtime tool-name list it offered a session, including plugin-provided
servers' real `mcp__plugin_<plugin>_<server>__` prefix. This is the SOURCE OF
TRUTH for tool NAMES and requires no model call, so it can't truncate or drop
servers the way asking a Haiku session to recite its own tool list could on a
large (30-server) setup. The stdio protocol path only ever supplies read/write
annotations for names transcripts (or headless, see below) already found;
names it can't match fall back to the READ_RE/WRITE_RE name heuristics. Each
tool is tagged read or write, then written into the generated agents:
  read  -> scout     (read-only recon tier)
  write -> mechanic  (execution tier)
The orchestrator holds no MCP tools; it reads TOOL-ROUTING.md to route.

Fallback: if NO transcript on disk has ever recorded a `deferred_tools_delta`
(brand-new machine, no prior sessions), fall back to the old
`enumerate_headless()` — asking an unrestricted, already-authenticated
headless Claude session (`claude -p --agent claude`) to recite its own
`mcp__*` tool list. That path is flaky at scale (the reason this file exists)
but is the only option with zero transcript history to mine.

Regenerates agents into ~/.claude/agents/ from templates on each run. Cheap:
re-enumerates ONLY when the set of configured MCP servers changed since last
run (transcript replay is fast — no model call in the common case; the
headless fallback, when it's used, costs one Haiku call); otherwise
regenerates from cache. Run at SessionStart and on install.

Reentrancy: the headless fallback spawns `claude -p`, which fires SessionStart
again — so this exits immediately if QUARTERMASTER_CLASSIFYING is set, and it sets
that var for the child. The SessionStart hook also guards on it.

Usage: classify-mcp.py [--templates DIR] [--agents DIR] [--force] [--print]
"""
import json, os, re, subprocess, sys, hashlib, time, glob

if os.environ.get("QUARTERMASTER_CLASSIFYING"):
    sys.exit(0)  # reentrancy guard: we're inside the enumeration child

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", "quartermaster")
CACHE = os.path.join(STATE_DIR, "cache.json")
ROUTING = os.path.join(STATE_DIR, "TOOL-ROUTING.md")
POLICY = os.path.join(STATE_DIR, "mcp-policy.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Connection-race constants. Some MCP servers (e.g. a plugin-provided `slack`)
# are still connecting when SessionStart fires `claude mcp list` reports them
# with a non-terminal status (or omits them entirely) until they settle.
CONNECT_POLL_INTERVAL = 3   # seconds between `claude mcp list` polls
CONNECT_TIMEOUT       = 60  # total seconds to wait for servers to settle
RETRY_WAIT            = 5   # seconds to wait before re-enumerating an incomplete server
RETRY_MAX             = 3   # max re-enumeration attempts for incomplete servers

# A single session's transcript can be INCOMPLETE for a server that was still
# connecting (or simply untouched) at that session's specific start moment --
# the same connection race CONNECT_TIMEOUT/RETRY_* guard against for the
# `claude mcp list`-driven paths. So transcript replay doesn't stop at the
# single newest transcript: it keeps unioning newest-first transcripts until
# every currently-configured server is covered, or it runs out of transcripts
# (or hits this cap, for safety on machines with very long session history).
TRANSCRIPT_SCAN_LIMIT = 200

SETTLED_RE = re.compile(r'connected|failed|needs authentication', re.I)

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

SERVER_LINE_RE = re.compile(r'^(.+?):\s.+\s-\s+(.+)$')

def parse_mcp_servers(text=None):
    """The SINGLE source of truth for parsing `claude mcp list` output. Returns
    an ordered list of {"name": <server id>, "status": <raw status text>}, e.g.
    'claude.ai Google Drive: https://... - ✔ Connected' ->
        {"name": "claude.ai Google Drive", "status": "✔ Connected"}
    'plugin:slack:slack: https://mcp.slack.com/mcp (HTTP) - ! Needs authentication' ->
        {"name": "plugin:slack:slack", "status": "! Needs authentication"}
    Server ids/display names are NOT restricted to a safe charset -- they may
    contain colons (plugin-provided servers like `plugin:slack:slack`) or
    spaces/dots (`claude.ai Google Drive`) -- so we never match on a name
    charset. Instead we rely on the fixed shape `claude mcp list` always
    emits: "<name>: <target> - <status>", where the LAST ": " before the
    target is the delimiter (any colons inside the name itself are never
    followed by whitespace, since only the final one -- before the target --
    is), and the last " - " before the status. Every caller that needs
    server identity/status MUST go through this function; do not re-parse
    `claude mcp list` ad hoc elsewhere."""
    if text is None:
        text = run(["claude","mcp","list"], timeout=30)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = SERVER_LINE_RE.match(line)
        if m:
            out.append({"name": m.group(1).strip(), "status": m.group(2).strip()})
    return out

def status_category(status):
    """Bucket a raw status string (e.g. '! Needs authentication') into one of:
    connected / needs authentication / connecting / failed / other. 'Checking'
    (the transient pre-poll state) buckets as connecting."""
    s = (status or "").lower()
    if "authenticat" in s: return "needs authentication"
    if "fail" in s: return "failed"
    if "connected" in s: return "connected"
    if "connect" in s or "checking" in s: return "connecting"
    return "other"

def server_hash(servers=None):
    """Hash configured server NAME+STATUS pairs -- not just names. A server
    going Needs-authentication -> Connected (e.g. the user just authorized
    Slack via /mcp) does not change the set of server names, but it MUST
    change this hash so the next classify run treats it as changed and
    re-enumerates instead of silently reusing the stale (zero-tool) cache."""
    if servers is None:
        servers = parse_mcp_servers()
    key = sorted(f"{s['name']}\x01{s['status']}" for s in servers)
    return hashlib.sha256("\n".join(key).encode()).hexdigest(), servers

def wait_for_settled(timeout=CONNECT_TIMEOUT, interval=CONNECT_POLL_INTERVAL, confirm=2):
    """Poll `claude mcp list` until every server it reports has a terminal
    status (Connected / Needs authentication / Failed) AND the set of server
    names is unchanged, for `confirm` consecutive polls in a row (or the
    timeout elapses). Requiring repeated confirmation -- not just one clean
    poll -- gives a server that hasn't been printed by `claude mcp list` yet
    at all more chances to appear before we declare things settled; it can't
    be foolproof against an arbitrarily slow late starter, which is why
    incomplete_connected_servers() below is a second, independent safety net
    applied AFTER enumeration too."""
    deadline = time.time() + timeout
    prev_names = None
    stable_hits = 0
    servers = []
    while True:
        servers = parse_mcp_servers()
        pending = [s for s in servers if not SETTLED_RE.search(s["status"])]
        names = {s["name"] for s in servers}
        stable = prev_names is not None and prev_names == names
        stable_hits = stable_hits + 1 if (not pending and stable) else 0
        if stable_hits >= confirm:
            return servers
        if time.time() >= deadline:
            return servers
        prev_names = names
        time.sleep(interval)

def _norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def tool_segment(name):
    """The server segment of a full `mcp__<server>__<tool>` name, or "" if
    the name isn't shaped like one. Single shared helper for every place
    that needs to map a tool name back to its server."""
    parts = name.split("__")
    return parts[1] if len(parts) >= 3 else ""

def connected_display_names(servers):
    """Servers `claude mcp list` reports as fully Connected (not needing
    auth, not failed)."""
    return [s["name"] for s in servers if status_category(s["status"]) == "connected"]

def tool_server_segments(tools):
    segs = set()
    for t in tools or []:
        parts = t.get("name","").split("__")
        if len(parts) >= 3:
            segs.add(parts[1])
    return segs

def incomplete_connected_servers(statuses, tools):
    """Connected servers that produced ZERO tools in this enumeration --
    almost certainly because they connected AFTER enumeration started."""
    connected = connected_display_names(statuses)
    segs_norm = {_norm(s) for s in tool_server_segments(tools)}
    return [n for n in connected if _norm(n) not in segs_norm]

def merge_tool_lists(base, extra):
    merged = {t["name"]: t for t in (base or [])}
    for t in (extra or []):
        merged.setdefault(t["name"], t)
    return list(merged.values())

def merge_with_cache(tools, cache_tools):
    """Never let a connected server that returns zero tools this run clobber
    its previously-cached tools: keep last-known-good per server, and only
    replace a server's tool set when this run actually returned tools for it."""
    if not cache_tools:
        return tools or []
    def seg(name):
        parts = name.split("__")
        return parts[1] if len(parts) >= 3 else ""
    servers_with_new = {seg(t["name"]) for t in (tools or []) if seg(t["name"])}
    merged = list(tools or [])
    seen_names = {t["name"] for t in merged}
    for t in cache_tools:
        if seg(t.get("name","")) in servers_with_new:
            continue  # this run has fresh data for that server -> trust it, drop stale entries
        if t["name"] not in seen_names:
            merged.append(t)
            seen_names.add(t["name"])
    return merged

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

def classify_by_name(name):
    """Name-only heuristic fallback (READ_RE/WRITE_RE) -- used for tool names
    that transcript replay (or headless fallback) supplied but the stdio
    protocol path couldn't confirm annotations for."""
    if WRITE_RE.search(name): return "write"
    if READ_RE.search(name):  return "read"
    return "write"   # unknown -> safe (execution tier)

def classify_proto(tool):
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is True: return "read"
    if ann.get("destructiveHint") is True: return "write"
    return classify_by_name(tool.get("name",""))

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
        if not send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"quartermaster","version":"0"}}}): return []
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

def transcript_files():
    """All session transcripts on disk, newest-modified first."""
    files = glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:TRANSCRIPT_SCAN_LIMIT]

def _transcript_deferred_names(path):
    """Replay a single transcript's `deferred_tools_delta` records IN ORDER.
    Each record's addedNames are unioned in, removedNames pruned OUT -- both
    scoped to THIS transcript only (a name removed in one session's replay
    never affects another session's). addedNames mixes MCP tool names
    (`mcp__*`) and Claude Code's own DEFERRED BUILT-IN tools (Monitor,
    SendMessage, Task*/Cron*, LSP, NotebookEdit, ...) -- both are recorded
    verbatim here and split by the mcp__ prefix, so callers get each list
    separately. Returns (mcp_names_set, builtin_names_set,
    needs_auth_last_seen_or_None, saw_any_record_bool). Never raises -- an
    unreadable/corrupt transcript is just treated as if it had no records."""
    names = set()
    builtin_names = set()
    needs_auth = None
    saw_record = False
    try:
        with open(path, "r", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                att = rec.get("attachment")
                if not (isinstance(att, dict) and att.get("type") == "deferred_tools_delta"):
                    continue
                saw_record = True
                for n in (att.get("addedNames") or []):
                    if not isinstance(n, str):
                        continue
                    if n.startswith("mcp__"):
                        names.add(n)
                    else:
                        builtin_names.add(n)
                for n in (att.get("removedNames") or []):
                    names.discard(n)
                    builtin_names.discard(n)
                na = att.get("needsAuthMcpServers")
                if na is not None:
                    needs_auth = na
    except Exception:
        return set(), set(), None, False
    return names, builtin_names, needs_auth, saw_record

def enumerate_transcripts(configured_servers=None):
    """DETERMINISTIC MCP tool-name source, no model call: Claude Code itself
    records the exact set of `mcp__*` tool names it offered a session in
    `deferred_tools_delta` attachments inside that session's own transcript
    (~/.claude/projects/<slug>/*.jsonl). Replaying addedNames/removedNames in
    order within one transcript gives that session's final deferred-tool set
    -- exact runtime names, verbatim, including plugin-provided servers' real
    prefix.

    configured_servers (parse_mcp_servers() output, i.e. every server `claude
    mcp list` currently reports) drives BOTH an early-exit AND a final filter:
    we scan transcripts newest-first, UNIONING names across them (not just
    trusting the single newest one -- see TRANSCRIPT_SCAN_LIMIT's comment for
    why), and stop as soon as every currently-configured server's segment is
    represented, or transcripts run out. Because scanning multiple transcripts
    can pull in OTHER segments incidentally (a still-configured server's
    deferred_tools_delta record sits alongside a long-gone server's in the
    same transcript), the result is then filtered down to only segments that
    match a currently-configured server -- so a genuinely stale server,
    removed from config but still sitting in old transcript history, never
    pollutes the result or gets a row in TOOL-ROUTING.md / a grant in a
    generated agent. When configured_servers is empty/None (caller has no
    config reference), no filter is applied.

    needsAuthMcpServers is taken ONLY from the single freshest transcript
    that recorded one, never merged across sessions -- auth state goes stale,
    unlike tool names (a name once offered is still a real name).

    Deferred BUILT-IN tool names (everything addedNames carries that does NOT
    start with mcp__ -- Monitor, SendMessage, Task*/Cron*, LSP, NotebookEdit,
    etc.) are unioned across every transcript scanned, with no per-server
    early-exit/filter (they aren't tied to any configured MCP server).

    Returns (sorted_mcp_name_list_or_None, needs_auth_list,
    sorted_builtin_name_list). None for the first element means NO transcript
    anywhere ever recorded a deferred_tools_delta -- caller should fall back
    to enumerate_headless()."""
    configured_norm = {_norm(s["name"]) for s in (configured_servers or [])}
    names = set()
    builtin_names = set()
    needs_auth = None
    needs_auth_set = False
    any_record = False
    for path in transcript_files():
        t_names, t_builtin_names, t_needs_auth, saw_record = _transcript_deferred_names(path)
        if not saw_record:
            continue
        any_record = True
        names |= t_names
        builtin_names |= t_builtin_names
        if not needs_auth_set:
            needs_auth = t_needs_auth
            needs_auth_set = True
        if configured_norm:
            segs_norm = {_norm(s) for s in tool_server_segments([{"name": n} for n in names])}
            if configured_norm <= segs_norm:
                break
    if not any_record:
        return None, (needs_auth or []), sorted(builtin_names)
    if configured_norm:
        names = {n for n in names if _norm(tool_segment(n)) in configured_norm}
    return sorted(names), (needs_auth or []), sorted(builtin_names)

def enumerate_headless():
    """Authed headless Claude — FALLBACK ONLY, used when no transcript anywhere
    has ever recorded a deferred_tools_delta. The only path that reaches
    OAuth/remote/plugin-provided servers without transcript history, since it
    uses the live tokens -- but flaky at scale (the reason enumerate_transcripts
    above is the primary source)."""
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
    env = dict(os.environ); env["QUARTERMASTER_CLASSIFYING"] = "1"
    txt = run(["claude","-p","--agent","claude","--model","haiku",prompt], timeout=240, env=env)
    m = re.search(r'\[.*\]', txt, re.S)
    if not m: return []
    try:
        return [t for t in json.loads(m.group(0))
                if isinstance(t, dict) and str(t.get("name","")).startswith("mcp__")]
    except Exception:
        return []

def enumerate_tools(servers=None):
    """Hybrid, but with a strict trust order: transcript replay
    (enumerate_transcripts) is the PRIMARY, deterministic source of truth for
    tool NAMES, since it reflects real runtime names Claude Code itself
    recorded (including plugin-provided servers, whose prefix is
    `mcp__plugin_<plugin>_<server>__`, NOT `mcp__<server>__`) with no model
    call. The stdio protocol path only ever confirms the runtime prefix for
    servers it can directly see in ~/.claude.json / .mcp.json — those are
    always plain stdio servers with a confirmed `mcp__<server>__` prefix
    (plugins declare their own servers elsewhere and never appear here), so
    it is safe to synthesize names for them. Protocol supplies read/write
    annotations for names transcripts (or headless) also reported; names it
    can't match fall back to the classify_by_name heuristic. Protocol NEVER
    overrides or supersedes a name transcripts/headless actually reported,
    and it never contributes a name for a server it can't confirm the
    prefix for.

    enumerate_headless() (one Haiku call, flaky at scale) is used ONLY when
    NO transcript anywhere has ever recorded a deferred_tools_delta. It never
    discovers deferred BUILT-IN tool names (only transcripts record those),
    so builtin_names below comes from enumerate_transcripts regardless of
    which path (transcript/headless) supplied the MCP tool names.

    Returns (tools_list_or_None, needs_auth_list, builtin_name_list)."""
    proto = {}   # full_name -> {"name","tier"}, confirmed-prefix stdio tools only
    for name, spec in load_servers().items():
        if spec.get("command"):
            for t in list_tools_stdio(spec["command"], spec.get("args",[]), spec.get("env")):
                full = f"mcp__{name}__{t.get('name','')}"
                proto[full] = {"name": full, "tier": classify_proto(t)}

    names, needs_auth, builtin_names = enumerate_transcripts(servers)
    if names is not None:                # transcript replay -- primary, deterministic path
        tools = {}
        for n in names:                  # names as recorded by the runtime, verbatim
            tier = proto[n]["tier"] if n in proto else classify_by_name(n)
            tools[n] = {"name": n, "tier": tier}
        for full, t in proto.items():    # backfill confirmed stdio tools transcripts missed
            tools.setdefault(full, t)
        return (list(tools.values()) or None), needs_auth, builtin_names

    headless = enumerate_headless()      # last-resort fallback: no transcript history at all
    if not headless and not proto:
        return None, needs_auth, builtin_names

    tools = {}
    for t in headless:                   # names as reported by the runtime, verbatim
        name = t["name"]
        tier = proto[name]["tier"] if name in proto else t.get("tier", "write")
        tools[name] = {"name": name, "tier": tier}
    for full, t in proto.items():         # backfill confirmed stdio tools headless missed
        tools.setdefault(full, t)
    return (list(tools.values()) or None), needs_auth, builtin_names

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

# Curated map of Claude Code's own DEFERRED BUILT-IN tools (everything
# `deferred_tools_delta.addedNames` carries that does NOT start with
# `mcp__` -- Monitor, SendMessage, Task*/Cron*, LSP, NotebookEdit, worktree
# tools, etc.) to the agent(s) that should hold them. A tool may legitimately
# appear under more than one agent (e.g. LSP: scout/mechanic/builder all get
# it). This is a curated allowlist, not a heuristic -- names absent from it
# are "unknown" and handled by the safe default in classify_builtins().
BUILTIN_TIERS = {
    "orchestrator": ["Monitor", "SendMessage", "TaskCreate", "TaskGet", "TaskList",
                      "TaskOutput", "TaskStop", "TaskUpdate", "CronCreate", "CronList",
                      "CronDelete", "PushNotification", "RemoteTrigger", "EnterPlanMode",
                      "ExitPlanMode", "ToolSearch", "ListMcpResourcesTool",
                      "ReadMcpResourceTool", "ReadMcpResourceDirTool", "WebFetch", "WebSearch"],
    "scout":        ["ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool", "LSP", "WebFetch", "WebSearch"],
    "mechanic":     ["NotebookEdit", "EnterWorktree", "ExitWorktree", "DesignSync", "LSP", "WebFetch", "WebSearch"],
    "builder":      ["NotebookEdit", "LSP", "EnterWorktree", "ExitWorktree", "WebFetch", "WebSearch"],
}

# Non-negotiable: the orchestrator must NEVER hold these, no matter what the
# map, the unknown-builtin default, or a policy override says. Enforced
# defensively in classify_builtins() itself (not just by omission from the
# map above), since a policy override could otherwise try to grant one.
HARD_DENIED_ORCHESTRATOR_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}

def classify_builtins(builtin_names, policy):
    """Assign observed deferred BUILT-IN tool names (non-mcp__) to agents.

    Precedence per name:
      1. policy["builtins"][name] -- explicit override, single agent, replaces
         whatever BUILTIN_TIERS says for that name.
      2. BUILTIN_TIERS -- curated default; a name may land on several agents.
      3. Unknown (observed but in neither of the above) -- granted ONLY to
         mechanic, and reported back separately so it can be surfaced in
         TOOL-ROUTING.md and reclassified via policy if desired.

    The orchestrator can NEVER end up with Edit/Write/MultiEdit/NotebookEdit/
    Bash, regardless of source -- filtered out defensively as the last step.

    Returns ({"orchestrator":[...], "scout":[...], "mechanic":[...],
    "builder":[...]}, sorted_unknown_names)."""
    overrides = policy.get("builtins", {})
    out = {"orchestrator": set(), "scout": set(), "mechanic": set(), "builder": set()}
    unknown = set()
    for name in (builtin_names or []):
        if name in overrides:
            agent = overrides[name]
            if agent in out:
                out[agent].add(name)
            continue
        agents_for_name = [a for a, names in BUILTIN_TIERS.items() if name in names]
        if agents_for_name:
            for a in agents_for_name:
                out[a].add(name)
        else:
            out["mechanic"].add(name)
            unknown.add(name)
    out["orchestrator"] -= HARD_DENIED_ORCHESTRATOR_TOOLS
    return {k: sorted(v) for k, v in out.items()}, sorted(unknown)

def generate_agents(mcp_assignment, builtin_assignment):
    """mcp_assignment: {"scout":[...], "mechanic":[...]} from assign().
    builtin_assignment: {"orchestrator":[...], "scout":[...], "mechanic":[...],
    "builder":[...]} from classify_builtins(). Both are appended onto each
    template's existing `tools:` line, skipping any name already present
    there so nothing is duplicated."""
    os.makedirs(AGENTS_DIR, exist_ok=True)
    for base in ["orchestrator","scout","mechanic","builder"]:
        tpl = os.path.join(TEMPLATES, base+".md")
        if not os.path.exists(tpl): continue
        content = open(tpl).read()
        add = list(mcp_assignment.get(base, [])) + list(builtin_assignment.get(base, []))
        m = re.search(r'^tools:(.*)$', content, flags=re.M)
        if add and m:
            existing = {s.strip() for s in m.group(1).split(",") if s.strip()}
            new_names = [n for n in add if n not in existing]
            if new_names:
                content = re.sub(r'^(tools:.*)$',
                                 lambda mm: mm.group(1).rstrip() + ", " + ", ".join(new_names),
                                 content, count=1, flags=re.M)
        open(os.path.join(AGENTS_DIR, base+".md"), "w").write(content)

def write_routing(tools, assignment, servers, needs_auth=None, builtin_assignment=None, unknown_builtins=None):
    """servers: list of {"name","status"} from parse_mcp_servers()/server_hash() --
    EVERY server `claude mcp list` reports, including ones with zero enumerated
    tools (needs-auth, still connecting, failed, or connected-but-empty). None of
    them are silently dropped from the table.
    needs_auth: needsAuthMcpServers as last recorded in the freshest session
    transcript (enumerate_transcripts) -- a second, independent needs-auth
    signal alongside the `claude mcp list` status parse, since a server can
    need auth in Claude Code's own view of the world (transcript) even when
    the CLI's status line hasn't caught up yet (or vice versa).
    builtin_assignment: {"orchestrator":[...], "scout":[...], "mechanic":[...],
    "builder":[...]} from classify_builtins() -- Claude Code's own deferred
    built-in tools (Monitor, SendMessage, Task*/Cron*, LSP, ...), separate
    from MCP tools.
    unknown_builtins: sorted names classify_builtins() couldn't match in
    BUILTIN_TIERS and fell to the mechanic-only safe default -- surfaced here
    so they can be reclassified via mcp-policy.json's "builtins" key."""
    os.makedirs(STATE_DIR, exist_ok=True)
    by_server = {}
    for t in tools:
        parts = t.get("name","").split("__")
        if len(parts) < 3: continue
        s = parts[1]; by_server.setdefault(s, {"read":0,"write":0})
        by_server[s]["read" if t.get("tier")=="read" else "write"] += 1
    lines = ["# MCP tool routing (generated by quartermaster — do not edit by hand)\n",
             "read tools -> scout · write tools -> mechanic · orchestrator delegates, holds none.\n",
             "| Server | read→scout | write→mechanic |", "|---|---|---|"]
    for s in sorted(by_server):
        lines.append(f"| {s} | {by_server[s]['read']} | {by_server[s]['write']} |")

    # Match each configured server (by display name / server id) to the tool
    # segment it produced, if any -- normalizing away spaces/dots/underscores/
    # colons so `plugin:slack:slack` matches a future `plugin_slack_slack`
    # tool-name segment the same way `claude.ai Google Drive` already matches
    # the `claude_ai_Google_Drive` segment.
    norm_to_seg = {_norm(seg): seg for seg in by_server}
    zero_tool = [s for s in servers if _norm(s["name"]) not in norm_to_seg]
    needs_auth_norm = {_norm(n) for n in (needs_auth or [])}

    if zero_tool:
        lines.append("")
        lines.append("## Configured, zero tools enumerated\n")
        lines.append("Every configured server appears here or in the table above -- "
                      "nothing is silently missing.\n")
        for s in zero_tool:
            cat = status_category(s["status"])
            transcript_needs_auth = _norm(s["name"]) in needs_auth_norm
            if cat == "needs authentication":
                why = "needs authentication; authorize via /mcp then re-run the classifier"
            elif transcript_needs_auth:
                why = ("needs authentication per session transcript; authorize via /mcp "
                       "then re-run the classifier")
            elif cat == "connecting":
                why = "still connecting; re-run the classifier once it settles"
            elif cat == "failed":
                why = "failed to connect; check its config/logs, then re-run the classifier"
            else:
                why = "no tools (connected but enumerated 0); declare a tier in mcp-policy.json if expected"
            lines.append(f"- {s['name']} — {why}.")

    # Servers currently needing authentication that ALREADY have a grant above
    # (nonzero row in the table -- e.g. transcript/cache history from back when
    # they were authorized) get a SEPARATE advisory here, rather than being
    # silently indistinguishable from a fully working server in the table.
    # Grants for these are intentionally NOT revoked/blocked: the moment the
    # user re-authenticates via /mcp, the existing grant just starts working
    # again -- no reclassification required.
    zero_tool_norm = {_norm(s["name"]) for s in zero_tool}
    stale_grant_needs_auth = [
        s for s in servers
        if _norm(s["name"]) not in zero_tool_norm
        and (status_category(s["status"]) == "needs authentication"
             or _norm(s["name"]) in needs_auth_norm)
    ]
    if stale_grant_needs_auth:
        lines.append("")
        lines.append("## Granted but currently needs authentication\n")
        lines.append("These servers have a tool grant in the table above (from cache or "
                      "session-transcript history) that is NOT revoked while unauthenticated -- "
                      "it will simply start working again once re-authenticated, with no "
                      "reclassification needed.\n")
        for s in stale_grant_needs_auth:
            lines.append(f"- {s['name']} — needs authentication; authorize via /mcp.")

    builtin_assignment = builtin_assignment or {}
    unknown_builtins = unknown_builtins or []
    lines.append("")
    lines.append("## Built-in tools\n")
    lines.append("Claude Code's own DEFERRED BUILT-IN tools (Monitor, SendMessage, "
                  "Task*/Cron*, LSP, NotebookEdit, worktree tools, ...) -- observed via "
                  "session-transcript `deferred_tools_delta` records, classified by "
                  "`BUILTIN_TIERS` (a tool may be granted to more than one agent), and "
                  "overridable per-name via mcp-policy.json's `builtins` key. The "
                  "orchestrator can never hold Edit/Write/MultiEdit/NotebookEdit/Bash, "
                  "regardless of map or override.\n")
    lines.append("| Agent | Built-in tools granted |")
    lines.append("|---|---|")
    for agent in ["orchestrator", "scout", "mechanic", "builder"]:
        names = builtin_assignment.get(agent) or []
        lines.append(f"| {agent} | {', '.join(names) if names else '(none)'} |")
    if unknown_builtins:
        lines.append("")
        lines.append("### Unknown built-ins (fell to mechanic default)\n")
        lines.append("Observed in session transcripts but not in `BUILTIN_TIERS` -- granted "
                      "ONLY to mechanic as a safe default (never auto-granted to the "
                      "orchestrator). Reclassify via `mcp-policy.json`'s `builtins` key, "
                      'e.g. `{"builtins": {"' + unknown_builtins[0] + '": "scout"}}`.\n')
        for n in unknown_builtins:
            lines.append(f"- {n}")

    open(ROUTING, "w").write("\n".join(lines) + "\n")

def main():
    policy = load_policy()
    h, servers = server_hash()
    cache = {}
    if os.path.exists(CACHE):
        try: cache = json.load(open(CACHE))
        except Exception: cache = {}

    tools = None
    needs_auth = cache.get("needs_auth", [])
    builtin_names = cache.get("builtin_names", [])  # deferred BUILT-IN tool names (non-mcp__)
    cached_tools = cache.get("tools")
    # A cache hit (unchanged hash) is only trustworthy if every server CURRENTLY
    # Connected actually has at least one tool in the cached set. Without this,
    # a cache poisoned earlier (e.g. a server enumerated as Connected before its
    # tools finished loading) would match the current hash forever and never
    # self-heal -- SessionStart would keep reusing a zero-tool grant for a
    # server that's actually fine. A server that's needs-auth/failed/connecting
    # with zero cached tools is NOT stale -- that's expected -- so this only
    # checks servers status_category()=="connected" right now.
    stale_cache = bool(cached_tools) and bool(incomplete_connected_servers(servers, cached_tools))
    if "--force" not in sys.argv and cache.get("hash") == h and cached_tools and not stale_cache:
        tools = cached_tools             # servers unchanged -> reuse (no re-enumeration)
        # builtin_names above (from cache) is reused too -- it isn't tied to
        # the MCP server hash, but re-deriving it costs nothing on a cache
        # miss and this branch is specifically the no-re-enumeration path.
    else:
        statuses = wait_for_settled()   # don't enumerate while servers are still connecting
        h, servers = server_hash(statuses)  # re-key the cache off the SETTLED status, not the
                                             # mid-connect snapshot taken before we waited -- so
                                             # the next run's hash comparison is apples-to-apples
        tools, needs_auth, builtin_names = enumerate_tools(servers)
        for _ in range(RETRY_MAX):
            if not incomplete_connected_servers(statuses, tools):
                break
            time.sleep(RETRY_WAIT)         # a connected server produced 0 tools -> it likely
            statuses = parse_mcp_servers() # connected late; re-enumerate and merge in what's new
            retry_tools, retry_needs_auth, retry_builtin_names = enumerate_tools(statuses)
            if retry_tools:
                tools = merge_tool_lists(tools, retry_tools)
            needs_auth = retry_needs_auth or needs_auth
            builtin_names = sorted(set(builtin_names) | set(retry_builtin_names))
        # Drop cached entries for servers `claude mcp list` no longer reports at
        # all (genuinely removed configs, e.g. an old transcript-era or headless-
        # era server) BEFORE handing cache_tools to merge_with_cache -- it can
        # only tell "connected server returned 0 this run" from "server isn't
        # configured anymore" if we don't feed it the latter. This is a filter
        # at the call site; merge_with_cache's own zero-clobber logic is untouched.
        configured_norm = {_norm(s["name"]) for s in servers}
        cache_tools = [t for t in (cache.get("tools") or [])
                       if _norm(tool_segment(t.get("name",""))) in configured_norm]
        tools = merge_with_cache(tools, cache_tools)  # never clobber good grants with 0
        # Built-in tool names, once observed in ANY transcript history, are
        # never tied to a specific MCP server config -- so union in whatever
        # was cached before rather than letting a re-enumeration that missed
        # scanning far enough back clobber a name seen previously.
        builtin_names = sorted(set(builtin_names) | set(cache.get("builtin_names") or []))

    # NOTE: grants for servers currently needing authentication (or otherwise
    # not reachable) are intentionally NOT stripped here -- if the server was
    # ever authorized before (cache/transcript history has real tool names for
    # it), the agent keeps that grant so it starts working again the moment
    # the user re-authenticates via /mcp, with no reclassification required.
    # write_routing still surfaces current needs-auth status as an advisory,
    # independent of whether a grant already exists.

    assignment = assign(tools, policy)
    builtin_assignment, unknown_builtins = classify_builtins(builtin_names, policy)

    if "--print" in sys.argv:
        write_routing(tools, assignment, servers, needs_auth, builtin_assignment, unknown_builtins)
        print(open(ROUTING).read()); return

    generate_agents(assignment, builtin_assignment)
    write_routing(tools, assignment, servers, needs_auth, builtin_assignment, unknown_builtins)
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"hash": h, "tools": tools, "assignment": assignment, "needs_auth": needs_auth,
               "builtin_names": builtin_names, "builtin_assignment": builtin_assignment,
               "unknown_builtins": unknown_builtins},
              open(CACHE,"w"), indent=2)
    n = sum(len(v) for v in assignment.values())
    b = sum(len(v) for v in builtin_assignment.values())
    print(f"quartermaster: {n} MCP tools classified across {len(servers)} servers "
          f"(scout {len(assignment.get('scout',[]))}, mechanic {len(assignment.get('mechanic',[]))}); "
          f"{b} built-in tool grants across orchestrator/scout/mechanic/builder "
          f"({len(unknown_builtins)} unknown -> mechanic default); "
          f"agents regenerated in {AGENTS_DIR}")

if __name__ == "__main__":
    main()
