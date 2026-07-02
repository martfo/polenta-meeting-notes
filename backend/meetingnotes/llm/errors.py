class LMStudioUnavailable(Exception):
    """LM Studio is not reachable or has no model loaded. Stages that need it
    leave the summary pending rather than failing the meeting."""
