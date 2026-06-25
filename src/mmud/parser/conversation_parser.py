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

# Unbracketed channels this server uses: "TheSysop gossips: msg",
# "Conan broadcasts: msg", "Merchant auctions: msg", "Krang yells, 'msg'",
# "Bob tells you ...". Verb-specific so bare "says" (shop signage) never matches.
_CHANNEL_RE = re.compile(
    r"^([\w'-]+(?: [\w'-]+)?)\s+"
    r"(gossips?|broadcasts?|auctions?|yells?|tells the group|tells you)"
    r"(?::|,)?\s*['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)


def _channel_for(verb: str) -> str:
    v = verb.lower()
    if v.startswith("gossip"):
        return "gossip"
    if v.startswith("broadcast"):
        return "broadcast"
    if v.startswith("auction"):
        return "auction"
    if v.startswith("yell"):
        return "shout"
    return "tell"   # "tells you" / "tells the group"

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

        # "Name gossips: text" / "Name broadcasts: text" / "Name yells, 'text'" / ...
        if m := _CHANNEL_RE.match(line):
            sender = m.group(1).strip()
            if sender.lower() != "you":   # not our own echo
                return ConversationMessage(channel=_channel_for(m.group(2)),
                                           sender=sender, text=m.group(3).strip())

        return None
