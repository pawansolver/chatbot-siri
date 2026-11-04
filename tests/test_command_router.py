import pytest
from backend.core.command_router import CommandRouter, get_command_router


def test_command_router_english_commands():
    """Verify local English commands are matched deterministically."""
    router = get_command_router()

    # 1. Stop
    res_stop = router.route("stop")
    assert res_stop.is_command is True
    assert res_stop.command_name == "stop"
    assert res_stop.action == "STOP_PLAYBACK"

    # 2. Cancel
    res_cancel = router.route("cancel.")
    assert res_cancel.is_command is True
    assert res_cancel.command_name == "stop"

    # 3. Mute
    res_mute = router.route("mute audio")
    assert res_mute.is_command is True
    assert res_mute.command_name == "mute"

    # 4. Volume Up
    res_vol = router.route("volume up!")
    assert res_vol.is_command is True
    assert res_vol.command_name == "volume_up"

    # 5. Clear History
    res_clear = router.route("clear history")
    assert res_clear.is_command is True
    assert res_clear.command_name == "clear_history"


def test_command_router_hindi_and_hinglish():
    """Verify local Hindi and Hinglish commands are matched accurately."""
    router = get_command_router()

    # Hindi Devanagari commands
    res_ruko = router.route("रुको")
    assert res_ruko.is_command is True
    assert res_ruko.command_name == "stop"

    res_band = router.route("बंद करो")
    assert res_band.is_command is True
    assert res_band.command_name == "stop"

    res_awaaz_band = router.route("आवाज़ बंद करो")
    assert res_awaaz_band.is_command is True
    assert res_awaaz_band.command_name == "mute"

    # Hinglish Latin commands
    res_chup = router.route("chup ho jao")
    assert res_chup.is_command is True
    assert res_chup.command_name == "stop"

    res_awaaz_badhao = router.route("awaaz badhao")
    assert res_awaaz_badhao.is_command is True
    assert res_awaaz_badhao.command_name == "volume_up"


def test_command_router_normal_questions_bypass():
    """Ensure normal conversational questions containing command keywords are NOT falsely intercepted."""
    router = get_command_router()

    # Questions containing 'stop'
    res_q1 = router.route("Why did the driver stop the bus?")
    assert res_q1.is_command is False

    res_q2 = router.route("Can you tell me about codon stop in genetics?")
    assert res_q2.is_command is False

    # Questions containing 'volume'
    res_q3 = router.route("What is volume formula of a cylinder?")
    assert res_q3.is_command is False

    # Questions containing 'cancel'
    res_q4 = router.route("How to cancel an airline booking online?")
    assert res_q4.is_command is False

    # Hindi questions containing 'ruko'
    res_q5 = router.route("रुको शब्द का अर्थ क्या है?")
    assert res_q5.is_command is False
