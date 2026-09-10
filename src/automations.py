"""
Automation Engine
Rules-based control for inverters and BMS
"""
import asyncio
import time
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass

@dataclass
class AutomationRule:
    """Single automation rule"""
    id: int
    name: str
    condition: Dict
    action: Dict
    enabled: bool = True
    last_triggered: float = 0
    cooldown: float = 60

class AutomationEngine:
    """Manages automation rules"""
    
    def __init__(self):
        self.rules: List[AutomationRule] = []
        self._callbacks: List[Callable] = []
        self._next_id = 1
    
    def add_rule(self, name: str, condition: Dict, action: Dict) -> AutomationRule:
        rule = AutomationRule(
            id=self._next_id,
            name=name,
            condition=condition,
            action=action
        )
        self.rules.append(rule)
        self._next_id += 1
        return rule
    
    def remove_rule(self, rule_id: int):
        self.rules = [r for r in self.rules if r.id != rule_id]
    
    def enable_rule(self, rule_id: int, enabled: bool):
        for rule in self.rules:
            if rule.id == rule_id:
                rule.enabled = enabled
    
    def evaluate_rules(self, readings: Dict[str, Dict[str, float]]):
        for rule in self.rules:
            if not rule.enabled:
                continue
            if time.time() - rule.last_triggered < rule.cooldown:
                continue
            
            port = rule.condition.get("port", "")
            metric = rule.condition.get("metric", "")
            operator = rule.condition.get("operator", "==")
            threshold = rule.condition.get("value", 0)
            
            if port not in readings:
                continue
            
            current_value = readings[port].get(metric)
            if current_value is None:
                continue
            
            triggered = False
            if operator == "<":
                triggered = current_value < threshold
            elif operator == ">":
                triggered = current_value > threshold
            elif operator == "<=":
                triggered = current_value <= threshold
            elif operator == ">=":
                triggered = current_value >= threshold
            elif operator == "==":
                triggered = current_value == threshold
            elif operator == "!=":
                triggered = current_value != threshold
            
            if triggered:
                rule.last_triggered = time.time()
                self._execute_action(rule)
    
    def _execute_action(self, rule: AutomationRule):
        for callback in self._callbacks:
            try:
                callback(rule.action)
            except Exception:
                pass
    
    def on_action(self, callback: Callable):
        self._callbacks.append(callback)
    
    def get_rules(self) -> List[Dict]:
        return [{
            "id": r.id,
            "name": r.name,
            "condition": r.condition,
            "action": r.action,
            "enabled": r.enabled,
            "last_triggered": r.last_triggered
        } for r in self.rules]
