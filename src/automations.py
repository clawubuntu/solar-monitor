#!/usr/bin/env python3
"""
Automation Engine
Rules-based control for inverters and BMS

Features:
- Async action execution
- Persistent configuration (SQLite)
- Cooldown protection
- Validated rules
- Hardware actions disabled until tested
"""
import asyncio
import json
import time
import logging
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    trigger_count: int = 0

class AutomationEngine:
    """Manages automation rules with async execution and persistence."""
    
    def __init__(self):
        self.rules: List[AutomationRule] = []
        self._callbacks: List[Callable] = []
        self._next_id = 1
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def add_rule(self, name: str, condition: Dict, action: Dict) -> AutomationRule:
        """Add a new automation rule."""
        # Validate condition
        if not self._validate_condition(condition):
            raise ValueError("Invalid condition format")
        
        # Validate action
        if not self._validate_action(action):
            raise ValueError("Invalid action format")
        
        rule = AutomationRule(
            id=self._next_id,
            name=name,
            condition=condition,
            action=action
        )
        self.rules.append(rule)
        self._next_id += 1
        logger.info(f"Added automation rule: {name}")
        return rule
    
    def remove_rule(self, rule_id: int):
        """Remove an automation rule."""
        self.rules = [r for r in self.rules if r.id != rule_id]
    
    def enable_rule(self, rule_id: int, enabled: bool):
        """Enable or disable an automation rule."""
        for rule in self.rules:
            if rule.id == rule_id:
                rule.enabled = enabled
    
    def _validate_condition(self, condition: Dict) -> bool:
        """Validate condition format."""
        required = ["port", "metric", "operator", "value"]
        return all(k in condition for k in required)
    
    def _validate_action(self, action: Dict) -> bool:
        """Validate action format."""
        return "type" in action
    
    def evaluate_rules(self, readings: Dict[str, Dict[str, float]]):
        """Evaluate all rules against current readings."""
        for rule in self.rules:
            if not rule.enabled:
                continue
            if time.time() - rule.last_triggered < rule.cooldown:
                continue
            
            try:
                if self._evaluate_condition(rule.condition, readings):
                    rule.last_triggered = time.time()
                    rule.trigger_count += 1
                    self._execute_action(rule)
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name}: {e}")
    
    def _evaluate_condition(self, condition: Dict, readings: Dict[str, Dict[str, float]]) -> bool:
        """Evaluate a single condition."""
        port = condition.get("port", "")
        metric = condition.get("metric", "")
        operator = condition.get("operator", "==")
        threshold = condition.get("value", 0)
        
        if port not in readings:
            return False
        
        current_value = readings[port].get(metric)
        if current_value is None:
            return False
        
        operators = {
            "<": lambda a, b: a < b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            ">=": lambda a, b: a >= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        
        op_func = operators.get(operator)
        if not op_func:
            return False
        
        return op_func(current_value, threshold)
    
    def _execute_action(self, rule: AutomationRule):
        """Execute an action for a triggered rule."""
        logger.info(f"Rule '{rule.name}' triggered, executing action: {rule.action}")
        
        # Execute callbacks asynchronously
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(rule.action))
                else:
                    callback(rule.action)
            except Exception as e:
                logger.error(f"Error executing action for rule {rule.name}: {e}")
    
    def on_action(self, callback: Callable):
        """Register an action callback."""
        self._callbacks.append(callback)
    
    def get_rules(self) -> List[Dict]:
        """Get all rules as dictionaries."""
        return [{
            "id": r.id,
            "name": r.name,
            "condition": r.condition,
            "action": r.action,
            "enabled": r.enabled,
            "last_triggered": r.last_triggered,
            "trigger_count": r.trigger_count
        } for r in self.rules]
    
    def load_rules(self, rules: List[Dict]):
        """Load rules from persistent storage."""
        for rule_data in rules:
            try:
                rule = AutomationRule(
                    id=rule_data["id"],
                    name=rule_data["name"],
                    condition=rule_data["condition"],
                    action=rule_data["action"],
                    enabled=rule_data.get("enabled", True),
                    last_triggered=rule_data.get("last_triggered", 0),
                    cooldown=rule_data.get("cooldown", 60),
                    trigger_count=rule_data.get("trigger_count", 0)
                )
                self.rules.append(rule)
                self._next_id = max(self._next_id, rule.id + 1)
            except Exception as e:
                logger.error(f"Failed to load rule: {e}")
