#!/usr/bin/env python3
import os
import sys
import multiprocessing
from pathlib import Path

# Add the project root to the Python path
# Handle both local development and container environments
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Also add the parent of project root for container environments where app is nested
parent_of_project_root = project_root.parent
if str(parent_of_project_root) not in sys.path:
    sys.path.insert(0, str(parent_of_project_root))

import uvicorn
import asyncio
import signal

def run_http_server():
    """Run HTTP server"""
    uvicorn.run(
        "app.api.server:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )

def run_https_server():
    """Run HTTPS server"""
    # Get SSL certificate paths from environment variables
    ssl_cert_file = os.environ.get('SSL_CERT_FILE')
    ssl_key_file = os.environ.get('SSL_KEY_FILE')

    # Check if SSL files exist
    if ssl_cert_file and ssl_key_file and \
       os.path.exists(ssl_cert_file) and os.path.exists(ssl_key_file):
        print(f"Starting HTTPS server with SSL enabled")
        print(f"SSL Certificate: {ssl_cert_file}")
        print(f"SSL Key: {ssl_key_file}")

        uvicorn.run(
            "app.api.server:app",
            host="0.0.0.0",
            port=8443,
            reload=True,
            ssl_certfile=ssl_cert_file,
            ssl_keyfile=ssl_key_file,
        )
    else:
        print("Not starting HTTPS server - SSL files not found or not properly configured")

def main():
    # Get SSL certificate paths from environment variables
    ssl_cert_file = os.environ.get('SSL_CERT_FILE')
    ssl_key_file = os.environ.get('SSL_KEY_FILE')

    # Check if SSL files exist
    ssl_enabled = ssl_cert_file and ssl_key_file and \
                  os.path.exists(ssl_cert_file) and os.path.exists(ssl_key_file)

    if ssl_enabled:
        print("Starting both HTTP and HTTPS servers")
        # Run HTTPS server in a separate process
        https_process = multiprocessing.Process(target=run_https_server)
        https_process.start()

        # Run HTTP server in main process
        try:
            run_http_server()
        finally:
            # Terminate HTTPS process when main process exits
            https_process.terminate()
            https_process.join()
    else:
        print("Starting HTTP server only (no SSL)")
        if ssl_cert_file or ssl_key_file:
            print("Warning: SSL files not found or not properly configured")

        # Run HTTP only
        run_http_server()

if __name__ == "__main__":
    main()