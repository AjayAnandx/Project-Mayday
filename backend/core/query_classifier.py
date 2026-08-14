import re
from dataclasses import dataclass, field


@dataclass
class QueryIntent:
    intent: str
    confidence: float
    requires_llm: bool
    tool_choice: str
    active_sections: list[str] = field(default_factory=list)
    active_groups: list[str] = field(default_factory=list)


class QueryClassifier:

    def __init__(self):
        self._entries = [
            ("build", True, "auto",
             ["BASE", "PERSONALITY", "PROJECT", "BUILD"],
             ["basic", "project", "scaffold", "visual_test", "document", "design_mcp"],
             [r"\bbuild\s", r"\bcreate\s+(a|an)\s+(website|app|project|landing|page|site)",
              r"\bcreate\s+(a|an)\s+\w+\s+(app|project|site)\b",
              r"\bscaffold\b", r"\binit\s+(project|app|site)",
              r"\bset\s+up\s+(a\s+)?project", r"\bmake\s+(a\s+)?(website|app|site)"]),

            ("research", True, "auto",
             ["BASE", "PERSONALITY", "PROJECT", "BUILD", "RESEARCH", "DATA"],
             ["basic", "research", "data", "project"],
             [r"\bresearch\b", r"\binvestigate\b", r"\bfind\s+out\s+about\b",
              r"\blook\s+into\b", r"\bstudy\b", r"\banalyze\b", r"\bsurvey\b",
              r"\bgrowth\b", r"\btrend\b", r"\bover\s+time\b", r"\bcompare\b",
              r"\bversus\b", r"\bvs\.?\b", r"\bstatistics\b", r"\bchart\b"]),

            ("project", True, "auto",
             ["BASE", "PERSONALITY", "PROJECT"],
             ["basic", "project", "file"],
             [r"\b(resume|update|list|show)\s+(project|task)",
              r"\bproject\s+(status|note|task)", r"\badd\s+task\b",
              r"\bupdate\s+task\b", r"\bcreate_project\b", r"\blist_projects\b",
              r"\bcreate\s+project\b", r"\bnew\s+project\b"]),

            ("todo", True, "auto",
             ["BASE", "PERSONALITY", "PROJECT"],
             ["basic", "todo"],
             [r"\b(todo|task|remind|to\s*do)\b",
              r"\bcreate\s+(a\s+)?todo\b", r"\blist\s+(all\s+)?(todo|task)",
              r"\badd\s+(a\s+)?(todo|task|reminder)",
              r"\bmark\s+(as\s+)?(done|complete|finished)",
              r"\bwhat\s+(do\s+I\s+need|is\s+due|tasks)"]),

            ("calendar", True, "auto",
             ["BASE", "PERSONALITY", "PROJECT"],
             ["basic", "calendar"],
             [r"\bevent\b", r"\bcalendar\b", r"\bschedule\b", r"\bmeeting\b",
              r"\bappointment\b", r"\bwhat'?s\s+(on|upcoming|happening)",
              r"\badd\s+(an?\s+)?event\b", r"\bcreate\s+(an?\s+)?event\b"]),

            ("memory", True, "auto",
             ["BASE", "PERSONALITY"],
             ["basic", "memory", "conversation"],
             [r"\bremember\b", r"\brecall\b", r"\bforget\b",
              r"\bwhat\s+(do\s+you\s+know|did\s+I\s+say)",
              r"\btell\s+me\s+about\b", r"\bstore\s+(this|that)\b"]),

            ("system", True, "auto",
             ["BASE", "PERSONALITY"],
             ["basic", "system"],
             [r"\bopen\s+(app|application|program|chrome|notepad|calculator)",
              r"\bclose\s+(app|application)",
              r"\bvolume\s+(up|down|set|mute|0[-\s]?100)",
              r"\bset\s+volume\b", r"\bwhat(\'s| is)\s+(my\s+)?volume\b",
              r"\bclipboard\b", r"\bcopy\s+(to\s+)?clipboard",
              r"\bsystem\s+info\b", r"\bsystem\s+information\b"]),

            ("weather", True, "auto",
             ["BASE", "PERSONALITY", "WEATHER"],
             ["basic"],
             [r"\bweather\b", r"\bforecast\b", r"\brain\b",
              r"\btemperature\b", r"\bhumidity\b",
              r"\bhow\s+(hot|cold|warm)\b"]),

            ("simple_qa", True, "none",
             ["BASE", "PERSONALITY"],
             ["basic"],
             [r"\bwhat\s+(time|date|day)\b",
              r"\bwho\s+(are|made|created)\s+(you|mayday)",
              r"\bhow\s+(do\s+you|does\s+this|are\s+you)\b",
              r"\bwhere\s+(am\s+I|is)\b",
              r"\bwhy\s+(is|are|do|does)\b",
              r"\bcan\s+you\s+(help|tell|explain|show)\b"]),

            ("greeting", False, "none",
             ["BASE"],
             [],
             [r"^(hi|hello|hey|yo|sup|howdy|good\s+(morning|afternoon|evening))[\s!.]*$",
              r"^(thanks|thank\s+you|ty|thx)[\s!.]*$",
              r"^(bye|goodbye|cya|see\s+ya)[\s!.]*$",
              r"^what'?s\s+up[\s?!]*$",
              r"^how\s+(are\s+you|it\s+going)[\s?!]*$"]),
        ]

    def classify(self, text: str, is_first_message: bool = False) -> QueryIntent:
        text = text.strip()

        if is_first_message:
            return QueryIntent(
                intent="general",
                confidence=1.0,
                requires_llm=True,
                tool_choice="auto",
active_sections=["BASE", "PERSONALITY", "PROJECT", "BUILD", "RESEARCH", "DATA", "WEATHER"],
                active_groups=self._all_groups(),
            )

        for intent_name, requires_llm, tool_choice, sections, groups, patterns in self._entries:
            matches = sum(1 for p in patterns if re.search(p, text, re.I))
            if matches > 0:
                confidence = min(1.0, 0.3 + matches * 0.35)
                return QueryIntent(
                    intent=intent_name,
                    confidence=confidence,
                    requires_llm=requires_llm,
                    tool_choice=tool_choice,
                    active_sections=list(sections),
                    active_groups=list(groups),
                )

        return QueryIntent(
            intent="general",
            confidence=0.8,
            requires_llm=True,
            tool_choice="auto",
            active_sections=["BASE", "PERSONALITY", "PROJECT", "BUILD", "RESEARCH", "WEATHER"],
            active_groups=self._all_groups(),
        )

    def _all_groups(self) -> list[str]:
        return [
            "basic", "todo", "calendar", "memory", "conversation",
            "system", "file", "project", "scaffold", "visual_test",
            "document", "screenshot", "notification", "design_mcp",
            "opencode", "git", "github", "browser", "fetch",
        ]
