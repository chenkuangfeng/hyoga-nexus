"""Skill publishing, binding lookup and run-time reads (openspec 2026-11-04-skill-scripts).

Skills grant no permission. A read is allowed only when the Run's agent version binds the skill
to a version that is still active; every read re-checks the platform resource grant.
"""
