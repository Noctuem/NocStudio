"""A stand-in for `claude -p` in stream-json mode, for the self-test: it asks to run one command, then answers.
Asked to stop, it ends the turn as Claude Code does; `-p /usage` prints a usage reading."""
import json
import sys
import uuid

if "/usage" in sys.argv:
    print(json.dumps({"type": "result", "subtype": "success", "local_command": "usage", "total_cost_usd": 0,
                      "result": "You are currently using your subscription\n\nCurrent session: 12% used · resets 3pm\n"
                                "Current week (all models): 40% used · resets Nov 6, 8am (America/Chicago)\n\nLast 24h · 9 requests"}))
    sys.exit(0)

sid = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else str(uuid.uuid4())


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


out({"type": "system", "subtype": "init", "session_id": sid})
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("type") == "user":
        said = msg["message"]["content"][0]["text"]
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "make thing"}}]}})
        out({"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "Bash",
             "input": {"command": "make thing"}, "description": "Make the thing"}})
    elif msg.get("type") == "control_request" and msg["request"].get("subtype") == "interrupt":
        out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"]}})
        out({"type": "result", "subtype": "error_during_execution", "session_id": sid})
    elif msg.get("type") == "control_response":
        allowed = msg["response"]["response"]["behavior"] == "allow"
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": ("made it: " if allowed else "did not: ") + said}]}})
        out({"type": "result", "subtype": "success", "session_id": sid})
