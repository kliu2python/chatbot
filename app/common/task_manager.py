"""
Task management system using Redis Queue (RQ) for handling chat requests.
"""
import redis
import rq
import json
import os
from typing import Dict, Any, Optional
from uuid import uuid4

# Redis connection
REDIS_HOST = os.getenv("REDIS_HOST", "10.160.13.16")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
task_queue = rq.Queue('chat_tasks', connection=redis_conn)


class TaskStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def queue_chat_request(question: str, session_id: str, top_k: int = 5, use_web_search: bool = True) -> str:
    """
    Queue a chat request for processing by a worker.

    Args:
        question: The user's question
        session_id: Session identifier
        top_k: Number of results to return
        use_web_search: Whether to use web search

    Returns:
        Task ID for tracking the request
    """
    task_id = str(uuid4())

    task_data = {
        "task_id": task_id,
        "question": question,
        "session_id": session_id,
        "top_k": top_k,
        "use_web_search": use_web_search,
        "status": TaskStatus.QUEUED
    }

    # Queue the task
    task_queue.enqueue(
        "app.worker.chat_worker.process_chat_request",
        task_data,
        job_id=task_id
    )

    return task_id


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the status of a queued task.

    Args:
        task_id: The task identifier

    Returns:
        Dictionary with task status and result if completed
    """
    try:
        job = task_queue.fetch_job(task_id)
        if not job:
            return None

        result = {
            "task_id": task_id,
            "status": job.get_status(),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        }

        if job.is_finished:
            result["result"] = job.result
            result["status"] = TaskStatus.COMPLETED
        elif job.is_failed:
            result["error"] = str(job.exc_info)
            result["status"] = TaskStatus.FAILED
        else:
            result["status"] = TaskStatus.PROCESSING

        return result
    except Exception:
        return None


def store_task_result(task_id: str, result: Dict[str, Any]) -> None:
    """
    Store the result of a completed task.

    Args:
        task_id: The task identifier
        result: The task result data
    """
    redis_conn.setex(f"task_result:{task_id}", 3600, json.dumps(result))  # Expire in 1 hour


def get_task_result(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve the result of a completed task.

    Args:
        task_id: The task identifier

    Returns:
        The task result data or None if not found
    """
    result = redis_conn.get(f"task_result:{task_id}")
    if result:
        return json.loads(result)
    return None