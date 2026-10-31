"""Prioritize the six approved P259-L04 language slots, without preemption.

The existing English Final is human-reviewed. This module only changes the
order in which the original Apps Script-authorized Kaggle worker checks
missing translations and publishes verified audio.
"""

PRIORITY_TASK_ID = "P259-L04"
PRIORITY_LANGUAGE_CODES = ("en", "th", "es", "id", "vi", "km")


def is_priority(task_id, language):
    return task_id == PRIORITY_TASK_ID and language in PRIORITY_LANGUAGE_CODES


def prioritize_translation_jobs(jobs):
    """Move L04's five AI languages first; retain other jobs' relative order."""
    return sorted(jobs, key=lambda job: not is_priority(job[0]["task_id"], job[2]))


def tts_job_passes(tasks):
    """Pass one: L04 six languages; pass two: everything else.

    Existing authorization, approved-language flags, QA, Drive revision and
    source-duration checks must still be applied by the caller.
    """
    jobs = list(tasks)
    return (
        [(task, True) for task in jobs if task["task_id"] == PRIORITY_TASK_ID]
        + [(task, False) for task in jobs]
    )
