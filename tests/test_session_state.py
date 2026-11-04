import pytest
from backend.core.session import SessionManager
from backend.core.state_manager import StateManager, AssistantState


def test_session_manager_isolation():
    """Verify separate sessions have completely isolated conversation histories."""
    mgr = SessionManager()

    # Create Session 1
    s1 = mgr.get_or_create_session("session_alice")
    s1.conversation.add_user_message("Hello from Alice")
    s1.conversation.add_assistant_message("Hi Alice!")

    # Create Session 2
    s2 = mgr.get_or_create_session("session_bob")
    s2.conversation.add_user_message("Hello from Bob")

    # Verify Alice's history
    alice_hist = s1.conversation.get_history()
    assert len(alice_hist) == 2
    assert alice_hist[0]["text"] == "Hello from Alice"

    # Verify Bob's history
    bob_hist = s2.conversation.get_history()
    assert len(bob_hist) == 1
    assert bob_hist[0]["text"] == "Hello from Bob"

    # Delete session
    assert mgr.delete_session("session_alice") is True
    assert mgr.get_session("session_alice") is None


def test_state_manager_transition_validation_and_barge_in():
    """Verify StateManager validates transitions and handles barge-in."""
    sm = StateManager()
    assert sm.current_state == AssistantState.IDLE

    # Valid: IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE
    assert sm.set_state(AssistantState.LISTENING) is True
    assert sm.set_state(AssistantState.THINKING) is True
    assert sm.set_state(AssistantState.SPEAKING) is True
    assert sm.set_state(AssistantState.IDLE) is True

    # Invalid jump: IDLE -> SPEAKING (should be rejected)
    assert sm.set_state(AssistantState.SPEAKING) is False
    assert sm.current_state == AssistantState.IDLE

    # Test Barge-In: SPEAKING -> LISTENING without barge_in flag should fail
    sm.set_state(AssistantState.LISTENING)
    sm.set_state(AssistantState.THINKING)
    sm.set_state(AssistantState.SPEAKING)
    assert sm.set_state(AssistantState.LISTENING, barge_in=False) is False

    # With barge_in=True, it succeeds
    assert sm.set_state(AssistantState.LISTENING, barge_in=True) is True
    assert sm.current_state == AssistantState.LISTENING

    # Force reset
    sm.reset_to_idle()
    assert sm.current_state == AssistantState.IDLE
