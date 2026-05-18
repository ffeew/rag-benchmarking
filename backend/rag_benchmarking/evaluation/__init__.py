"""In-process evaluation runner.

The API and CLI used to dispatch evaluations to a separate Celery worker.
They now run inside the API process: ``launch_evaluation_thread`` spawns
a daemon thread per evaluation that calls ``rag_evaluation.runner.run_evaluation``
directly. The previous broker, queue, and worker container are gone.
"""

from rag_benchmarking.evaluation.runner import (
    INPROC_TASK_PREFIX,
    inproc_thread_alive,
    is_inproc_task_id,
    launch_evaluation_thread,
)

__all__ = [
    "INPROC_TASK_PREFIX",
    "inproc_thread_alive",
    "is_inproc_task_id",
    "launch_evaluation_thread",
]
