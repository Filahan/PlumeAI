"""Human-readable diff summaries between two versions of an `AutomationDocument`."""

from __future__ import annotations

from app.schemas.documents import ActionStep, AutomationDocument, ManualTrigger, Trigger

_WEEKDAYS_CRON_LABEL = "weekdays"


def describe_trigger(trigger: Trigger) -> str:
    """A short, lowercase, human phrase describing a trigger (for use mid-sentence)."""
    if isinstance(trigger, ManualTrigger):
        return "manual trigger"

    settings = trigger.settings
    if settings.mode == "interval":
        n = settings.every_minutes
        unit = "minute" if n == 1 else "minutes"
        return f"every {n} {unit}"

    cron = settings.cron or ""
    parts = cron.split()
    if len(parts) != 5:
        return f"cron schedule '{cron}'"
    minute, hour, dom, month, dow = parts

    time_part = None
    if minute.isdigit() and hour.isdigit():
        time_part = f"{int(hour):02d}:{int(minute):02d}"

    if time_part and dom == "*" and month == "*" and dow == "1-5":
        return f"{_WEEKDAYS_CRON_LABEL} at {time_part}"
    if time_part and dom == "*" and month == "*" and dow == "*":
        return f"daily at {time_part}"
    return f"cron schedule '{cron}'"


def diff_summary(old: AutomationDocument, new: AutomationDocument) -> list[str]:
    """Human-readable sentences summarizing what changed between `old` and `new`."""
    lines: list[str] = []

    if old.name != new.name:
        lines.append(f"Renamed '{old.name}' to '{new.name}'")

    if old.description != new.description:
        lines.append("Updated description")

    if old.model != new.model:
        lines.append(f"Changed model to {new.model.provider}/{new.model.model}")

    if old.trigger != new.trigger:
        lines.append(f"Changed trigger to {describe_trigger(new.trigger)}")

    old_by_id = {s.id: s for s in old.steps}
    new_by_id = {s.id: s for s in new.steps}

    for step in new.steps:
        if step.id in old_by_id:
            continue
        if isinstance(step, ActionStep):
            lines.append(
                f"Added step '{step.name}' ({step.settings.integration} · {step.settings.action})"
            )
        else:
            lines.append(f"Added step '{step.name}'")

    for step in old.steps:
        if step.id not in new_by_id:
            lines.append(f"Removed step '{step.name}'")

    old_common_order = [s.id for s in old.steps if s.id in new_by_id]
    new_common_order = [s.id for s in new.steps if s.id in old_by_id]
    if len(old_common_order) > 1 and old_common_order != new_common_order:
        lines.append("Reordered steps")

    for step_id, old_step in old_by_id.items():
        new_step = new_by_id.get(step_id)
        if new_step is None or old_step == new_step:
            continue
        renamed_only = (
            old_step.name != new_step.name
            and old_step.model_copy(update={"name": new_step.name}) == new_step
        )
        if renamed_only:
            lines.append(f"Renamed step '{old_step.name}' to '{new_step.name}'")
        else:
            lines.append(f"Updated step '{new_step.name}'")

    return lines
