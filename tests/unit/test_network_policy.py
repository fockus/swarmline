"""Tests for EgressRule input validation — security hardening.

Covers:
  - Destination injection string rejected (ValueError)
  - Unknown / injected protocol rejected (ValueError)
  - Out-of-range port (0 and 70000) rejected (ValueError)
  - Valid IP ("8.8.8.8") and CIDR ("10.0.0.0/8") accepted without error
"""

from __future__ import annotations

import pytest


class TestEgressRuleValidation:
    def test_egress_rule_rejects_destination_injection(self) -> None:
        """Injection string in destination field raises ValueError at construction."""
        from swarmline.tools.network_policy import EgressAction, EgressRule

        with pytest.raises(ValueError):
            EgressRule(
                action=EgressAction.ALLOW,
                destination="0.0.0.0/0 -j ACCEPT #",
                protocol="tcp",
                port=443,
            )

    def test_egress_rule_rejects_unknown_protocol(self) -> None:
        """Protocol not in {tcp, udp, all} raises ValueError at construction."""
        from swarmline.tools.network_policy import EgressAction, EgressRule

        with pytest.raises(ValueError):
            EgressRule(
                action=EgressAction.ALLOW,
                destination="10.0.0.0/8",
                protocol="tcp; rm -rf /",
            )

    def test_egress_rule_rejects_out_of_range_port(self) -> None:
        """Port values 0 and 70000 each raise ValueError at construction."""
        from swarmline.tools.network_policy import EgressAction, EgressRule

        with pytest.raises(ValueError):
            EgressRule(
                action=EgressAction.ALLOW,
                destination="10.0.0.0/8",
                protocol="tcp",
                port=70000,
            )

        with pytest.raises(ValueError):
            EgressRule(
                action=EgressAction.ALLOW,
                destination="10.0.0.0/8",
                protocol="tcp",
                port=0,
            )

    def test_egress_rule_accepts_valid_ip_and_cidr(self) -> None:
        """Plain IP and CIDR destinations construct without error."""
        from swarmline.tools.network_policy import EgressAction, EgressRule

        rule_ip = EgressRule(
            action=EgressAction.ALLOW,
            destination="8.8.8.8",
            protocol="udp",
            port=53,
        )
        assert rule_ip.destination == "8.8.8.8"

        rule_cidr = EgressRule(
            action=EgressAction.ALLOW,
            destination="10.0.0.0/8",
            protocol="tcp",
        )
        assert rule_cidr.destination == "10.0.0.0/8"
