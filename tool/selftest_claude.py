"""A stand-in for `claude -p` in stream-json mode, for the self-test: it asks to run one command, then answers."""
import json
import sys
import uuid

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
    elif msg.get("type") == "control_response":
        allowed = msg["response"]["response"]["behavior"] == "allow"
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": ("made it: " if allowed else "did not: ") + said}]}})
        out({"type": "result", "subtype": "success", "session_id": sid})
