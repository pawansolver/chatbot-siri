import asyncio
import json
import logging
from typing import Set, Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.state_manager import get_state_manager, AssistantState
from backend.core.device_state import get_device_state_manager, DeviceState
from backend.core.assistant import get_assistant_core
from backend.core.session import get_session_manager

logger = logging.getLogger("ai_voice_assistant.websocket")

ws_router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages active WebSocket client connections and broadcasts state/event changes."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast_event(
        self,
        event_type: str,
        data: Any,
        state: Optional[str] = None,
        generation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        if not self.active_connections:
            return
        payload = json.dumps({
            "type": event_type,
            "state": state,
            "generation_id": generation_id,
            "session_id": session_id,
            "data": data,
        })
        dead_sockets = set()
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                dead_sockets.add(connection)
        for dead in dead_sockets:
            self.active_connections.discard(dead)


ws_manager = ConnectionManager()


# Register listener with StateManager to broadcast real-time assistant state transitions
def on_assistant_state_change(new_state: AssistantState, metadata: dict):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            ws_manager.broadcast_event(
                event_type="state_change",
                data={"metadata": metadata},
                state=new_state.value,
            )
        )
    except RuntimeError:
        pass


get_state_manager().register_listener(on_assistant_state_change)


# Register listener with DeviceStateManager to broadcast physical device hardware changes
def on_device_state_change(new_state: DeviceState, metadata: dict):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            ws_manager.broadcast_event(
                event_type="device_state_change",
                data={"device_state": new_state.value, "metadata": metadata},
            )
        )
    except RuntimeError:
        pass


get_device_state_manager().register_listener(on_device_state_change)


@ws_router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for bi-directional real-time voice, streaming, and generation cancellation."""
    await ws_manager.connect(websocket)
    state_mgr = get_state_manager()
    device_mgr = get_device_state_manager()
    assistant = get_assistant_core()
    session_mgr = get_session_manager()

    try:
        # Send initial handshake state
        await websocket.send_text(json.dumps({
            "type": "state_change",
            "state": state_mgr.current_state.value,
            "data": {
                "message": "Connected to Aether Assistant WebSocket",
                "device_state": device_mgr.current_state.value,
            },
        }))

        while True:
            raw_data = await websocket.receive_text()
            try:
                msg = json.loads(raw_data)
            except Exception:
                continue

            msg_type = msg.get("type", "")
            session_id = msg.get("session_id")
            generation_id = msg.get("generation_id")

            # 1. Handle Explicit Generation Cancellation / Barge-In
            if msg_type in ("cancel_generation", "barge_in", "cancel"):
                logger.info(f"⚡ WS cancel_generation received for [{generation_id} in {session_id}]")
                state_mgr.cancel_active_task()
                if session_id:
                    session = session_mgr.get_session(session_id)
                    if session:
                        session.cancel_current_generation()

                await ws_manager.broadcast_event(
                    event_type="cancel_ack",
                    data={"status": "generation_cancelled", "generation_id": generation_id},
                    state="IDLE",
                    generation_id=generation_id,
                    session_id=session_id,
                )

            # 2. Handle Streaming Chat with Generation ID
            elif msg_type == "stream_chat":
                prompt = msg.get("prompt", "").strip()
                session = session_mgr.get_or_create_session(session_id)
                current_gen_id = session.new_generation()

                if prompt:
                    # Check local command router first
                    cmd_res = assistant.command_router.route(prompt)
                    if cmd_res.is_command:
                        await websocket.send_text(json.dumps({
                            "type": "command_executed",
                            "data": {
                                "command_name": cmd_res.command_name,
                                "action": cmd_res.action,
                                "response": cmd_res.response_text,
                            },
                            "generation_id": current_gen_id,
                            "session_id": session.session_id,
                        }))
                        continue

                    state_mgr.set_state(AssistantState.THINKING)
                    history_ctx = session.conversation.get_gemini_context()
                    session.conversation.add_user_message(prompt, source="text")

                    full_reply = []
                    async for chunk in assistant.gemini_svc.generate_response_stream(prompt, history=history_ctx):
                        # Verify generation has not been cancelled mid-stream
                        if not session.is_current_generation(current_gen_id):
                            logger.info(f"WS stream aborted mid-chunk for stale generation {current_gen_id}")
                            break

                        full_reply.append(chunk)
                        await websocket.send_text(json.dumps({
                            "type": "stream_chunk",
                            "data": {"chunk": chunk},
                            "generation_id": current_gen_id,
                        }))

                    if session.is_current_generation(current_gen_id):
                        final_text = "".join(full_reply).strip()
                        session.conversation.add_assistant_message(final_text)

                        audio_url = None
                        if msg.get("speak", True) and final_text:
                            state_mgr.set_state(AssistantState.SPEAKING)
                            chosen_voice = assistant.voice_router.route_voice(final_text)
                            filename = await assistant.tts_svc.synthesize_to_file(final_text, voice=chosen_voice)
                            if filename and session.is_current_generation(current_gen_id):
                                audio_url = f"/api/audio/{filename}"

                        await websocket.send_text(json.dumps({
                            "type": "final_response",
                            "data": {
                                "response": final_text,
                                "audio_url": audio_url,
                            },
                            "state": state_mgr.current_state.value,
                            "generation_id": current_gen_id,
                            "session_id": session.session_id,
                        }))
                        if not audio_url:
                            state_mgr.reset_to_idle()

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
