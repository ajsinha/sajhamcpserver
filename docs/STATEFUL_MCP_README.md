# Stateful MCP with Server-Sent Events (SSE) Enhancement

## Overview

This enhancement adds stateful capabilities to the MCP (Model Context Protocol) tool framework using Server-Sent Events (SSE) and server-side push. Tools can now maintain session state and push real-time updates to clients.

## Key Features

### 1. **Stateful Sessions**
- Create persistent sessions that maintain state across multiple calls
- Session-specific state storage and retrieval
- Automatic session cleanup based on configurable timeout
- Maximum session limits per tool

### 2. **Server-Sent Events (SSE)**
- Real-time event streaming from server to client
- Long-lived HTTP connections for continuous updates
- Heartbeat mechanism to keep connections alive
- Automatic reconnection support

### 3. **Server-Side Push**
- Tools can proactively push data to client sessions
- Event-based notification system
- Support for custom event types
- Message queuing and history

### 4. **Configurable per Tool**
- Enable/disable stateful features per tool via configuration
- Tools without stateful configuration work as before
- No breaking changes to existing implementations

## Architecture

```
┌─────────────┐
│   Client    │
│  (Browser/  │
│    App)     │
└──────┬──────┘
       │
       │ 1. Create Session (POST)
       ▼
┌─────────────────────────────────┐
│   MCP Flask Application         │
│  (mcp_app_stateful.py)          │
│                                 │
│  ┌──────────────────────────┐  │
│  │  Session Management      │  │
│  │  - Create/Close Session  │  │
│  │  - Get/Set State         │  │
│  │  - SSE Streaming         │  │
│  └──────────────────────────┘  │
└────────┬────────────────────────┘
         │
         │ 2. Manage Sessions
         ▼
┌─────────────────────────────────┐
│   BaseMCPTool                   │
│  (base_mcp_tool_stateful.py)    │
│                                 │
│  ┌──────────────────────────┐  │
│  │  StatefulSession         │  │
│  │  - State Storage         │  │
│  │  - Message Queue         │  │
│  │  - Event History         │  │
│  └──────────────────────────┘  │
│                                 │
│  ┌──────────────────────────┐  │
│  │  Background Workers      │  │
│  │  - Session Cleanup       │  │
│  │  - Data Monitoring       │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
         │
         │ 3. Tool-Specific Logic
         ▼
┌─────────────────────────────────┐
│   Specific Tool Implementation  │
│  (e.g., BankOfCanadaMCPTool)    │
│                                 │
│  - Custom stateful methods      │
│  - Push updates to sessions     │
│  - Monitor external data        │
└─────────────────────────────────┘
```

## Configuration

### Tool Configuration (JSON)

Add the following fields to your tool configuration:

```json
{
  "name": "my_tool",
  "module": "tools.my_tool.MyTool",
  "max_hits": 1000,
  "max_hit_interval": 10,
  
  "stateful_enabled": true,      // Enable stateful sessions
  "sse_enabled": true,            // Enable Server-Sent Events
  "push_enabled": true,           // Enable server-side push
  "session_timeout": 3600,        // Session timeout in seconds (1 hour)
  "max_sessions": 100,            // Maximum concurrent sessions
  
  "tool_description": {
    // ... existing tool definitions
  }
}
```

### Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `stateful_enabled` | boolean | `false` | Enable stateful session support |
| `sse_enabled` | boolean | `false` | Enable Server-Sent Events streaming |
| `push_enabled` | boolean | `false` | Enable server-side push notifications |
| `session_timeout` | integer | `3600` | Session timeout in seconds |
| `max_sessions` | integer | `100` | Maximum number of concurrent sessions |

## API Endpoints

### Session Management

#### 1. Create Session
```
POST /api/tool/{tool_name}/session/create
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "initial_state": {
    "key1": "value1",
    "key2": "value2"
  }
}

Response (201):
{
  "session_id": "uuid-string",
  "created_at": "2025-10-22T10:30:00",
  "sse_enabled": true,
  "push_enabled": true,
  "user": "username"
}
```

#### 2. Close Session
```
DELETE /api/tool/{tool_name}/session/{session_id}
Authorization: Bearer <jwt_token>

Response (200):
{
  "success": true,
  "session_id": "uuid-string",
  "message": "Session closed successfully"
}
```

#### 3. Get Session State
```
GET /api/tool/{tool_name}/session/{session_id}/state
Authorization: Bearer <jwt_token>

Response (200):
{
  "session_id": "uuid-string",
  "state": {
    "key1": "value1",
    "key2": "value2"
  },
  "created_at": "2025-10-22T10:30:00",
  "last_activity": "2025-10-22T10:35:00"
}
```

#### 4. Set Session State
```
PUT /api/tool/{tool_name}/session/{session_id}/state
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "state": {
    "key1": "new_value1",
    "key3": "value3"
  }
}

Response (200):
{
  "success": true,
  "session_id": "uuid-string",
  "state": {
    "key1": "new_value1",
    "key2": "value2",
    "key3": "value3"
  }
}
```

### Server-Sent Events (SSE)

#### 5. SSE Stream Endpoint
```
GET /api/tool/{tool_name}/session/{session_id}/sse
Authorization: Bearer <jwt_token>

Response (200):
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: connected
id: connection-id
data: {"session_id": "uuid-string"}

event: update
id: message-id-1
data: {"type": "rate_change", "old_value": 5.0, "new_value": 5.25}

event: heartbeat
data: {"timestamp": "2025-10-22T10:35:00"}

event: alert
id: message-id-2
data: {"indicator": "cpi", "value": 3.2, "threshold": 3.0}

event: close
data: {"message": "Session closed"}
```

### Server-Side Push

#### 6. Push Message to Session
```
POST /api/tool/{tool_name}/session/{session_id}/push
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "event": "custom_event",
  "data": {
    "message": "Custom notification",
    "value": 123
  }
}

Response (200):
{
  "success": true,
  "message": "Message pushed successfully"
}
```

## Implementation Guide

### 1. Extend BaseMCPTool for Stateful Tools

```python
from base_mcp_tool_stateful import BaseMCPTool

class MyStatefulTool(BaseMCPTool):
    def _initialize(self):
        """Initialize tool-specific components"""
        super()._initialize()
        
        # Start background monitoring if stateful
        if self.stateful_enabled and self.push_enabled:
            self._start_monitoring()
    
    def _start_monitoring(self):
        """Start background monitoring thread"""
        import threading
        
        def monitor_worker():
            while True:
                # Monitor external data source
                data = self._fetch_external_data()
                
                # Push updates to all active sessions
                with self._session_lock:
                    for session_id, session in self.sessions.items():
                        if self._should_notify(session, data):
                            self.push_to_session(
                                session_id,
                                'data_update',
                                {'value': data}
                            )
                
                time.sleep(60)  # Check every minute
        
        thread = threading.Thread(target=monitor_worker, daemon=True)
        thread.start()
    
    def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]):
        """Handle tool calls with session context"""
        # Get session ID from arguments if provided
        session_id = arguments.get('session_id')
        
        if tool_name == "subscribe_updates":
            return self._subscribe_updates(session_id, arguments)
        
        # Handle other tool calls
        return super().handle_tool_call(tool_name, arguments)
    
    def _subscribe_updates(self, session_id: str, arguments: Dict[str, Any]):
        """Subscribe to updates for a session"""
        if not session_id:
            return {"error": "Session ID required"}
        
        session = self.get_session(session_id)
        if not session:
            return {"error": "Session not found"}
        
        # Store subscription preferences in session state
        session.set_state('subscribed', True)
        session.set_state('update_type', arguments.get('update_type'))
        
        return {
            "success": True,
            "message": "Subscribed to updates"
        }
```

### 2. Client Implementation Examples

#### Python Client

```python
import requests
import json
import sseclient  # pip install sseclient-py

class MCPStatefulClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        self.session_id = None
    
    def create_session(self, tool_name, initial_state=None):
        """Create a new session"""
        url = f"{self.base_url}/api/tool/{tool_name}/session/create"
        response = requests.post(
            url,
            headers=self.headers,
            json={'initial_state': initial_state or {}}
        )
        response.raise_for_status()
        data = response.json()
        self.session_id = data['session_id']
        return data
    
    def listen_sse(self, tool_name, callback):
        """Listen to SSE stream"""
        if not self.session_id:
            raise ValueError("No active session")
        
        url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}/sse"
        response = requests.get(
            url,
            headers=self.headers,
            stream=True
        )
        
        client = sseclient.SSEClient(response)
        for event in client.events():
            callback(event.event, json.loads(event.data))
    
    def close_session(self, tool_name):
        """Close the session"""
        if not self.session_id:
            return
        
        url = f"{self.base_url}/api/tool/{tool_name}/session/{self.session_id}"
        response = requests.delete(url, headers=self.headers)
        response.raise_for_status()
        return response.json()


# Usage example
def handle_event(event_type, data):
    print(f"Received {event_type}: {data}")

client = MCPStatefulClient("http://localhost:5000", "your-jwt-token")

# Create session
session_info = client.create_session(
    "bank_of_canada_tool",
    initial_state={'currency': 'USD', 'alert_threshold': 1.30}
)
print(f"Session created: {session_info['session_id']}")

# Subscribe to updates (tool-specific method)
# ... make tool calls ...

# Listen for SSE events
try:
    client.listen_sse("bank_of_canada_tool", handle_event)
except KeyboardInterrupt:
    client.close_session("bank_of_canada_tool")
```

#### JavaScript Client

```javascript
class MCPStatefulClient {
  constructor(baseUrl, accessToken) {
    this.baseUrl = baseUrl;
    this.accessToken = accessToken;
    this.sessionId = null;
    this.eventSource = null;
  }

  async createSession(toolName, initialState = {}) {
    const response = await fetch(
      `${this.baseUrl}/api/tool/${toolName}/session/create`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ initial_state: initialState })
      }
    );
    
    const data = await response.json();
    this.sessionId = data.session_id;
    return data;
  }

  listenSSE(toolName, callbacks) {
    if (!this.sessionId) {
      throw new Error('No active session');
    }

    const url = `${this.baseUrl}/api/tool/${toolName}/session/${this.sessionId}/sse`;
    
    this.eventSource = new EventSource(url, {
      headers: {
        'Authorization': `Bearer ${this.accessToken}`
      }
    });

    // Handle different event types
    this.eventSource.addEventListener('connected', (event) => {
      const data = JSON.parse(event.data);
      callbacks.onConnected?.(data);
    });

    this.eventSource.addEventListener('update', (event) => {
      const data = JSON.parse(event.data);
      callbacks.onUpdate?.(data);
    });

    this.eventSource.addEventListener('alert', (event) => {
      const data = JSON.parse(event.data);
      callbacks.onAlert?.(data);
    });

    this.eventSource.addEventListener('heartbeat', (event) => {
      const data = JSON.parse(event.data);
      callbacks.onHeartbeat?.(data);
    });

    this.eventSource.addEventListener('close', (event) => {
      const data = JSON.parse(event.data);
      callbacks.onClose?.(data);
      this.eventSource.close();
    });

    this.eventSource.onerror = (error) => {
      callbacks.onError?.(error);
    };
  }

  async closeSession(toolName) {
    if (!this.sessionId) return;

    if (this.eventSource) {
      this.eventSource.close();
    }

    const response = await fetch(
      `${this.baseUrl}/api/tool/${toolName}/session/${this.sessionId}`,
      {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${this.accessToken}`
        }
      }
    );

    return response.json();
  }
}

// Usage example
const client = new MCPStatefulClient('http://localhost:5000', 'your-jwt-token');

(async () => {
  // Create session
  const session = await client.createSession('bank_of_canada_tool', {
    currency: 'USD',
    alert_threshold: 1.30
  });
  console.log('Session created:', session.session_id);

  // Listen for SSE events
  client.listenSSE('bank_of_canada_tool', {
    onConnected: (data) => {
      console.log('Connected:', data);
    },
    onUpdate: (data) => {
      console.log('Update received:', data);
    },
    onAlert: (data) => {
      console.log('Alert:', data);
    },
    onHeartbeat: (data) => {
      console.log('Heartbeat:', data.timestamp);
    },
    onClose: (data) => {
      console.log('Connection closed:', data.message);
    },
    onError: (error) => {
      console.error('SSE Error:', error);
    }
  });
})();
```

## Use Cases

### 1. Real-Time Financial Data Monitoring
- Monitor exchange rates, interest rates, or stock prices
- Push alerts when thresholds are crossed
- Maintain user preferences in session state

### 2. Long-Running Analysis Tasks
- Start analysis in one request
- Push progress updates via SSE
- Client receives results without polling

### 3. Collaborative Sessions
- Multiple clients share a session
- Server pushes updates to all connected clients
- Synchronize state across clients

### 4. Event-Driven Workflows
- Subscribe to specific events
- Receive notifications as events occur
- Maintain workflow state across requests

## Security Considerations

1. **Authentication**: All endpoints require JWT authentication
2. **Session Isolation**: Sessions are user-specific and isolated
3. **Rate Limiting**: Existing rate limiting applies to session operations
4. **Timeout**: Sessions automatically expire after inactivity
5. **Maximum Sessions**: Limit prevents resource exhaustion

## Performance Considerations

1. **Connection Pooling**: Use HTTP/2 for efficient SSE connections
2. **Message Queuing**: In-memory queues for fast message delivery
3. **Background Cleanup**: Automatic cleanup of expired sessions
4. **Threading**: Proper thread safety for concurrent access
5. **Memory Management**: Bounded queues and history limits

## Backward Compatibility

- Tools without stateful configuration work unchanged
- Existing API endpoints remain functional
- Gradual migration path for existing tools
- No breaking changes to tool registry

## Testing

See the `examples/` directory for:
- Unit tests for stateful sessions
- Integration tests for SSE endpoints
- Load testing scripts
- Example client implementations

## Troubleshooting

### SSE Connection Drops
- Check firewall/proxy timeout settings
- Verify heartbeat messages are being sent
- Implement client-side reconnection logic

### Session Not Found
- Verify session hasn't expired (check timeout)
- Ensure session_id is correctly passed
- Check session was created successfully

### Messages Not Received
- Verify push_enabled is true in config
- Check session is active
- Ensure SSE connection is established

## Future Enhancements

1. **Redis Backend**: Store sessions in Redis for clustering
2. **WebSocket Support**: Alternative to SSE for bidirectional communication
3. **Session Sharing**: Allow multiple users to join same session
4. **Replay**: Replay message history for late-joining clients
5. **Compression**: Compress SSE messages for bandwidth efficiency

## License

[Your license here]

## Contributors

[Your contributors here]
