"""Core SWE-bench Live agent-run primitives: prepare a task's repo checkout,
build/reuse the sandbox agent image, run Claude Code against it (opus-solo,
or the opus-4-8 -> executor prewalk swap), and extract the resulting patch.

Sandbox pattern (DEFAULT, not an exception -- see AGENTS-facing report):
Claude Code runs as the non-root `node` user inside a
node:20-bookworm-slim + @anthropic-ai/claude-code + git/python/
build-essential container, with the task's repo checkout bind-mounted at
/workspace (checked out at base_commit). `--permission-mode bypassPermissions`
(the flag actually proven working end-to-end in the spike; equivalent in
effect to `--dangerously-skip-permissions` -- Claude Code refuses to enable
either permission-bypass mode when run as root on a bare host, which this
non-root sandboxed container satisfies) lets the run proceed unattended.

Agent configs (model pins are EXACT IDs, never floating aliases --
coordinator correction: "opus"/"sonnet"/"haiku" aliases are never used
here):
  - opus-solo: ONE `claude` process, `--model claude-opus-4-8` start to
    finish. This is the ground-truth re-baseline arm.
  - prewalk (planner/builder): `claude-opus-4-8` plans/explores until the
    FIRST successful Edit/Write/MultiEdit tool result (detected via a
    `PostToolUse` hook marker file, event-driven, not log-polling -- same
    mechanism qm_prewalk_agent.py uses, adapted here from Harbor's
    environment.exec() abstraction to plain `docker exec` since this
    harness talks to Docker directly), then the opus process is
    SIGTERM'd/SIGKILL'd and `claude --resume <session-id> --model
    <executor_model>` continues the SAME session unsupervised to
    completion. `run_prewalk`'s `executor_model` param is caller-supplied
    (run_instance.py wires it per arm: claude-sonnet-5 for prewalk-sonnet,
    claude-haiku-4-5 for prewalk-haiku) -- never hardcoded here.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_MASK_PROXY_SCRIPT = Path(__file__).resolve().parent.parent / "masking" / "mask_proxy.py"

AGENT_IMAGE = "qm-swebench-agent:latest"
AGENT_DIR = Path(__file__).resolve().parent / "agent"

DEFAULT_MAX_BUDGET_USD = 15.0
DOCKER_RUN_TIMEOUT_S = 1800  # 30 min hard ceiling per single-process run
POLL_INTERVAL_S = 1.0
POLL_EXEC_TIMEOUT_S = 15
MAX_WAIT_FOR_MARKER_S = 1800
PRE_KILL_GRACE_S = 2.0
KILL_GRACE_S = 3.0

_MARKER_PATH = "/tmp/qm_marker"
_PID_PATH = "/tmp/qm_opus.pid"
_LOG_PATH = "/meta/agent_run.jsonl"

_HOOKS_SETTINGS = {
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": (f"date +%s > {_MARKER_PATH}.tmp && mv -f {_MARKER_PATH}.tmp {_MARKER_PATH}"),
                    }
                ],
            }
        ]
    }
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


@contextlib.contextmanager
def _api_key_env_file(api_key: str, extra_lines: dict[str, str] | None = None):
    """Write ANTHROPIC_API_KEY (plus any `extra_lines`, e.g.
    ANTHROPIC_BASE_URL for the masking-proxy arm) to a 0600 temp file and
    pass it to `docker run`/`docker exec` via --env-file, so the key never
    appears as a literal CLI argument (visible in `ps`/process listings) --
    only inside the file, and inside the container's own env (which the
    container legitimately needs to run the agent)."""
    fd, path_str = tempfile.mkstemp(prefix="qm-swebench-envfile-")
    path = Path(path_str)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as f:
            f.write(f"ANTHROPIC_API_KEY={api_key}\n")
            for k, v in (extra_lines or {}).items():
                f.write(f"{k}={v}\n")
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextlib.contextmanager
def _mask_proxy(
    meta_dir: Path,
    target_model: str,
    mask_enabled: bool,
    keep_n: int,
    port: int,
    mode: str = "cap",
    cap_chars: int = 16000,
):
    """Run the observation-transform egress proxy on the host for the duration
    of one agent run. The sandbox reaches it via host.docker.internal:<port>
    (ANTHROPIC_BASE_URL). Per-request stats are written to
    meta_dir/mask_stats.jsonl. mode="cap" is the deterministic whale-capping
    transform (cache-safe); mode="window" is the F2 sliding mask (kept for the
    record); mask_enabled=False is a byte-identical pass-through control.
    Cap-mode overflow files go to meta_dir/obs, which the sandbox sees at
    /meta/obs (meta_dir is bind-mounted at /meta)."""
    stats_path = meta_dir / "mask_stats.jsonl"
    overflow_dir = meta_dir / "obs"
    env = os.environ.copy()
    env.update(
        {
            "MASK_PORT": str(port),
            "MASK_HOST": "0.0.0.0",
            "MASK_ENABLED": "1" if mask_enabled else "0",
            "MASK_MODE": mode,
            "MASK_KEEP_N": str(keep_n),
            "MASK_CAP_CHARS": str(cap_chars),
            # keep head+tail comfortably under the cap threshold at any setting
            "MASK_HEAD_CHARS": str(cap_chars // 2),
            "MASK_TAIL_CHARS": str(cap_chars // 4),
            "MASK_OVERFLOW_DIR": str(overflow_dir),
            "MASK_OVERFLOW_MOUNT": "/meta/obs",
            "MASK_TARGET_MODEL": target_model,
            "MASK_STATS": str(stats_path),
        }
    )
    proc = subprocess.Popen(
        [sys.executable, str(_MASK_PROXY_SCRIPT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait until the proxy is accepting connections (or give up after ~10s).
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError(f"mask proxy did not come up on port {port}")
    try:
        yield stats_path
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _summarize_mask_stats(stats_path: Path, mask_enabled: bool, keep_n: int) -> dict[str, Any]:
    """Aggregate the per-request masking stats for one run into the result."""
    n_requests = n_masked_events = max_tool_results = 0
    n_requests_with_masking = 0
    try:
        for line in stats_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            n_requests += 1
            n_masked_events += int(r.get("masked", 0) or 0)
            max_tool_results = max(max_tool_results, int(r.get("total_tool_results", 0) or 0))
            if r.get("applied"):
                n_requests_with_masking += 1
    except (OSError, ValueError):
        pass
    return {
        "mask_enabled": mask_enabled,
        "keep_n": keep_n,
        "proxy_requests_targeted": n_requests,
        "requests_with_masking": n_requests_with_masking,
        "masked_block_events": n_masked_events,
        "max_tool_results_in_a_turn": max_tool_results,
    }


# ---------------------------------------------------------------------------
# Repo checkout + image build
# ---------------------------------------------------------------------------


def prepare_repo(instance: dict[str, Any], dest: Path, timeout_s: int = 600) -> Path:
    """Full clone of the instance's GitHub repo, checked out at base_commit.
    (Gotcha #1's `git submodule update --init --recursive` is for the
    vendored SWE-bench-Live/RepoLaunch checkout, a separate concern from
    this per-instance TASK repo clone.)"""
    if dest.exists():
        log(f"REPO_REUSE {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    repo_url = f"https://github.com/{instance['repo']}.git"
    log(f"REPO_CLONE {repo_url} -> {dest}")
    subprocess.run(["git", "clone", "--quiet", repo_url, str(dest)], check=True, timeout=timeout_s)
    subprocess.run(
        ["git", "checkout", "--quiet", instance["base_commit"]],
        cwd=dest,
        check=True,
        timeout=timeout_s,
    )
    return dest


def build_agent_image(tag: str = AGENT_IMAGE, dockerfile_dir: Path = AGENT_DIR) -> None:
    log(f"IMAGE_BUILD tag={tag} dir={dockerfile_dir}")
    subprocess.run(
        ["docker", "build", "-t", tag, "-f", str(dockerfile_dir / "Dockerfile.agent"), str(dockerfile_dir)],
        check=True,
    )
    log(f"IMAGE_BUILD_OK tag={tag}")


def image_built(tag: str = AGENT_IMAGE) -> bool:
    # timeout guard: a wedged Docker daemon otherwise blocks this call forever
    # (observed 2026-07-21: powered campaign hung ~3h on `docker image inspect`
    # after Docker Desktop locked up mid-campaign).
    proc = subprocess.run(
        ["docker", "image", "inspect", tag], capture_output=True, text=True, timeout=60
    )
    return proc.returncode == 0


def ensure_agent_image(tag: str = AGENT_IMAGE, dockerfile_dir: Path = AGENT_DIR) -> None:
    if image_built(tag):
        log(f"IMAGE_OK tag={tag} (already built)")
        return
    build_agent_image(tag, dockerfile_dir)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def render_prompt(instance: dict[str, Any]) -> str:
    return (
        f"You are working in a checkout of the {instance['repo']} repository "
        f"at commit {instance['base_commit']}.\n\n"
        "A user has filed the following issue. Resolve it by editing the "
        "repository's source code. Do not modify any test files. Make the "
        "smallest reasonable change to fix the root cause.\n\n"
        "--- ISSUE ---\n"
        f"{instance['problem_statement']}\n"
        "--- END ISSUE ---\n\n"
        "When you are done, stop. Do not run git commit."
    )


# ---------------------------------------------------------------------------
# docker helpers
# ---------------------------------------------------------------------------


def _docker_run_detached(name: str, repo_path: Path, meta_dir: Path, env_file: Path, image: str) -> None:
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-u",
            "node",
            "-v",
            f"{repo_path}:/workspace",
            "-v",
            f"{meta_dir}:/meta",
            "--env-file",
            str(env_file),
            image,
            "sleep",
            "infinity",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _docker_exec(
    name: str, command: str, env_file: Path, timeout_s: int | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", "--env-file", str(env_file), name, "bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def _docker_rm(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------------------
# opus-solo arm
# ---------------------------------------------------------------------------


def run_opus_solo(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-8",
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = AGENT_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
    base_url: str | None = None,
    arm_label: str = "opus-solo",
    extra_env: dict[str, str] | None = None,
    pre_cmd: str | None = None,
) -> dict[str, Any]:
    """Single-process agent run. When `base_url` is set (the masking arm),
    the container is pointed at the host masking proxy via ANTHROPIC_BASE_URL
    and reaches it through host.docker.internal; otherwise it talks to the API
    directly (the plain opus-solo baseline). `extra_env` adds further env
    vars to the sandbox (e.g. MAX_THINKING_TOKENS for the tuned arm)."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    prompt = render_prompt(instance)
    log_path = meta_dir / "agent_run.jsonl"
    err_path = meta_dir / "agent_run.stderr.log"

    inner_cmd = shlex.join(
        [
            "claude",
            "--verbose",
            "--output-format=stream-json",
            "--max-budget-usd",
            str(max_budget_usd),
            "--model",
            model,
            "--permission-mode",
            "bypassPermissions",
            "--print",
            "--",
            prompt,
        ]
    )
    full_cmd = f"{inner_cmd} > /meta/agent_run.jsonl 2> /meta/agent_run.stderr.log"
    if pre_cmd:
        full_cmd = f"{pre_cmd} && {full_cmd}"

    env_lines = dict(extra_env or {})
    if base_url:
        env_lines["ANTHROPIC_BASE_URL"] = base_url
    # host.docker.internal is automatic on Docker Desktop (macOS); the explicit
    # host-gateway mapping makes the proxy reachable on Linux too.
    host_args = ["--add-host", "host.docker.internal:host-gateway"] if base_url else []

    t0 = time.time()
    status = "ok"
    error_detail = None
    try:
        with _api_key_env_file(api_key, env_lines or None) as env_file:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-u",
                    "node",
                    *host_args,
                    "-v",
                    f"{repo_path}:/workspace",
                    "-v",
                    f"{meta_dir}:/meta",
                    "--env-file",
                    str(env_file),
                    image,
                    "bash",
                    "-lc",
                    full_cmd,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
    except subprocess.TimeoutExpired:
        status = "errored"
        error_detail = f"docker run timed out after {timeout_s}s"
    except subprocess.CalledProcessError as exc:
        status = "errored"
        error_detail = f"docker run exit={exc.returncode} stderr_tail={(exc.stderr or '')[-2000:]}"

    wall_clock_s = round(time.time() - t0, 2)
    return {
        "status": status,
        "error_detail": error_detail,
        "wall_clock_s": wall_clock_s,
        "log_path": str(log_path),
        "stderr_path": str(err_path),
        "arm": arm_label,
        "planner_model": model,
        "executor_model": None,
        "swap_fired": False,
    }


# Round-3 Arm A (PREREG_ROUND3.md): output-token tuning via repo instructions
# + thinking-budget cap. The instruction text is a FIXED constant: identical
# in every run and every request (it enters the context once at session start
# via the auto-loaded /workspace/CLAUDE.md), so it is cache-stable. It is
# written as an UNTRACKED file, and extract_patch uses `git diff` (tracked
# only), so it can never leak into the evaluated patch.
EFFICIENCY_CLAUDE_MD = """\
# Working style for this repository

- Be maximally concise. No preamble, no narration of what you are about to
  do, no summaries of what you just did. Never restate file contents you
  just read.
- Read the MINIMUM needed: use grep/targeted searches first; read full files
  only for the file you are about to edit. Batch independent
  reads/greps/searches into a single message wherever possible.
- Make the smallest change that fixes the root cause. Prefer surgical edits
  over rewrites. Do not refactor, reformat, or improve unrelated code.
- Do not re-read files you have already seen unless they changed.
- When done, stop immediately. Do not write a closing summary.
"""


# Vehicle re-bench (PREREG_VEHICLE.md): the SHIPPED delivery of the certified
# output tuning — SessionStart-hook additionalContext injection (as the v0.9.0
# plugin does) + MAX_THINKING_TOKENS env — with NO repo CLAUDE.md. Tests
# whether the shipped vehicle reproduces the certified effect (which was
# measured with the block delivered via repo CLAUDE.md).
_VEHICLE_INJECT_PY = """\
import json

block = open("/meta/tuning_block.md").read()
print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": block,
            }
        }
    )
)
"""

_VEHICLE_SETTINGS = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": "python3 /meta/inject_tuning.py"}],
            }
        ]
    }
}


def run_opus_shipped(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-8",
    max_thinking_tokens: int = 8000,
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = AGENT_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """Certified output tuning delivered exactly as the v0.9.0 plugin ships
    it: identical instruction text, injected via SessionStart-hook
    additionalContext; thinking cap via env; NO repo CLAUDE.md."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    claude_md = repo_path / "CLAUDE.md"
    claude_md.unlink(missing_ok=True)  # the point: no repo-file delivery
    (meta_dir / "tuning_block.md").write_text(EFFICIENCY_CLAUDE_MD)
    (meta_dir / "inject_tuning.py").write_text(_VEHICLE_INJECT_PY)
    settings_json = json.dumps(_VEHICLE_SETTINGS)
    pre_cmd = (
        "mkdir -p $HOME/.claude && "
        f"echo {shlex.quote(settings_json)} > $HOME/.claude/settings.json"
    )
    result = run_opus_solo(
        instance,
        repo_path,
        meta_dir,
        api_key,
        model=model,
        max_budget_usd=max_budget_usd,
        image=image,
        timeout_s=timeout_s,
        arm_label="opus-shipped",
        extra_env={"MAX_THINKING_TOKENS": str(max_thinking_tokens)},
        pre_cmd=pre_cmd,
    )
    result["tuning"] = {"vehicle": "sessionstart-hook", "max_thinking_tokens": max_thinking_tokens}
    return result


# Round-3 Arm B (PREREG_ROUST.md): roust-only code retrieval. The agent must
# use the roust binary for content search; the Grep tool and grep-family Bash
# commands are DENIED by a PreToolUse hook (instruction-only routing measures
# ~60% compliance — context-mode's own data — so we enforce). Instructions
# follow roust's README-recommended CLAUDE.md block, adapted for the hard
# block (the README's "fall back to grep" line is inapplicable here).
ROUST_IMAGE = "qm-swebench-agent-roust:latest"

ROUST_CLAUDE_MD = """\
# Code search in this repository

grep/rg and the Grep tool are DISABLED in this environment. Use `roust` for
all content search — it returns one ranked, token-budgeted bundle of the
relevant code per query:

- `roust "<question or issue text>" --files-only` to localize which files
  are relevant.
- `roust "<question or issue text>"` to get a packed bundle of the actual
  relevant code, ready to read.

Pass the raw question or issue text as the query — don't summarize or clean
it up first. Include error messages, stack traces, file paths, and
backtick-quoted symbol/function names verbatim; roust uses those as
high-precision anchors. Reading specific files you already know about
(Read tool, file paths) is fine; discovering code goes through roust.
"""

_DENY_GREP_HOOK = """\
import json
import re
import sys

d = json.load(sys.stdin)
tool = d.get("tool_name", "")
cmd = (d.get("tool_input") or {}).get("command", "")
deny = tool == "Grep" or (
    tool == "Bash" and re.search(r"(^|[|;&\\s(])(grep|egrep|fgrep|rg|ag|ack)\\b", cmd)
)
if deny:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "grep-family search is disabled in this environment. "
                        'Use roust instead: roust "<question or issue text>" '
                        "[--files-only]  (see CLAUDE.md)"
                    ),
                }
            }
        )
    )
"""

_ROUST_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash|Grep",
                "hooks": [{"type": "command", "command": "python3 /meta/deny_grep.py"}],
            }
        ]
    }
}


def run_opus_roust(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-8",
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = ROUST_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """opus-solo scaffold + roust-only retrieval: roust binary in the image,
    usage instructions via untracked CLAUDE.md, grep-family denied by a
    PreToolUse hook (settings.json written before launch)."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    (repo_path / "CLAUDE.md").write_text(ROUST_CLAUDE_MD)
    (meta_dir / "deny_grep.py").write_text(_DENY_GREP_HOOK)
    settings_json = json.dumps(_ROUST_SETTINGS)
    pre_cmd = (
        "mkdir -p $HOME/.claude && "
        f"echo {shlex.quote(settings_json)} > $HOME/.claude/settings.json"
    )
    result = run_opus_solo(
        instance,
        repo_path,
        meta_dir,
        api_key,
        model=model,
        max_budget_usd=max_budget_usd,
        image=image,
        timeout_s=timeout_s,
        arm_label="opus-roust",
        pre_cmd=pre_cmd,
    )
    result["roust"] = {"image": image, "grep_denied": True}
    return result


def run_opus_tuned(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-8",
    max_thinking_tokens: int = 8000,
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = AGENT_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """opus-solo scaffold + output-token tuning: a fixed efficiency CLAUDE.md
    dropped (untracked) into the task repo, plus MAX_THINKING_TOKENS capped
    via the env-file. No proxy, no context mutation — pure output-side lever."""
    (repo_path / "CLAUDE.md").write_text(EFFICIENCY_CLAUDE_MD)
    result = run_opus_solo(
        instance,
        repo_path,
        meta_dir,
        api_key,
        model=model,
        max_budget_usd=max_budget_usd,
        image=image,
        timeout_s=timeout_s,
        arm_label="opus-tuned",
        extra_env={"MAX_THINKING_TOKENS": str(max_thinking_tokens)},
    )
    result["tuning"] = {"claude_md": True, "max_thinking_tokens": max_thinking_tokens}
    return result


def run_opus_masked(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    model: str = "claude-opus-4-8",
    keep_n: int = 3,
    mask_enabled: bool = True,
    mode: str = "cap",
    cap_chars: int = 16000,
    arm_label: str | None = None,
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = AGENT_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
    port: int = 8788,
) -> dict[str, Any]:
    """opus-solo scaffold with an observation transform applied by a host
    egress proxy on ANTHROPIC_BASE_URL. mode="cap" = deterministic
    whale-capping (cache-safe); mode="window" = F2 sliding mask (record only);
    mask_enabled=False runs the identical proxy path in pass-through mode
    (the parity control)."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    if arm_label is None:
        arm_label = ("opus-capped" if mode == "cap" else "opus-masked") if mask_enabled else "opus-passthru"
    with _mask_proxy(meta_dir, model, mask_enabled, keep_n, port, mode=mode, cap_chars=cap_chars) as stats_path:
        result = run_opus_solo(
            instance,
            repo_path,
            meta_dir,
            api_key,
            model=model,
            max_budget_usd=max_budget_usd,
            image=image,
            timeout_s=timeout_s,
            base_url=f"http://host.docker.internal:{port}",
            arm_label=arm_label,
        )
    result["masking"] = {"mode": mode, "cap_chars": cap_chars, **_summarize_mask_stats(stats_path, mask_enabled, keep_n)}
    return result


# ---------------------------------------------------------------------------
# prewalk (opus-4-8 -> sonnet-5) arm
# ---------------------------------------------------------------------------


def _poll_marker(name: str, env_file: Path) -> tuple[bool, str | None, int | None]:
    start = time.monotonic()
    check_cmd = (
        f"if [ -f {_MARKER_PATH} ]; then echo \"FOUND $(cat {_MARKER_PATH} 2>/dev/null)\"; "
        f"else echo PENDING; fi; echo '---QM-ALIVE---'; "
        f'PID=$(cat {_PID_PATH} 2>/dev/null); '
        f'if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then echo ALIVE; else echo DEAD; fi'
    )
    while True:
        try:
            proc = _docker_exec(name, check_cmd, env_file, timeout_s=POLL_EXEC_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            if time.monotonic() - start > MAX_WAIT_FOR_MARKER_S:
                return False, "marker_wait_timeout", None
            continue

        stdout = proc.stdout or ""
        marker_part, _, alive_part = stdout.partition("---QM-ALIVE---")
        marker_line = marker_part.strip()
        proc_alive = "ALIVE" in alive_part

        if marker_line.startswith("FOUND"):
            epoch_str = marker_line[len("FOUND") :].strip()
            marker_epoch = int(epoch_str) if epoch_str.isdigit() else None
            return True, None, marker_epoch
        if not proc_alive:
            return False, "opus_completed_without_edit", None
        if time.monotonic() - start > MAX_WAIT_FOR_MARKER_S:
            return False, "marker_wait_timeout", None
        time.sleep(POLL_INTERVAL_S)


def run_prewalk(
    instance: dict[str, Any],
    repo_path: Path,
    meta_dir: Path,
    api_key: str,
    planner_model: str = "claude-opus-4-8",
    executor_model: str = "claude-sonnet-5",
    max_budget_usd: float = DEFAULT_MAX_BUDGET_USD,
    image: str = AGENT_IMAGE,
    timeout_s: int = DOCKER_RUN_TIMEOUT_S,
) -> dict[str, Any]:
    meta_dir.mkdir(parents=True, exist_ok=True)
    prompt = render_prompt(instance)
    session_id = str(uuid.uuid4())
    container_name = f"qm-swebench-prewalk-{uuid.uuid4().hex[:10]}"
    log_path = meta_dir / "agent_run.jsonl"

    t0 = time.time()
    status = "ok"
    error_detail = None
    swap_fired = False
    never_swapped_reason = None
    marker_epoch: int | None = None

    try:
        with _api_key_env_file(api_key) as env_file:
            _docker_run_detached(container_name, repo_path, meta_dir, env_file, image)

            hooks_json = json.dumps(_HOOKS_SETTINGS)
            setup_cmd = (
                "mkdir -p $HOME/.claude && "
                f"rm -f {_MARKER_PATH} {_MARKER_PATH}.tmp && "
                f"echo {shlex.quote(hooks_json)} > $HOME/.claude/settings.json"
            )
            _docker_exec(container_name, setup_cmd, env_file, timeout_s=60)

            launch_inner = shlex.join(
                [
                    "claude",
                    "--verbose",
                    "--output-format=stream-json",
                    "--max-budget-usd",
                    str(max_budget_usd),
                    "--model",
                    planner_model,
                    "--session-id",
                    session_id,
                    "--permission-mode",
                    "bypassPermissions",
                    "--print",
                    "--",
                    prompt,
                ]
            )
            launch_cmd = f"nohup {launch_inner} > {_LOG_PATH} 2>&1 < /dev/null & echo $! > {_PID_PATH}"
            _docker_exec(container_name, launch_cmd, env_file, timeout_s=30)

            swap_fired, never_swapped_reason, marker_epoch = _poll_marker(container_name, env_file)

            if swap_fired:
                time.sleep(PRE_KILL_GRACE_S)
                kill_cmd = (
                    f'PID=$(cat {_PID_PATH} 2>/dev/null); '
                    f'if [ -n "$PID" ]; then kill -TERM "$PID" 2>/dev/null || true; fi; '
                    f"sleep {KILL_GRACE_S}; "
                    f'if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then kill -KILL "$PID" 2>/dev/null || true; sleep 1; fi'
                )
                _docker_exec(container_name, kill_cmd, env_file, timeout_s=30)

                nudge = (
                    "Continue the task exactly where you left off, using the existing "
                    "conversation and tool results as your context. Keep working "
                    "autonomously until the task is fully complete -- do not ask for "
                    "confirmation or restate the plan, just finish it. When you are "
                    "done, stop. Do not run git commit."
                )
                resume_inner = shlex.join(
                    [
                        "claude",
                        "--verbose",
                        "--output-format=stream-json",
                        "--max-budget-usd",
                        str(max_budget_usd),
                        "--model",
                        executor_model,
                        "--resume",
                        session_id,
                        "--permission-mode",
                        "bypassPermissions",
                        "--print",
                        "--",
                        nudge,
                    ]
                )
                resume_cmd = f"{resume_inner} >> {_LOG_PATH} 2>&1 < /dev/null"
                resume_proc = _docker_exec(container_name, resume_cmd, env_file, timeout_s=timeout_s)
                if resume_proc.returncode != 0:
                    status = "errored"
                    error_detail = (
                        f"resume exec exit={resume_proc.returncode} "
                        f"stderr_tail={(resume_proc.stderr or '')[-2000:]}"
                    )
            else:
                time.sleep(1.0)

    except subprocess.TimeoutExpired:
        status = "errored"
        error_detail = f"prewalk run timed out after {timeout_s}s"
    except subprocess.CalledProcessError as exc:
        status = "errored"
        error_detail = f"docker exit={exc.returncode} stderr_tail={(exc.stderr or '')[-2000:]}"
    finally:
        _docker_rm(container_name)

    wall_clock_s = round(time.time() - t0, 2)
    return {
        "status": status,
        "error_detail": error_detail,
        "wall_clock_s": wall_clock_s,
        "log_path": str(log_path),
        "arm": "prewalk",
        "planner_model": planner_model,
        "executor_model": executor_model,
        "swap_fired": swap_fired,
        "never_swapped_reason": never_swapped_reason,
        "marker_epoch": marker_epoch,
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# Patch extraction
# ---------------------------------------------------------------------------


def extract_patch(repo_path: Path) -> str:
    proc = subprocess.run(
        ["git", "diff", "--no-color"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout
