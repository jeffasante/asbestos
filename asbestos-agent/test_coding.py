#!/usr/bin/env python3
"""
test_coding.py — Send a coding task to the Asbestos Agent and stream the response.
Usage: python3 test_coding.py
"""

import httpx
import json

AGENT_URL = "http://127.0.0.1:8765/v1/chat/completions"

PROMPT = """\
Write a Python function called `parse_log_file(path: str) -> list[dict]` that:
1. Reads a log file line by line
2. Each line has the format: [LEVEL] TIMESTAMP: MESSAGE
   Example: [ERROR] 2024-03-05T10:22:01: Disk failure on /dev/sda
3. Returns a list of dicts with keys: level, timestamp, message
4. Skips malformed lines gracefully
5. Include a usage example at the bottom

Then save the function to ~/asbestos_knowledge/log_parser.py
"""

def main():
    print("→ Sending coding task to Asbestos...\n")
    print("─" * 60)

    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            AGENT_URL,
            json={
                "model": "asbestos-local",
                "messages": [{"role": "user", "content": PROMPT}],
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            pending_event = None

            for line in response.iter_lines():
                if line.startswith("event: "):
                    pending_event = line[7:].strip()
                    continue

                if not line.startswith("data: "):
                    pending_event = None
                    continue

                payload = line[6:].strip()
                if payload == "[DONE]":
                    break

                try:
                    chunk = json.loads(payload)

                    if pending_event == "confirmation":
                        conf_id = chunk.get("id", "")
                        print(f"\n⏳ CONFIRMATION NEEDED (id={conf_id})")
                        print(chunk.get("message", ""))
                        answer = input("\nType 'yes' to confirm, anything else to skip: ").strip()
                        if answer.lower() == "yes":
                            r = httpx.post(
                                f"http://127.0.0.1:8765/confirm/{conf_id}",
                                timeout=30,
                            )
                            result = r.json()
                            if result.get("status") == "ok":
                                print(f"✓ Saved to {result.get('path')} ({result.get('bytes_written')} bytes)")
                            else:
                                print(f"✗ Error: {result}")
                        pending_event = None
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        print(delta, end="", flush=True)

                except json.JSONDecodeError:
                    pass

                pending_event = None

    print("\n" + "─" * 60)
    print("✓ Done.")


if __name__ == "__main__":
    main()
