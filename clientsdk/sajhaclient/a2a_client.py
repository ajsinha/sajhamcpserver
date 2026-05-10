"""
SAJHA MCP Server — Client SDK A2A (Agent-to-Agent) Protocol Client

Implements Google's A2A protocol for agent-to-agent communication.
See: https://google.github.io/A2A/

    from sajhaclient import SajhaConfig
    from sajhaclient.a2a_client import A2AClient

    config = SajhaConfig(base_url="http://localhost:3002")
    a2a = A2AClient(config)

    # Discover agent capabilities
    card = a2a.get_agent_card()
    print(f"Agent: {card['name']} with {len(card['skills'])} skills")

    # Send a task
    task = a2a.send_task("Analyze the latest AAPL earnings report")
    print(f"Task {task['id']}: {task['status']['state']}")

    # Check status
    status = a2a.get_task(task['id'])
"""

import json
import urllib.request
import logging
from typing import Optional, Dict, Any, List

from sajhaclient.config import SajhaConfig
from sajhaclient.auth import AuthProvider, NoAuth, ApiKeyAuth, JWTAuth
from sajhaclient.exceptions import SajhaA2AError, SajhaConnectionError

logger = logging.getLogger(__name__)


class A2AClient:
    """
    A2A (Agent-to-Agent) protocol client.

    Enables inter-agent communication using Google's A2A spec.
    Supports task submission, status tracking, and cancellation.
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        self.config = config or SajhaConfig()
        self._auth = auth

        if not self._auth:
            if self.config.api_key:
                self._auth = ApiKeyAuth(self.config.api_key)
            elif self.config.username and self.config.password:
                self._auth = JWTAuth(self.config.base_url, self.config.username, self.config.password)
            else:
                self._auth = NoAuth()

        self._request_id = 0
        self._agent_card: Optional[Dict] = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc(self, method: str, params: Dict) -> Any:
        """Send an A2A JSON-RPC 2.0 request."""
        self._auth.refresh_if_needed()

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }).encode('utf-8')

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'sajhaclient-a2a/3.0.0',
            **self._auth.get_headers(),
        }

        try:
            req = urllib.request.Request(self.config.a2a_url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                response = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise SajhaA2AError(f"A2A request failed ({e.code}): {e.read().decode()}")
        except urllib.error.URLError as e:
            raise SajhaConnectionError(f"Cannot connect: {e.reason}")

        if 'error' in response:
            err = response['error']
            raise SajhaA2AError(f"A2A error {err.get('code')}: {err.get('message')}")

        return response.get('result')

    # ── Agent Discovery ──────────────────────────────────────────

    def get_agent_card(self) -> Dict:
        """
        Fetch the agent card (/.well-known/agent.json).

        Returns agent name, description, capabilities, skills, and auth schemes.
        Use this to discover what the agent can do before sending tasks.
        """
        headers = {
            'Accept': 'application/json',
            **self._auth.get_headers(),
        }
        try:
            req = urllib.request.Request(self.config.agent_card_url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                self._agent_card = json.loads(resp.read().decode('utf-8'))
                return self._agent_card
        except Exception as e:
            raise SajhaA2AError(f"Failed to fetch agent card: {e}")

    def list_skills(self) -> List[Dict]:
        """Get the agent's skill list (fetches agent card if needed)."""
        if not self._agent_card:
            self.get_agent_card()
        return self._agent_card.get('skills', [])

    # ── Task Lifecycle ───────────────────────────────────────────

    def send_task(self, text: str, session_id: Optional[str] = None,
                  metadata: Optional[Dict] = None) -> Dict:
        """
        Send a task to the agent.

        Args:
            text: Task description / instruction in natural language
            session_id: Optional session ID for multi-turn conversations
            metadata: Optional metadata dict

        Returns:
            Task result with id, status, and artifacts

        Example:
            task = a2a.send_task("Get the current stock price of AAPL")
            print(task['status']['state'])  # 'completed'
            print(task['artifacts'])         # result data
        """
        params = {
            'message': {
                'parts': [{'type': 'text', 'text': text}],
            }
        }
        if session_id:
            params['sessionId'] = session_id
        if metadata:
            params['metadata'] = metadata

        return self._rpc('tasks/send', params)

    def get_task(self, task_id: str) -> Dict:
        """
        Get the current status and result of a task.

        Args:
            task_id: The task ID returned by send_task()

        Returns:
            Task object with id, status, artifacts
        """
        return self._rpc('tasks/get', {'id': task_id})

    def cancel_task(self, task_id: str) -> Dict:
        """
        Cancel a running task.

        Args:
            task_id: The task ID to cancel

        Returns:
            Updated task object with cancelled state
        """
        return self._rpc('tasks/cancel', {'id': task_id})

    # ── Convenience ──────────────────────────────────────────────

    def send_and_wait(self, text: str, timeout: int = 60,
                      poll_interval: float = 1.0) -> Dict:
        """
        Send a task and wait for completion.

        Args:
            text: Task instruction
            timeout: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Completed task result

        Raises:
            SajhaA2AError: If task fails or times out
        """
        import time

        task = self.send_task(text)
        task_id = task['id']
        state = task.get('status', {}).get('state', '')

        if state in ('completed', 'failed', 'cancelled'):
            return task

        start = time.time()
        while time.time() - start < timeout:
            time.sleep(poll_interval)
            task = self.get_task(task_id)
            state = task.get('status', {}).get('state', '')
            if state in ('completed', 'failed', 'cancelled'):
                if state == 'failed':
                    msg = task.get('status', {}).get('message', {})
                    raise SajhaA2AError(f"Task failed: {msg}")
                return task

        raise SajhaA2AError(f"Task {task_id} timed out after {timeout}s (state: {state})")
