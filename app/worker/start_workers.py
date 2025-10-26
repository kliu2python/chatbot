"""
Script to start multiple worker processes for processing chat requests.
"""
import os
import sys
import logging
import multiprocessing
from pathlib import Path
from rq import Worker

# Add the project root to the Python path
# Handle both local development and container environments
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Also add the parent of project root for container environments where app is nested
parent_of_project_root = project_root.parent
if str(parent_of_project_root) not in sys.path:
    sys.path.insert(0, str(parent_of_project_root))

from app.common.task_manager import redis_conn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def start_worker(worker_id: int):
    """
    Start a worker process.

    Args:
        worker_id: Identifier for the worker process
    """
    logger.info(f"Starting worker {worker_id}")

    # Create worker
    worker = Worker(['chat_tasks'], connection=redis_conn)
    worker.work(logging_level='INFO')


def main():
    """Main function to start multiple worker processes."""
    # Get number of workers from environment variable or default to CPU count
    num_workers = int(os.getenv('NUM_WORKERS', multiprocessing.cpu_count()))

    logger.info(f"Starting {num_workers} worker processes")

    # Create and start worker processes
    processes = []
    for i in range(num_workers):
        process = multiprocessing.Process(target=start_worker, args=(i,))
        process.start()
        processes.append(process)

    # Wait for all processes to complete
    for process in processes:
        process.join()


if __name__ == '__main__':
    main()