#!/usr/bin/env python3
"""
VideoVoice Application Launcher

Starts both the backend (FastAPI) and frontend (Vite) servers.
"""
import subprocess
import time
import os
import sys
import signal
import socket

# Load .env file first
try:
    from dotenv import load_dotenv
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[Config] Loaded environment from {env_path}")
except ImportError:
    print("[Config] python-dotenv not installed, using system environment only")

# Configuration
BACKEND_HOST = os.environ.get("VIDEOVOICE_HOST", "0.0.0.0")
BACKEND_PORT = int(os.environ.get("VIDEOVOICE_PORT", "8000"))
FRONTEND_PORT = 5173
STARTUP_WAIT = 3  # seconds to wait before opening browser
OPEN_BROWSER = os.environ.get("VIDEOVOICE_NO_BROWSER", "").lower() != "true"


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def check_command_exists(command: str) -> bool:
    """Check if a command is available in PATH."""
    try:
        subprocess.run(
            [command, "--version"] if command != "npm" else [command, "-v"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=(os.name == 'nt')  # Use shell on Windows
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def wait_for_port(port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def main():
    print("=" * 50)
    print("  VideoVoice - AI Video Dubbing System")
    print("=" * 50)
    print()

    # Check prerequisites
    print("[Checking Prerequisites]")

    if not check_command_exists("uvicorn"):
        print("ERROR: uvicorn not found. Install with: pip install uvicorn")
        sys.exit(1)
    print("  ✓ uvicorn found")

    if not check_command_exists("npm"):
        print("ERROR: npm not found. Please install Node.js")
        sys.exit(1)
    print("  ✓ npm found")

    # Check if ports are available
    if is_port_in_use(BACKEND_PORT):
        print(f"WARNING: Port {BACKEND_PORT} is already in use")
        print(f"  Backend may already be running or another service is using this port")

    if is_port_in_use(FRONTEND_PORT):
        print(f"WARNING: Port {FRONTEND_PORT} is already in use")
        print(f"  Frontend may already be running or another service is using this port")

    print()

    # Get project paths
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(project_root, "frontend")

    if not os.path.exists(frontend_dir):
        print(f"ERROR: Frontend directory not found: {frontend_dir}")
        sys.exit(1)

    # Check if node_modules exists
    node_modules = os.path.join(frontend_dir, "node_modules")
    if not os.path.exists(node_modules):
        print("[Installing Frontend Dependencies]")
        print("  Running npm install...")
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=frontend_dir,
                shell=(os.name == 'nt'),
                check=True
            )
            print("  ✓ Dependencies installed")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to install dependencies: {e}")
            sys.exit(1)

    print()
    backend = None
    frontend = None

    try:
        # Start Backend
        print(f"[1/2] Starting Backend Server (port {BACKEND_PORT})...")
        backend = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "src.web.main:app",
                "--reload",
                "--host", BACKEND_HOST,
                "--port", str(BACKEND_PORT)
            ],
            cwd=project_root,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # Brief wait to check if backend started
        time.sleep(1)
        if backend.poll() is not None:
            print("ERROR: Backend failed to start")
            # Stdout is already printed
            sys.exit(1)
        print(f"  ✓ Backend starting on http://localhost:{BACKEND_PORT}")

        # Start Frontend
        print(f"[2/2] Starting Frontend (port {FRONTEND_PORT})...")
        frontend = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
            shell=(os.name == 'nt'),
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        time.sleep(1)
        if frontend.poll() is not None:
            print("ERROR: Frontend failed to start")
            stdout, _ = frontend.communicate(timeout=5)
            if stdout:
                print(stdout.decode('utf-8', errors='replace'))
            sys.exit(1)
        print(f"  ✓ Frontend starting on http://localhost:{FRONTEND_PORT}")

        print()
        print("=" * 50)
        print("  System Starting...")
        print("=" * 50)
        print()
        print(f"  Backend API:  http://localhost:{BACKEND_PORT}")
        print(f"  Frontend UI:  http://localhost:{FRONTEND_PORT}")
        print(f"  API Docs:     http://localhost:{BACKEND_PORT}/docs")
        print()
        print("  Press Ctrl+C to stop all servers")
        print()

        # Wait for services and open browser
        if OPEN_BROWSER:
            print(f"  Opening browser in {STARTUP_WAIT} seconds...")
            time.sleep(STARTUP_WAIT)

            if wait_for_port(FRONTEND_PORT, timeout=10):
                try:
                    import webbrowser
                    webbrowser.open(f"http://localhost:{FRONTEND_PORT}")
                except Exception as e:
                    print(f"  Could not open browser: {e}")
            else:
                print("  WARNING: Frontend not ready, skipping browser open")

        # Wait for processes
        backend.wait()
        frontend.wait()

    except KeyboardInterrupt:
        print()
        print("[Shutting Down]")

    finally:
        # Cleanup
        if backend and backend.poll() is None:
            print("  Stopping backend...")
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()

        if frontend and frontend.poll() is None:
            print("  Stopping frontend...")
            frontend.terminate()
            try:
                frontend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                frontend.kill()

        print("  ✓ All servers stopped")
        print()


if __name__ == "__main__":
    main()
