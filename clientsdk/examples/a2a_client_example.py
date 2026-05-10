#!/usr/bin/env python3
"""
Example: SAJHA A2A (Agent-to-Agent) Protocol Client

Use this when building an AI agent that needs to delegate tasks
to SAJHA as another agent in a multi-agent system.
"""

from sajhaclient import SajhaConfig
from sajhaclient.a2a_client import A2AClient

# ── Connect ──────────────────────────────────────────────────────
config = SajhaConfig(base_url="http://localhost:3002")
a2a = A2AClient(config)

# ── Discover Agent ───────────────────────────────────────────────
card = a2a.get_agent_card()
print(f"Agent: {card['name']}")
print(f"Description: {card['description']}")
print(f"Capabilities: {card['capabilities']}")
print(f"Auth schemes: {card['authentication']['schemes']}")
print(f"Skills: {len(card['skills'])}")
for skill in card['skills'][:5]:
    print(f"  • {skill['id']}: {skill['description'][:50]}")

# ── Send a Task ──────────────────────────────────────────────────
print("\n--- Sending task ---")
task = a2a.send_task("Get the company profile for Apple (AAPL)")
print(f"Task ID: {task['id']}")
print(f"State: {task['status']['state']}")
if 'artifacts' in task:
    print(f"Artifacts: {len(task['artifacts'])} items")

# ── Check Task Status ────────────────────────────────────────────
status = a2a.get_task(task['id'])
print(f"\nTask status: {status['status']['state']}")

# ── Send and Wait (blocking) ────────────────────────────────────
print("\n--- Send and wait ---")
result = a2a.send_and_wait("What tools are available?", timeout=30)
print(f"State: {result['status']['state']}")
if 'artifacts' in result:
    for art in result['artifacts']:
        for part in art.get('parts', []):
            if part.get('type') == 'text':
                print(f"Response: {part['text'][:200]}")

# ── Multi-turn Session ───────────────────────────────────────────
print("\n--- Multi-turn session ---")
session = "session-001"
a2a.send_task("Remember: I'm interested in tech stocks", session_id=session)
task2 = a2a.send_task("Now get me the latest NVDA quote", session_id=session)
print(f"Session task: {task2['status']['state']}")
