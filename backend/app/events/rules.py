"""Alert rules: WHEN an event type occurs, IF the filters match, THEN take the actions.

Matching is a pure function of the event. Cooldown and de-duplication (in the event
processor) decide whether a match opens a new alert or is folded into an open one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import tzinfo

from app.ai.classes import expand_classes
from app.events.types import Event
from app.schemas.scene import AlertRuleConfig, DedupScope


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    config: AlertRuleConfig
    object_classes: frozenset[str]  # group names such as "vehicle" already expanded


class RuleEngine:
    def __init__(self, rules: Sequence[AlertRuleConfig], tz: tzinfo) -> None:
        self._tz = tz
        self._rules = [
            _CompiledRule(rule, frozenset(expand_classes(rule.object_classes)))
            for rule in rules
            if rule.enabled
        ]

    def match(self, event: Event) -> list[AlertRuleConfig]:
        return [r.config for r in self._rules if self._matches(r, event)]

    def _matches(self, compiled: _CompiledRule, event: Event) -> bool:
        rule = compiled.config
        if event.event_type not in rule.event_types:
            return False
        if rule.zones and event.zone_id not in rule.zones:
            return False
        if rule.lines and event.line_id not in rule.lines:
            return False
        if compiled.object_classes and event.object_class not in compiled.object_classes:
            return False
        if (
            rule.min_confidence is not None
            and event.confidence is not None
            and event.confidence < rule.min_confidence
        ):
            return False
        return rule.schedule is None or rule.schedule.is_active(
            event.occurred_at.astimezone(self._tz)
        )

    @staticmethod
    def dedup_key(rule: AlertRuleConfig, event: Event) -> str:
        """Events with the same key share one alert during the rule's cooldown."""
        match rule.dedup_scope:
            case DedupScope.TRACK:
                scope = f"track:{event.track_id}"
            case DedupScope.ZONE:
                scope = f"area:{event.zone_id or event.line_id or '-'}"
            case DedupScope.CAMERA:
                scope = f"camera:{event.camera_id}"
            case _:
                scope = "rule"
        return f"{rule.id}|{scope}"
