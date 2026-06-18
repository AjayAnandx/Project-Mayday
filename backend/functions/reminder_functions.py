from backend.core.scheduler import get_scheduler
from backend.core.operation_log import get_operation_log


def create_reminder(message: str, datetime: str) -> str:
    rid, adjusted, stored_dt = get_scheduler().add_reminder(message, datetime)
    get_operation_log().record("create", "reminder", rid, message,
                                details={"datetime": stored_dt})
    if adjusted:
        return f"Reminder adjusted to 1 minute from now: '{message}' at {stored_dt} UTC (id: {rid}) — the requested time {datetime} was already in the past."
    return f"Reminder set: '{message}' at {stored_dt} UTC (id: {rid})"


def list_reminders() -> str:
    reminders = get_scheduler().list_reminders()
    if not reminders:
        return "No pending reminders."
    lines = [f"Pending reminders ({len(reminders)}):"]
    for r in reminders:
        lines.append(f"  - [{r['id']}] {r['message']} at {r['datetime']} UTC")
    return "\n".join(lines)


def delete_reminder(reminder_id: str) -> str:
    if get_scheduler().delete_reminder(reminder_id):
        get_operation_log().record("delete", "reminder", reminder_id, "")
        return f"Deleted reminder {reminder_id}"
    return f"Reminder {reminder_id} not found"
