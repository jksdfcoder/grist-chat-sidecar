from pathlib import Path
import subprocess

JS = Path(__file__).resolve().parents[1] / "static" / "ensure-chat.js"


def test_ensure_chat_plan():
    subprocess.check_call(["node", str(JS)])
