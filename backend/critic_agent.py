"""Flat-import shim: exposes CriticAgent for use in backend/main.py."""

from app.agents.critic_agent import CriticAgent, CriticState

__all__ = ["CriticAgent", "CriticState"]

