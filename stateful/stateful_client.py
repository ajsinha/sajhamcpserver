"""
Example client demonstrating stateful MCP with SSE
"""
import requests
import json
import time
import threading
from typing import Callable, Dict, Any
import sseclient  # pip install sseclient-py


class MCPStatefulClient:
    """Client for interacting with stateful MCP tools"""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.session_id = None
        self.sse_thread = None
        self.sse_running = False
        
        # Authenticate
        self.login()
    
    def login(self):
        """Authenticate and get JWT tokens"""
        url = f"{self.base_url}/api/auth/login"
        response = requests.post(url, json={
            'username': self.username,
            'password': self.password
        })
        response.raise_for_status()
        
        data = response.json()
        self.access_token = data['access_token']
        self.refresh_token = data['refresh_token']
        print(f"✓ Authenticated as {data['user']['full_name']}")
    
    def _get_headers(self):
        """Get headers with JWT token"""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def create_session(self, tool_name: str, initial_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a new stateful session"""
        url = f"{self.base_url}/api/tool/{tool_name}/session/create"
        response = requests.post(
            url,
            headers=self._get_headers(),
            json={'initial_state': initial_state or {}}
        )
        response.raise_for_status()
        
        data = response.json()
        self.session_id = data['session_id']
        print(f"✓ Session created: {self.session_id[:8]}...")
        print(f"  SSE enabled: {data.get('sse_enabled', False)}")
        print(f"  Push enabled: {data.get('push_enabled', False)}")
        return data
    
    def get_session_state(self, tool_name: str) -> Dict[str, Any]:
        """Get current session state"""
        if not self.session_id:
            raise ValueError("No active session")
        
        url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}/state"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()
    
    def set_session_state(self, tool_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Update session state"""
        if not self.session_id:
            raise ValueError("No active session")
        
        url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}/state"
        response = requests.put(
            url,
            headers=self._get_headers(),
            json={'state': state}
        )
        response.raise_for_status()
        return response.json()
    
    def call_tool(self, tool_name: str, method: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Call a tool method"""
        url = f"{self.base_url}/api/tool/{tool_name}/callapi"
        response = requests.post(
            url,
            headers=self._get_headers(),
            json={
                'method': method,
                'arguments': arguments or {}
            }
        )
        response.raise_for_status()
        return response.json()
    
    def listen_sse(self, tool_name: str, event_handlers: Dict[str, Callable]):
        """
        Listen to SSE stream in a background thread
        
        Args:
            tool_name: Name of the tool
            event_handlers: Dict mapping event types to handler functions
        """
        if not self.session_id:
            raise ValueError("No active session")
        
        def sse_worker():
            url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}/sse"
            
            try:
                response = requests.get(
                    url,
                    headers=self._get_headers(),
                    stream=True
                )
                response.raise_for_status()
                
                client = sseclient.SSEClient(response)
                print("✓ SSE connection established")
                
                for event in client.events():
                    if not self.sse_running:
                        break
                    
                    event_type = event.event
                    data = json.loads(event.data) if event.data else {}
                    
                    # Call appropriate handler
                    handler = event_handlers.get(event_type)
                    if handler:
                        try:
                            handler(data)
                        except Exception as e:
                            print(f"✗ Error in event handler: {e}")
                    
                    # Stop on close event
                    if event_type == 'close':
                        break
                        
            except Exception as e:
                print(f"✗ SSE connection error: {e}")
            finally:
                print("✓ SSE connection closed")
        
        self.sse_running = True
        self.sse_thread = threading.Thread(target=sse_worker, daemon=True)
        self.sse_thread.start()
    
    def stop_sse(self):
        """Stop SSE listening"""
        self.sse_running = False
        if self.sse_thread:
            self.sse_thread.join(timeout=5)
    
    def close_session(self, tool_name: str) -> Dict[str, Any]:
        """Close the session"""
        if not self.session_id:
            return {}
        
        # Stop SSE if running
        self.stop_sse()
        
        url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}"
        response = requests.delete(url, headers=self._get_headers())
        response.raise_for_status()
        
        data = response.json()
        print(f"✓ Session closed: {self.session_id[:8]}...")
        self.session_id = None
        return data


def example_1_basic_session():
    """Example 1: Basic session management"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic Session Management")
    print("="*60)
    
    client = MCPStatefulClient(
        base_url="http://localhost:5000",
        username="admin",
        password="admin123"
    )
    
    # Create session
    session = client.create_session(
        "bank_of_canada_tool",
        initial_state={'currency': 'USD', 'monitoring': True}
    )
    
    # Get state
    state = client.get_session_state("bank_of_canada_tool")
    print(f"\nCurrent state: {state['state']}")
    
    # Update state
    client.set_session_state("bank_of_canada_tool", {
        'currency': 'EUR',
        'last_check': time.time()
    })
    
    # Get updated state
    state = client.get_session_state("bank_of_canada_tool")
    print(f"Updated state: {state['state']}")
    
    # Close session
    client.close_session("bank_of_canada_tool")


def example_2_sse_monitoring():
    """Example 2: Real-time monitoring with SSE"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Real-time Monitoring with SSE")
    print("="*60)
    
    client = MCPStatefulClient(
        base_url="http://localhost:5000",
        username="admin",
        password="admin123"
    )
    
    # Create session
    client.create_session(
        "bank_of_canada_tool",
        initial_state={'monitoring_rate': 'policy', 'threshold': 5.0}
    )
    
    # Define event handlers
    def on_connected(data):
        print(f"\n[CONNECTED] {data}")
    
    def on_update(data):
        print(f"\n[UPDATE] {data}")
    
    def on_alert(data):
        print(f"\n[ALERT] ⚠️  {data}")
    
    def on_heartbeat(data):
        print(".", end="", flush=True)
    
    def on_close(data):
        print(f"\n[CLOSE] {data}")
    
    event_handlers = {
        'connected': on_connected,
        'update': on_update,
        'alert': on_alert,
        'heartbeat': on_heartbeat,
        'close': on_close
    }
    
    # Start SSE listening
    client.listen_sse("bank_of_canada_tool", event_handlers)
    
    print("\nListening for events (press Ctrl+C to stop)...")
    
    try:
        # Make some tool calls that might trigger events
        for i in range(3):
            time.sleep(5)
            result = client.call_tool(
                "bank_of_canada_tool",
                "get_policy_rate",
                {'recent': 1, 'session_id': client.session_id}
            )
            print(f"\n[CALL] Policy rate: {result}")
    
    except KeyboardInterrupt:
        print("\n\nStopping...")
    
    finally:
        client.close_session("bank_of_canada_tool")


def example_3_stateful_workflow():
    """Example 3: Stateful workflow with context"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Stateful Workflow with Context")
    print("="*60)
    
    client = MCPStatefulClient(
        base_url="http://localhost:5000",
        username="analyst",
        password="analyst123"
    )
    
    # Create session with analysis context
    client.create_session(
        "bank_of_canada_tool",
        initial_state={
            'analysis_type': 'monetary_policy',
            'date_range': '2024-01-01_to_2025-10-22',
            'indicators': ['policy_rate', 'cpi', 'gdp']
        }
    )
    
    # Step 1: Fetch policy rate with session context
    print("\nStep 1: Fetching policy rate...")
    result = client.call_tool(
        "bank_of_canada_tool",
        "get_policy_rate",
        {'recent': 12, 'session_id': client.session_id}
    )
    
    # Store analysis results in session
    client.set_session_state("bank_of_canada_tool", {
        'policy_rate_data': result,
        'step': 1
    })
    
    # Step 2: Fetch CPI data
    print("\nStep 2: Fetching CPI data...")
    result = client.call_tool(
        "bank_of_canada_tool",
        "get_cpi_data",
        {'cpi_type': 'all_items'}
    )
    
    # Update session with more data
    client.set_session_state("bank_of_canada_tool", {
        'cpi_data': result,
        'step': 2
    })
    
    # Step 3: Fetch exchange rate
    print("\nStep 3: Fetching exchange rate...")
    result = client.call_tool(
        "bank_of_canada_tool",
        "get_exchange_rates",
        {'currency': 'USD', 'recent': 12}
    )
    
    # Complete analysis
    client.set_session_state("bank_of_canada_tool", {
        'exchange_rate_data': result,
        'step': 3,
        'analysis_complete': True
    })
    
    # Get final state
    final_state = client.get_session_state("bank_of_canada_tool")
    print(f"\nAnalysis complete! Collected {len(final_state['state'])} data points")
    print(f"Session state keys: {list(final_state['state'].keys())}")
    
    # Close session
    client.close_session("bank_of_canada_tool")


def example_4_concurrent_sessions():
    """Example 4: Multiple concurrent sessions"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Multiple Concurrent Sessions")
    print("="*60)
    
    # Create multiple clients
    clients = []
    for i in range(3):
        client = MCPStatefulClient(
            base_url="http://localhost:5000",
            username="admin",
            password="admin123"
        )
        clients.append(client)
    
    # Create session for each client with different context
    currencies = ['USD', 'EUR', 'GBP']
    for i, client in enumerate(clients):
        client.create_session(
            "bank_of_canada_tool",
            initial_state={
                'currency': currencies[i],
                'client_id': i,
                'monitoring': True
            }
        )
        print(f"Client {i}: Monitoring {currencies[i]}")
    
    # Make calls from different sessions
    print("\nMaking parallel calls...")
    for i, client in enumerate(clients):
        result = client.call_tool(
            "bank_of_canada_tool",
            "get_exchange_rates",
            {
                'currency': currencies[i],
                'recent': 1,
                'session_id': client.session_id
            }
        )
        print(f"Client {i} ({currencies[i]}): {result}")
    
    # Close all sessions
    print("\nClosing all sessions...")
    for client in clients:
        client.close_session("bank_of_canada_tool")


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║        Stateful MCP Client Examples                        ║
    ║                                                            ║
    ║  Make sure the MCP server is running before executing!    ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    
    # Run examples
    try:
        example_1_basic_session()
        time.sleep(2)
        
        example_3_stateful_workflow()
        time.sleep(2)
        
        example_4_concurrent_sessions()
        time.sleep(2)
        
        # Run SSE example last (it's interactive)
        # Uncomment to run:
        # example_2_sse_monitoring()
        
    except requests.exceptions.ConnectionError:
        print("\n✗ Error: Could not connect to MCP server")
        print("  Make sure the server is running at http://localhost:5000")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
