"""NetworkPolicy — egress control for sandboxed agent execution.

Produces iptables OUTPUT chain rules from a declarative allow/deny rule list.

Usage::

    from swarmline.tools.network_policy import EgressAction, EgressRule, NetworkPolicy

    policy = NetworkPolicy(
        egress_rules=[
            EgressRule(action=EgressAction.ALLOW, destination="8.8.8.8",
                       protocol="udp", port=53),
        ],
        default_drop=True,
    )
    rules = policy.to_iptables_rules()
    # ['iptables -A OUTPUT -d 8.8.8.8 -p udp --dport 53 -j ACCEPT',
    #  'iptables -A OUTPUT -j DROP']

Rule ordering:
  Explicit rules are emitted in declaration order. The default-drop catch-all
  (if enabled) is always appended last so specific ACCEPT rules take effect
  before the blanket DROP.

Fly.io / Firecracker network policy adapters are SEPARATE optional packages,
NOT shipped here.

REQ-OSS-050: opt-in / additive.
REQ-OSS-051: zero product coupling — no tenant/workspace/FastAPI/SQLAlchemy.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import StrEnum

_ALLOWED_PROTOCOLS: frozenset[str] = frozenset({"tcp", "udp", "all"})


class EgressAction(StrEnum):
    """Action to take for matching egress traffic."""

    ALLOW = "ALLOW"
    DROP = "DROP"


@dataclass(frozen=True)
class EgressRule:
    """A single egress rule for iptables OUTPUT chain generation.

    Args:
        action:      ALLOW or DROP.
        destination: Destination CIDR or IP (e.g. "10.0.0.0/8", "8.8.8.8").
                     Must be a valid IP address or CIDR notation — hostnames
                     and injection strings are rejected at construction.
        protocol:    IP protocol: "tcp", "udp", or "all" (default).
                     When "all", no ``-p`` flag is emitted.
        port:        Destination port (1–65535). Only relevant for tcp/udp rules.
                     When None, no ``--dport`` flag is emitted.
    """

    action: EgressAction
    destination: str
    protocol: str = "all"
    port: int | None = None

    def __post_init__(self) -> None:
        """Validate all fields at construction — trust boundary enforcement."""
        try:
            ipaddress.ip_network(self.destination, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"EgressRule.destination must be a valid IP or CIDR, "
                f"got {self.destination!r}"
            ) from exc
        if self.protocol not in _ALLOWED_PROTOCOLS:
            raise ValueError(
                f"EgressRule.protocol must be one of {sorted(_ALLOWED_PROTOCOLS)}, "
                f"got {self.protocol!r}"
            )
        if self.port is not None and not (1 <= self.port <= 65535):
            raise ValueError(f"EgressRule.port must be in 1–65535, got {self.port!r}")


@dataclass
class NetworkPolicy:
    """Declarative egress network policy for a sandboxed environment.

    Converts a list of EgressRules to iptables OUTPUT chain rule strings
    via :meth:`to_iptables_rules`.

    Args:
        egress_rules:  Ordered list of egress rules. Rules are applied in
                       declaration order — first match wins at the kernel level.
        default_drop:  When True (recommended for production), append a
                       catch-all ``iptables -A OUTPUT -j DROP`` as the final
                       rule so any traffic not explicitly allowed is blocked.
    """

    egress_rules: list[EgressRule] = field(default_factory=list)
    default_drop: bool = True

    def to_iptables_rules(self) -> list[str]:
        """Generate iptables OUTPUT chain rules from the policy.

        Returns:
            Ordered list of iptables rule strings, ready to be passed to
            ``iptables`` (or ``ip6tables``) for application. The default-drop
            catch-all, if enabled, is always the last element.

        Examples:
            Allow DNS over UDP, then drop everything else::

                policy = NetworkPolicy(
                    egress_rules=[
                        EgressRule(EgressAction.ALLOW, "8.8.8.8", "udp", 53),
                    ],
                    default_drop=True,
                )
                policy.to_iptables_rules()
                # ['iptables -A OUTPUT -d 8.8.8.8 -p udp --dport 53 -j ACCEPT',
                #  'iptables -A OUTPUT -j DROP']
        """
        rules: list[str] = []

        for rule in self.egress_rules:
            if rule.action is EgressAction.ALLOW:
                parts = ["iptables -A OUTPUT", f"-d {rule.destination}"]
                if rule.protocol != "all":
                    parts.append(f"-p {rule.protocol}")
                if rule.port is not None:
                    parts.append(f"--dport {rule.port}")
                parts.append("-j ACCEPT")
                rules.append(" ".join(parts))

            elif rule.action is EgressAction.DROP:
                rules.append(f"iptables -A OUTPUT -d {rule.destination} -j DROP")

        if self.default_drop:
            rules.append("iptables -A OUTPUT -j DROP")

        return rules


__all__ = ["EgressAction", "EgressRule", "NetworkPolicy"]
