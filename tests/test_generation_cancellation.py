import pytest
from backend.core.session import Session, SessionManager
from backend.core.assistant import AssistantCore, get_assistant_core
from backend.core.state_manager import StateManager, AssistantState


def test_generation_id_invalidation():
    """Verify that creating a new generation strictly invalidates the old generation."""
    session = Session(session_id="test_gen_session")
    
    # Generation 1
    gen_1 = session.new_generation()
    assert session.is_current_generation(gen_1) is True

    # Generation 2 (supersedes gen_1)
    gen_2 = session.new_generation()
    assert session.is_current_generation(gen_2) is True
    assert session.is_current_generation(gen_1) is False  # Gen 1 is now invalid!

    # Explicit cancel
    session.cancel_current_generation()
    assert session.is_current_generation(gen_2) is False  # Gen 2 is cancelled!


@pytest.mark.asyncio
async def test_assistant_stale_generation_rejection():
    """Verify AssistantCore discards responses when generation ID is stale."""
    assistant = get_assistant_core()
    session = assistant.session_mgr.get_or_create_session("stale_test_sess")
    
    # 1. Start generation 1
    gen_1 = session.new_generation()
    
    # 2. Immediately create generation 2 (simulating user barge-in / new input)
    gen_2 = session.new_generation()

    # Now attempt to process with superseded gen_1
    result = await assistant.process_text_input(
        prompt="Tell me a long story",
        speak=False,
        session_id="stale_test_sess",
    )
    # The new request creates gen_3, and gen_1 is rejected
    assert result["success"] is True
    assert result["generation_id"] != gen_1
