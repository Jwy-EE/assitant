from __future__ import annotations

from dataclasses import dataclass


FORBIDDEN_PATTERNS = [
    "del /s",
    "rd /s",
    "rmdir /s",
    "remove-item -recurse",
    "rm -rf",
]

HIGH_RISK_WORDS = [
    "remove-item",
    "del ",
    "erase ",
    "git push",
    "git commit",
    "send-mailmessage",
    "shutdown",
    "format ",
    "set-executionpolicy",
]


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    risk: str
    requires_confirmation: bool
    reason: str


class PermissionBroker:
    def inspect_command(self, command: str) -> PermissionDecision:
        normalized = " ".join(command.lower().split())
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in normalized:
                return PermissionDecision(
                    allowed=False,
                    risk="L4",
                    requires_confirmation=True,
                    reason=f"Forbidden recursive or batch deletion pattern: {pattern}",
                )
        if any(word in normalized for word in HIGH_RISK_WORDS):
            return PermissionDecision(
                allowed=True,
                risk="L4",
                requires_confirmation=True,
                reason="High-risk command requires explicit confirmation.",
            )
        if any(word in normalized for word in ["new-item", "set-content", "python", "pip", "npm"]):
            return PermissionDecision(
                allowed=True,
                risk="L3",
                requires_confirmation=True,
                reason="Command may write files or run code.",
            )
        return PermissionDecision(
            allowed=True,
            risk="L1",
            requires_confirmation=False,
            reason="Read-only or low-risk command.",
        )

    def inspect_tool_intent(self, risk: str) -> PermissionDecision:
        if risk == "L4":
            return PermissionDecision(True, risk, True, "Sensitive action needs second confirmation.")
        if risk in {"L2", "L3"}:
            return PermissionDecision(True, risk, True, "Local file or execution action needs confirmation.")
        return PermissionDecision(True, risk or "L0", False, "Low-risk assistant action.")

