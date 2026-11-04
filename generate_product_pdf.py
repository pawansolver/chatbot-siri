import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable,
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' in footer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Header
        self.drawString(45, 755, "AETHER AI • PHYSICAL SMART SPEAKER & MCP KNOWLEDGE APPLIANCE")
        self.drawRightString(567, 755, "PRODUCT SPECIFICATION & BOM")
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(45, 749, 567, 749)

        # Footer
        self.line(45, 38, 567, 38)
        self.drawString(45, 26, "Confidential — Engineering & Commercialization Blueprint • Powered by Gemini & MCP")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(567, 26, page_text)

        self.restoreState()


def create_product_pdf(output_filename="Aether_Smart_Speaker_Product_Specification.pdf"):
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=letter,
        leftMargin=45,
        rightMargin=45,
        topMargin=46,
        bottomMargin=46,
    )

    styles = getSampleStyleSheet()

    # Color Palette
    c_primary = colors.HexColor("#0f172a")    # Slate 900
    c_accent = colors.HexColor("#1d4ed8")     # Blue 700
    c_teal = colors.HexColor("#0f766e")       # Teal 700
    c_dark = colors.HexColor("#1e293b")       # Slate 800
    c_muted = colors.HexColor("#475569")      # Slate 600
    c_light_bg = colors.HexColor("#f8fafc")   # Slate 50
    c_blue_bg = colors.HexColor("#eff6ff")    # Blue 50

    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=c_primary,
        spaceAfter=3,
    )

    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=c_accent,
        spaceAfter=8,
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16,
        textColor=c_primary,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=c_accent,
        spaceBefore=5,
        spaceAfter=2,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.8,
        textColor=c_dark,
        spaceAfter=4,
    )

    bullet_style = ParagraphStyle(
        "Bullet_Custom",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2.5,
    )

    table_text = ParagraphStyle(
        "TableText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.8,
        textColor=c_dark,
    )

    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.8,
        textColor=colors.white,
    )

    callout_text = ParagraphStyle(
        "CalloutText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=c_dark,
    )

    story = []

    # =========================================================================
    # PAGE 1: TITLE, EXECUTIVE SUMMARY & ALL 4 PRODUCT USE CASES
    # =========================================================================
    story.append(Paragraph("AETHER AI PHYSICAL SMART SPEAKER APPLIANCE", title_style))
    story.append(Paragraph("Commercial Product Blueprint • Hardware Bill of Materials • MCP GitHub Knowledge Pipeline", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_accent, spaceBefore=0, spaceAfter=8))

    meta_table_data = [
        [
            Paragraph("<b>Target SBC:</b> Raspberry Pi Zero 2 W / Orange Pi / ESP32-S3", table_text),
            Paragraph("<b>Software Stack:</b> Python 3.11, FastAPI, SQLite, FastMCP", table_text),
            Paragraph("<b>AI Engine:</b> Google Gemini 2.5 Flash + Edge Neural TTS", table_text),
            Paragraph("<b>Hardware BOM:</b> ~Rs. 2,870 ($34 USD) per unit", table_text),
        ]
    ]
    meta_table = Table(meta_table_data, colWidths=[130, 130, 135, 127])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("1. Executive Summary & Core Value Proposition", h1_style))
    story.append(Paragraph(
        "Commercial smart speakers (Amazon Echo, Google Home) only provide generic internet web search results. "
        "They cannot converse with proprietary private repositories, company SOPs, or project documentation. "
        "<b>Aether AI Smart Speaker</b> bridges this gap by marrying an ultra-low-cost physical appliance with an open "
        "<b>Model Context Protocol (MCP)</b> engine connected to your <b>GitHub Knowledge Base</b>. "
        "When documentation is pushed to GitHub in Markdown, the physical speaker instantly learns the knowledge in real-time "
        "with <b>$0 database hosting fees</b> and <b>$0 cloud subscription lock-in</b>.",
        body_style
    ))

    callout_data = [[
        Paragraph(
            "<b>The Core Innovation:</b> Hands-free voice queries (Hindi/English/Hinglish) triggering real-time MCP tool "
            "calling to fetch and audibly explain private GitHub repository knowledge through a 3W physical speaker in under 2 seconds.",
            callout_text
        )
    ]]
    callout_table = Table(callout_data, colWidths=[522])
    callout_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_blue_bg),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor("#93c5fd")),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(callout_table)
    story.append(Spacer(1, 6))

    story.append(Paragraph("2. Product Lineup & Real-World Commercial Use Cases", h1_style))

    story.append(Paragraph("Product 1: 'DevDesk AI' — Software Engineer & Founder Desk Companion", h2_style))
    story.append(Paragraph(
        "A cylindrical desktop appliance next to a workstation monitor for hands-free codebase and architecture questions while coding.",
        body_style
    ))
    story.append(Paragraph("- <b>Target Audience:</b> Software Engineers, DevOps Engineers, Technical Founders, Freelancers.", bullet_style))
    story.append(Paragraph("- <b>Voice Query:</b> <i>'Aether, what is the payment timeout configured in our repo webhook?'</i>", bullet_style))
    story.append(Paragraph("- <b>Speaker Output:</b> <i>'According to settings.py in main branch, payment timeout is 15 seconds with 3 retries.'</i>", bullet_style))

    story.append(Paragraph("Product 2: 'OfficeBrain Kiosk' — B2B Internal Company Smart Speaker", h2_style))
    story.append(Paragraph(
        "Positioned in office meeting rooms, pantries, or reception areas to resolve employee HR policy, onboarding, and SOP questions.",
        body_style
    ))
    story.append(Paragraph("- <b>Target Audience:</b> Small & Medium Businesses (SMBs), Startups, Law Firms, Clinics, Coworking Spaces.", bullet_style))
    story.append(Paragraph("- <b>Voice Query:</b> <i>'Sick leave apply karne ka procedure kya hai aur approval kaun deta hai?'</i>", bullet_style))
    story.append(Paragraph("- <b>Speaker Output:</b> <i>'HR portal par apply karein; 2 din se zyada ke liye medical certificate required hai, aur direct manager approve karta hai.'</i>", bullet_style))

    story.append(Paragraph("Product 3: 'Showroom & Kiosk Assistant' — Interactive Product Demonstrator", h2_style))
    story.append(Paragraph(
        "Placed beside machines or retail demo displays to explain technical specs, warranty terms, and usage instructions directly from Git docs.",
        body_style
    ))
    story.append(Paragraph("- <b>Voice Query:</b> <i>'Is machine ka power consumption kitna hai aur warranty kitne saal ki hai?'</i>", bullet_style))

    story.append(Paragraph("Product 4: 'Personal Second Brain' — Obsidian & GitHub Notes Companion", h2_style))
    story.append(Paragraph(
        "A bedside or home office speaker that queries private markdown journal notes, book summaries, and daily goals on command.",
        body_style
    ))

    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: SYSTEM ARCHITECTURE & MCP PIPELINE
    # =========================================================================
    story.append(Paragraph("3. Technical Architecture & End-to-End Data Pipeline", h1_style))
    story.append(Paragraph(
        "The appliance runs a fully localized asynchronous pipeline engineered for sub-second response times, "
        "barge-in interruption, and offline persistence:",
        body_style
    ))

    arch_data = [
        [Paragraph("<b>Pipeline Stage</b>", table_header), Paragraph("<b>Component / Technology</b>", table_header), Paragraph("<b>Technical Function</b>", table_header)],
        [
            Paragraph("1. Audio Capture", table_text),
            Paragraph("INMP441 I2S MEMS Mic", table_text),
            Paragraph("Direct 24-bit digital capture at 16kHz PCM; eliminates analog hissing and ground loops.", table_text),
        ],
        [
            Paragraph("2. Voice Trigger / Button", table_text),
            Paragraph("GPIO 17 / Keyword Spotter", table_text),
            Paragraph("Single-tap tactile hardware button or continuous VAD voice trigger initiates listening.", table_text),
        ],
        [
            Paragraph("3. Speech-to-Text (STT)", table_text),
            Paragraph("Web Speech / Groq Whisper", table_text),
            Paragraph("Ultra-fast speech-to-text with multilingual Hindi, Hinglish, and English recognition.", table_text),
        ],
        [
            Paragraph("4. Local Command Router", table_text),
            Paragraph("Deterministic Regex Engine", table_text),
            Paragraph("Evaluates Stop, Mute, Volume, Clear locally in &lt;5ms ($0 API cost; bypasses cloud).", table_text),
        ],
        [
            Paragraph("5. AI Brain & Tool Decider", table_text),
            Paragraph("Google Gemini 2.5 Flash", table_text),
            Paragraph("Evaluates user intent. Emits an MCP tool call if query pertains to the GitHub repository.", table_text),
        ],
        [
            Paragraph("6. MCP Tool Execution", table_text),
            Paragraph("GitHub REST / FastMCP Client", table_text),
            Paragraph("Fetches target markdown doc from repository; feeds retrieved context back to Gemini.", table_text),
        ],
        [
            Paragraph("7. Neural Voice (TTS)", table_text),
            Paragraph("Microsoft Edge Neural TTS", table_text),
            Paragraph("Synthesizes human-like speech via hi-IN-Swara, en-IN-Neerja, or en-US-Ava ($0 Free).", table_text),
        ],
        [
            Paragraph("8. Audio Output & Amp", table_text),
            Paragraph("MAX98357A I2S Amp + 3W Spk", table_text),
            Paragraph("Class-D digital amplifier driving a 4Ω 3W speaker with instant barge-in cut-off.", table_text),
        ],
        [
            Paragraph("9. Data Persistence", table_text),
            Paragraph("Embedded SQLite 3 (WAL)", table_text),
            Paragraph("Saves conversation history, volume, and latency metrics locally on flash ($0 fee).", table_text),
        ],
    ]
    arch_table = Table(arch_data, colWidths=[105, 140, 277])
    arch_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(arch_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("4. MCP GitHub Knowledge Base Integration Mechanics", h1_style))
    story.append(Paragraph(
        "Aether integrates a dedicated FastMCP Client (<code>backend/mcp/github_kb.py</code>) exposing standard tool declarations to Gemini:",
        body_style
    ))
    story.append(Paragraph("• <b>Tool 1: <code>search_github_knowledge(query)</code></b> — Searches markdown files and documentation directories across your GitHub repository using fuzzy index and semantic keyword matching.", bullet_style))
    story.append(Paragraph("• <b>Tool 2: <code>read_github_document(file_path)</code></b> — Fetches exact file contents via GitHub REST API with an intelligent local RAM cache to avoid redundant API hits.", bullet_style))
    story.append(Paragraph("• <b>Tool 3: <code>list_knowledge_topics()</code></b> — Returns a summarized catalog of all indexed documentation files currently in the repository.", bullet_style))
    story.append(Paragraph(
        "<b>Zero Sync Overhead:</b> Whenever an engineer or manager pushes an update (<code>git push origin main</code>), "
        "the physical speaker immediately reflects the updated facts upon the very next voice query.",
        body_style
    ))

    # Architecture Diagram block
    ascii_data = [[
        Paragraph(
            "<font face='Courier' size='7'>"
            "USER VOICE  --[INMP441 I2S]-->  STT ENGINE  --[Text]-->  ASSISTANT CORE<br/>"
            "                                                              │<br/>"
            "   ┌──────────────────────────────────────────────────────────┘<br/>"
            "   ▼<br/>"
            "GEMINI 2.5 FLASH  --[Function Call]-->  MCP CLIENT  --[REST]-->  GITHUB REPO<br/>"
            "   ▲                                       │                      (Markdown Docs)<br/>"
            "   └─────────────────[Retrieved Context]───┘<br/>"
            "   │<br/>"
            "   ▼ [Natural Speech Answer]<br/>"
            "EDGE NEURAL TTS  --[Audio PCM]-->  MAX98357A I2S AMP  --[3W Output]-->  LOUDSPEAKER"
            "</font>",
            table_text
        )
    ]]
    ascii_table = Table(ascii_data, colWidths=[522])
    ascii_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#334155")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(ascii_table)

    story.append(PageBreak())

    # =========================================================================
    # PAGE 3: HARDWARE BOM & PINOUT WIRING
    # =========================================================================
    story.append(Paragraph("5. Hardware Bill of Materials (BOM) & Unit Costing", h1_style))
    story.append(Paragraph(
        "Complete component shopping list for manufacturing one standalone physical smart speaker. "
        "All parts are standard and in stock across Indian robotics suppliers (Robu.in, Robocraze, ElectronicsComp) and Amazon:",
        body_style
    ))

    bom_data = [
        [
            Paragraph("<b>Component</b>", table_header),
            Paragraph("<b>Recommended Model</b>", table_header),
            Paragraph("<b>Price (INR)</b>", table_header),
            Paragraph("<b>Price (USD)</b>", table_header),
            Paragraph("<b>Sourcing & Function Notes</b>", table_header),
        ],
        [
            Paragraph("1. Single Board Computer", table_text),
            Paragraph("Raspberry Pi Zero 2 W (Header Pin)", table_text),
            Paragraph("Rs. 1,650", table_text),
            Paragraph("$19.50", table_text),
            Paragraph("Quad-core 64-bit ARM, Wi-Fi 4, runs Linux/Python", table_text),
        ],
        [
            Paragraph("2. Digital Microphone", table_text),
            Paragraph("INMP441 I2S MEMS Mic Module", table_text),
            Paragraph("Rs. 140", table_text),
            Paragraph("$1.70", table_text),
            Paragraph("Ultra-low noise digital 24-bit audio capture", table_text),
        ],
        [
            Paragraph("3. Audio DAC Amplifier", table_text),
            Paragraph("MAX98357A I2S Mono 3W Amp", table_text),
            Paragraph("Rs. 160", table_text),
            Paragraph("$1.90", table_text),
            Paragraph("Class-D digital amplifier; high power efficiency", table_text),
        ],
        [
            Paragraph("4. Loudspeaker", table_text),
            Paragraph("4 Ohm (4Ω) / 3W 40mm Driver", table_text),
            Paragraph("Rs. 85", table_text),
            Paragraph("$1.00", table_text),
            Paragraph("Optimized for vocal clarity and crisp speech", table_text),
        ],
        [
            Paragraph("5. Visual Status Ring", table_text),
            Paragraph("WS2812B NeoPixel 8-LED Ring", table_text),
            Paragraph("Rs. 130", table_text),
            Paragraph("$1.55", table_text),
            Paragraph("RGB state indicator (Blue, Violet, Green, Red)", table_text),
        ],
        [
            Paragraph("6. Tactile Push Button", table_text),
            Paragraph("12mm Tactile Button + Cap", table_text),
            Paragraph("Rs. 15", table_text),
            Paragraph("$0.20", table_text),
            Paragraph("Tap-to-Talk, Cancel audio, and Mic Mute", table_text),
        ],
        [
            Paragraph("7. Flash Memory Storage", table_text),
            Paragraph("SanDisk 32GB Class 10 MicroSD", table_text),
            Paragraph("Rs. 280", table_text),
            Paragraph("$3.35", table_text),
            Paragraph("Houses OS, Python virtualenv & SQLite DB", table_text),
        ],
        [
            Paragraph("8. Connecting Jumpers", table_text),
            Paragraph("Female-to-Female Wires (15 pcs)", table_text),
            Paragraph("Rs. 40", table_text),
            Paragraph("$0.50", table_text),
            Paragraph("Pin-to-pin wiring (No soldering required for prototype)", table_text),
        ],
        [
            Paragraph("9. Power Supply Adapter", table_text),
            Paragraph("5V 2.5A Micro-USB Supply", table_text),
            Paragraph("Rs. 190", table_text),
            Paragraph("$2.25", table_text),
            Paragraph("Stable continuous 24/7 electrical feed", table_text),
        ],
        [
            Paragraph("10. Enclosure Chassis", table_text),
            Paragraph("3D-Printed Cylindrical Box", table_text),
            Paragraph("Rs. 180", table_text),
            Paragraph("$2.15", table_text),
            Paragraph("Acoustic speaker cavity + mic port + LED top diffuser", table_text),
        ],
        [
            Paragraph("<b>TOTAL PROTOTYPE BOM</b>", table_header),
            Paragraph("<b>Complete Turnkey Unit</b>", table_header),
            Paragraph("<b>Rs. 2,870</b>", table_header),
            Paragraph("<b>$34.10</b>", table_header),
            Paragraph("<b>Fully Functional Hardware Smart Speaker</b>", table_header),
        ],
    ]
    bom_table = Table(bom_data, colWidths=[105, 140, 60, 55, 162])
    bom_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, c_light_bg]),
        ('BACKGROUND', (0, -1), (-1, -1), c_accent),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(bom_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("6. Hardware Pinout & Wiring Connection Map", h1_style))
    story.append(Paragraph(
        "The INMP441 Microphone and MAX98357A Amplifier share the common I2S audio bus clock lines on the Pi Zero 2 W 40-pin header:",
        body_style
    ))

    pinout_data = [
        [Paragraph("<b>Peripheral Module</b>", table_header), Paragraph("<b>Module Pin</b>", table_header), Paragraph("<b>Pi Zero 2W Pin</b>", table_header), Paragraph("<b>Signal / Function</b>", table_header)],
        [Paragraph("INMP441 (Microphone)", table_text), Paragraph("VDD", table_text), Paragraph("Pin 1 (3.3V)", table_text), Paragraph("Power Supply (3.3V Logic ONLY - Never connect 5V)", table_text)],
        [Paragraph("INMP441 (Microphone)", table_text), Paragraph("GND & L/R", table_text), Paragraph("Pin 9 (GND)", table_text), Paragraph("Ground / Left Channel Audio Select", table_text)],
        [Paragraph("INMP441 (Microphone)", table_text), Paragraph("SCK", table_text), Paragraph("Pin 12 (GPIO 18)", table_text), Paragraph("I2S Bit Clock (Shared BCLK)", table_text)],
        [Paragraph("INMP441 (Microphone)", table_text), Paragraph("WS", table_text), Paragraph("Pin 35 (GPIO 19)", table_text), Paragraph("I2S Word Select / LR Clock (Shared LRCK)", table_text)],
        [Paragraph("INMP441 (Microphone)", table_text), Paragraph("SD", table_text), Paragraph("Pin 38 (GPIO 20)", table_text), Paragraph("I2S Data Input (Microphone PCM stream)", table_text)],
        [Paragraph("MAX98357A (Amplifier)", table_text), Paragraph("Vin", table_text), Paragraph("Pin 2 (5V)", table_text), Paragraph("5V High-Output Power Supply", table_text)],
        [Paragraph("MAX98357A (Amplifier)", table_text), Paragraph("GND", table_text), Paragraph("Pin 6 (GND)", table_text), Paragraph("Power Ground", table_text)],
        [Paragraph("MAX98357A (Amplifier)", table_text), Paragraph("BCLK", table_text), Paragraph("Pin 12 (GPIO 18)", table_text), Paragraph("I2S Bit Clock (Shared with Mic)", table_text)],
        [Paragraph("MAX98357A (Amplifier)", table_text), Paragraph("LRC", table_text), Paragraph("Pin 35 (GPIO 19)", table_text), Paragraph("I2S Word Select (Shared with Mic)", table_text)],
        [Paragraph("MAX98357A (Amplifier)", table_text), Paragraph("DIN", table_text), Paragraph("Pin 40 (GPIO 21)", table_text), Paragraph("I2S Audio Output to Speaker", table_text)],
        [Paragraph("Tactile Push Button", table_text), Paragraph("Pin 1 & 2", table_text), Paragraph("Pin 11 (GPIO 17) & GND", table_text), Paragraph("Active-Low Tap-to-Talk / Mute trigger", table_text)],
        [Paragraph("WS2812B LED Ring", table_text), Paragraph("5V, GND, DIN", table_text), Paragraph("Pin 4 (5V), Pin 20, Pin 32", table_text), Paragraph("PWM Controlled NeoPixel State Ring (GPIO 12)", table_text)],
    ]
    pinout_table = Table(pinout_data, colWidths=[115, 80, 115, 212])
    pinout_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(pinout_table)

    story.append(PageBreak())

    # =========================================================================
    # PAGE 4: OPERATIONAL COSTS, COMMERCIALIZATION & NEXT STEPS
    # =========================================================================
    story.append(Paragraph("7. Operational Cloud & API Costs (Zero-Cost Blueprint)", h1_style))
    story.append(Paragraph(
        "Aether AI is engineered for zero-to-negligible operating costs by leveraging free-tier APIs and local embedded compute:",
        body_style
    ))

    cost_data = [
        [Paragraph("<b>Service / Resource</b>", table_header), Paragraph("<b>Provider & Model</b>", table_header), Paragraph("<b>Free Tier Limit</b>", table_header), Paragraph("<b>Monthly Cost (INR / USD)</b>", table_header)],
        [
            Paragraph("AI Brain (LLM)", table_text),
            Paragraph("Google Gemini 2.5 Flash", table_text),
            Paragraph("15 RPM / 1M TPM 100% Free", table_text),
            Paragraph("Rs. 0 (Free) or ~Rs. 80/mo at scale", table_text),
        ],
        [
            Paragraph("Speech-to-Text (STT)", table_text),
            Paragraph("Browser Web Speech / Groq", table_text),
            Paragraph("Unlimited / Free Tier", table_text),
            Paragraph("Rs. 0 (100% Free)", table_text),
        ],
        [
            Paragraph("Neural TTS Voice", table_text),
            Paragraph("Microsoft Edge Neural TTS", table_text),
            Paragraph("Unlimited Multilingual", table_text),
            Paragraph("Rs. 0 (100% Free)", table_text),
        ],
        [
            Paragraph("Knowledge Base Tool", table_text),
            Paragraph("GitHub REST API / MCP", table_text),
            Paragraph("5,000 requests/hour free", table_text),
            Paragraph("Rs. 0 (100% Free)", table_text),
        ],
        [
            Paragraph("Database Persistence", table_text),
            Paragraph("Embedded SQLite 3 (WAL)", table_text),
            Paragraph("Local Flash Storage", table_text),
            Paragraph("Rs. 0 (100% Free)", table_text),
        ],
        [
            Paragraph("Appliance OS & Services", table_text),
            Paragraph("Raspberry Pi OS (Bookworm)", table_text),
            Paragraph("Open Source Linux", table_text),
            Paragraph("Rs. 0 (100% Free)", table_text),
        ],
        [
            Paragraph("<b>TOTAL MONTHLY RUN COST</b>", table_header),
            Paragraph("<b>1,000 Voice Queries / Month</b>", table_header),
            Paragraph("<b>Standard Daily Usage</b>", table_header),
            Paragraph("<b>Rs. 0 – Rs. 80 / mo ($0 – $1.00)</b>", table_header),
        ],
    ]
    cost_table = Table(cost_data, colWidths=[120, 130, 125, 147])
    cost_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_teal),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, c_light_bg]),
        ('BACKGROUND', (0, -1), (-1, -1), c_primary),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(cost_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("8. Commercial Pricing Strategy & Profit Margins", h1_style))
    story.append(Paragraph(
        "Commercialization economics when packaging and selling Aether Smart Speaker as a finished hardware appliance:",
        body_style
    ))

    biz_data = [
        [Paragraph("<b>Product Edition</b>", table_header), Paragraph("<b>Hardware BOM</b>", table_header), Paragraph("<b>Retail Price</b>", table_header), Paragraph("<b>Gross Margin (INR)</b>", table_header), Paragraph("<b>Profit Margin (%)</b>", table_header)],
        [
            Paragraph("DevDesk AI (DIY Maker Kit)", table_text),
            Paragraph("Rs. 2,870", table_text),
            Paragraph("Rs. 5,999 ($72)", table_text),
            Paragraph("Rs. 3,129 per unit", table_text),
            Paragraph("<b>52.1%</b>", table_text),
        ],
        [
            Paragraph("DevDesk AI (Assembled Box)", table_text),
            Paragraph("Rs. 3,100", table_text),
            Paragraph("Rs. 7,999 ($95)", table_text),
            Paragraph("Rs. 4,899 per unit", table_text),
            Paragraph("<b>61.2%</b>", table_text),
        ],
        [
            Paragraph("OfficeBrain B2B Appliance", table_text),
            Paragraph("Rs. 3,500", table_text),
            Paragraph("Rs. 14,999 ($178)", table_text),
            Paragraph("Rs. 11,499 per unit", table_text),
            Paragraph("<b>76.6%</b>", table_text),
        ],
    ]
    biz_table = Table(biz_data, colWidths=[140, 75, 95, 120, 92])
    biz_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_accent),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_light_bg]),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(biz_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("9. Production Roadmap & Turnkey Deployment Steps", h1_style))
    story.append(Paragraph("<b>Step 1: Local Verification on Windows (Current Phase):</b> Validate Gemini function calling with your GitHub MCP tools and SQLite session persistence locally.", bullet_style))
    story.append(Paragraph("<b>Step 2: Component Procurement:</b> Order Raspberry Pi Zero 2 W, INMP441, MAX98357A, and 4Ω 3W mini speaker from Robu.in / Robocraze (~Rs. 2,870).", bullet_style))
    story.append(Paragraph("<b>Step 3: Hardware Assembly & Jumper Pinning:</b> Connect the 10 jumper wires according to Section 6 pinout map; snap into a 3D-printed cylindrical enclosure.", bullet_style))
    story.append(Paragraph("<b>Step 4: 1-Command Automated Installation:</b> Flash Raspberry Pi OS (Bookworm 64-bit Lite) and execute <code>bash scripts/setup_appliance.sh</code>. The system registers a <code>systemd</code> auto-boot daemon.", bullet_style))
    story.append(Paragraph("<b>Step 5: GitHub Knowledge Base Linkage:</b> Add markdown documentation into your GitHub repository. The speaker instantly answers queries in natural voice!", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"SUCCESS: PDF generated at {os.path.abspath(output_filename)}")

if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "Aether_Smart_Speaker_Product_Specification.pdf"
    create_product_pdf(out_file)
