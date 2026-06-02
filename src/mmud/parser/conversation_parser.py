from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class ConversationMessage:
    channel: str   # "tell" | "shout" | "party" | "gossip" | "auction" | "gang"
    sender: str
    text: str


# "[BumbleBee tells you] hey there!"
_BRACKET_TELL_RE = re.compile(r"^\[(\w[\w\s]*?)\s+tells?\s+you\]\s+(.+)$", re.IGNORECASE)

# "[Shout] DarkStar: LFG!"  "[Party] Krang: need heal"  "[Gossip] ..."
_BRACKET_CHANNEL_RE = re.compile(
    r"^\[(Shout|Party|Gossip|Auction|Gang|Broadcast|Tell)\]\s+(\w[\w\s]*?):\s+(.+)$",
    re.IGNORECASE,
)

# "BumbleBee tells you, 'hello'"
_OLD_TELL_RE = re.compile(r"^(\w[\w\s]+?)\s+tells?\s+you,?\s+['\"](.+)['\"]$", re.IGNORECASE)

# "Someone shouts, 'help!'"  — anonymous, skip the sender mystery
_SHOUT_RE = re.compile(r"^(\w[\w\s]+?)\s+shouts?,?\s+['\"](.+)['\"]$", re.IGNORECASE)

# Skip own echoes
_OWN_ECHO_RE = re.compile(r"^You\s+(say|shout|tell|yell|sing)\b", re.IGNORECASE)


class ConversationParser:
    def parse(self, line: str) -> ConversationMessage | None:
        line = line.strip()
        if not line:
            return None
        if _OWN_ECHO_RE.match(line):
            return None

        # "[BumbleBee tells you] hey!"
        if m := _BRACKET_TELL_RE.match(line):
            return ConversationMessage(channel="tell", sender=m.group(1).strip(), text=m.group(2).strip())

        # "[Shout] Name: text"
        if m := _BRACKET_CHANNEL_RE.match(line):
            return ConversationMessage(
                channel=m.group(1).lower(),
                sender=m.group(2).strip(),
                text=m.group(3).strip(),
            )

        # "Name tells you, 'text'"
        if m := _OLD_TELL_RE.match(line):
            return ConversationMessage(channel="tell", sender=m.group(1).strip(), text=m.group(2).strip())

        # "Name shouts, 'text'"
        if m := _SHOUT_RE.match(line):
            sender = m.group(1).strip()
            if sender.lower() != "someone":
                return ConversationMessage(channel="shout", sender=sender, text=m.group(2).strip())

        return None
