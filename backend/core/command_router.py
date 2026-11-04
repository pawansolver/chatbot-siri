import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
import logging

logger = logging.getLogger("ai_voice_assistant.command_router")


@dataclass
class CommandResult:
    """Result of command router evaluation."""
    is_command: bool
    command_name: Optional[str] = None
    action: Optional[str] = None
    response_text: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


# (Regex Pattern, Command Name, Action, English Spoken Confirmation, Hindi Spoken Confirmation)
LOCAL_COMMAND_PATTERNS: List[Tuple[str, str, str, str, str]] = [
    # 1. Stop / Cancel / Interrupt
    (
        r"^(stop|halt|cancel|terminate|abort|be quiet|shut up|ruko|ruk jao|chup|chup ho jao|band karo|shant raho|रुको|रुकिए|बंद करो|शांत रहो)$",
        "stop",
        "STOP_PLAYBACK",
        "Stopping playback.",
        "रोक दिया गया है।",
    ),
    # 2. Mute Audio
    (
        r"^(mute|mute audio|mute sound|sound off|awaaz band karo|mute karo|आवाज़ बंद करो|म्यूट करो)$",
        "mute",
        "MUTE_AUDIO",
        "Microphone and speaker muted.",
        "आवाज़ म्यूट कर दी गई है।",
    ),
    # 3. Unmute Audio
    (
        r"^(unmute|unmute audio|sound on|awaaz chalu karo|unmute karo|आवाज़ चालू करो|अनम्यूट करो)$",
        "unmute",
        "UNMUTE_AUDIO",
        "Audio unmuted.",
        "आवाज़ चालू कर दी गई है।",
    ),
    # 4. Volume Up
    (
        r"^(volume up|increase volume|louder|make it louder|turn it up|awaaz badhao|volume badhao|आवाज़ बढ़ाओ|वॉल्यूम बढ़ाओ)$",
        "volume_up",
        "VOLUME_UP",
        "Increasing volume.",
        "आवाज़ बढ़ा दी गई है।",
    ),
    # 5. Volume Down
    (
        r"^(volume down|decrease volume|lower volume|softer|turn it down|awaaz kam karo|volume kam karo|आवाज़ कम करो|वॉल्यूम कम करो)$",
        "volume_down",
        "VOLUME_DOWN",
        "Lowering volume.",
        "आवाज़ कम कर दी गई है।",
    ),
    # 6. Pause
    (
        r"^(pause|pause playback|pause audio|rok do|रोक दो|पॉज़ करो)$",
        "pause",
        "PAUSE_PLAYBACK",
        "Playback paused.",
        "रोक दिया गया है।",
    ),
    # 7. Resume
    (
        r"^(resume|resume playback|continue playback|chalu karo|जारी रखो|फिर से शुरू करो)$",
        "resume",
        "RESUME_PLAYBACK",
        "Resuming playback.",
        "फिर से शुरू कर दिया गया है।",
    ),
    # 8. Clear History
    (
        r"^(clear history|clear chat|clear conversation|delete history|history clear karo|chat clear karo|इतिहास साफ़ करो|चैट मिटाओ)$",
        "clear_history",
        "CLEAR_HISTORY",
        "Conversation history cleared.",
        "बातचीत का इतिहास साफ़ कर दिया गया है।",
    ),
    # 9. Status
    (
        r"^(system status|device status|status|how are you running|battery status|स्थिति बताओ|सिस्टम स्थिति)$",
        "status",
        "CHECK_STATUS",
        "System is running normally.",
        "सिस्टम सुचारू रूप से कार्य कर रहा है।",
    ),
]


class CommandRouter:
    """Deterministic local command routing layer.
    Routes local commands (Stop, Mute, Volume, Clear) instantly without calling Gemini,
    while safely passing normal conversational queries to the LLM.
    """

    def __init__(self):
        self._compiled_patterns = [
            (re.compile(pat, re.IGNORECASE), name, action, en_reply, hi_reply)
            for pat, name, action, en_reply, hi_reply in LOCAL_COMMAND_PATTERNS
        ]

    def route(self, text: str, preferred_lang: str = "en") -> CommandResult:
        """Evaluate whether text is a local hardware/playback command."""
        clean = text.strip()
        # Remove trailing punctuation like period or exclamation mark
        clean_normalized = re.sub(r"[.!?।]+$", "", clean).strip()

        if not clean_normalized:
            return CommandResult(is_command=False)

        for pattern, name, action, en_reply, hi_reply in self._compiled_patterns:
            if pattern.match(clean_normalized):
                # Pick localized response
                is_hindi_query = bool(re.search(r"[\u0900-\u097F]", clean_normalized)) or preferred_lang == "hi"
                reply = hi_reply if is_hindi_query else en_reply

                logger.info(f"⚡ Local command matched: [{name}] -> Action: [{action}]")
                return CommandResult(
                    is_command=True,
                    command_name=name,
                    action=action,
                    response_text=reply,
                    data={"matched_input": clean_normalized},
                )

        return CommandResult(is_command=False)


_command_router_instance = None


def get_command_router() -> CommandRouter:
    """Singleton getter for CommandRouter."""
    global _command_router_instance
    if _command_router_instance is None:
        _command_router_instance = CommandRouter()
    return _command_router_instance
