# 🔌 Model Context Protocol (MCP) Integration Architecture

This document describes the future integration of **MCP (Model Context Protocol)** servers and tool execution into the **Aether AI Voice Assistant Core**.

---

## 1. Tool Call Architecture

```
                 🎤 User Speech
                       │
                       ▼
                 Assistant Core
                       │
                       ▼
               Google Gemini API
          (Function Calling / Tool Decider)
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
[Plain Conversational Reply]  [MCP Tool Call Requested]
                                     │
                                     ▼
                              Tool Manager
                                     │
                                     ▼
                            ┌────────────────┐
                            │   MCP Client   │
                            └────────┬───────┘
                                     │ (JSON-RPC / stdio / SSE)
                                     ▼
                            ┌────────────────┐
                            │   MCP Server   │
                            │  (GPIO / Home  │
                            │  Automation)   │
                            └────────┬───────┘
                                     │
                                     ▼
                              Tool Result
                                     │
                                     ▼
                             Gemini Synthesis
                                     │
                                     ▼
                             Neural TTS Audio
```

---

## 2. Integration Extension Point in `AssistantCore`

In `backend/core/assistant.py`:
```python
# Planned MCP extension hook
async def execute_tool_calls(self, function_calls: list) -> list:
    results = []
    for call in function_calls:
        # Route to configured MCP server
        result = await self.mcp_client.call_tool(name=call.name, arguments=call.args)
        results.append(result)
    return results
```

This decoupled design allows plugging in home automation, smart light switches, IoT relays, or weather sensors without modifying voice or UI layers.
