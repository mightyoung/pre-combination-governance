"""Pure resource/call boundary predicates, prepared only."""


def may_launch(elapsed, charged_cpu_with_quota, reserved_calls, next_calls):
    return elapsed < 100 and charged_cpu_with_quota <= 56 and reserved_calls + next_calls <= 240


def stop_reason(elapsed, charged_cpu, controller_cpu, output_bytes, rss_values):
    if elapsed >= 100:
        return "wall"
    if charged_cpu > 56 or controller_cpu > 2.5:
        return "cpu"
    if output_bytes > 9 * 1024 * 1024:
        return "output"
    if not rss_values:
        return "monitor_unavailable"
    if max(rss_values) > 384 * 1024 * 1024 or sum(rss_values) > 1536 * 1024 * 1024:
        return "rss"
    return None
