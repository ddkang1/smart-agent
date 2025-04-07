"""
Process management functionality for the Smart Agent CLI.
"""

import os
import sys
import time
import signal
import socket
import subprocess
import logging
import platform
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)


class ProcessManager:
    """
    Manages tool processes for the Smart Agent.

    This class handles starting, stopping, and managing tool processes
    for the Smart Agent CLI.
    """

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize the process manager.

        Args:
            config_dir: Directory for configuration files
        """
        self.config_dir = config_dir or os.path.join(os.path.expanduser("~"), ".smart_agent")
        self.pid_dir = os.path.join(self.config_dir, "pids")

        # Create directories if they don't exist
        os.makedirs(self.pid_dir, exist_ok=True)

    def is_port_in_use(self, port: int) -> bool:
        """
        Check if a port is in use.

        Args:
            port: Port number to check

        Returns:
            True if the port is in use, False otherwise
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

    def find_available_port(self, start_port: int = 8000, max_attempts: int = 100) -> int:
        """
        Find an available port starting from start_port.

        Args:
            start_port: Port to start checking from
            max_attempts: Maximum number of ports to check

        Returns:
            An available port number

        Raises:
            RuntimeError: If no available port is found
        """
        for port in range(start_port, start_port + max_attempts):
            if not self.is_port_in_use(port):
                return port

        raise RuntimeError(f"Could not find an available port after {max_attempts} attempts")

    def start_tool_process(
        self,
        tool_id: str,
        command: str,
        port: Optional[int] = None,
        background: bool = True
    ) -> Tuple[int, int]:
        """
        Start a tool process.

        Args:
            tool_id: ID of the tool
            command: Command to run
            port: Port to use (if None, find an available port)
            background: Whether to run in background

        Returns:
            Tuple of (process ID, port)
        """
        # Find an available port if not specified
        if port is None:
            port = self.find_available_port()

        # Replace {port} in the command with the actual port
        command = command.replace("{port}", str(port))

        # Start the process
        if background:
            # Use platform-specific approach for background processes
            if platform.system() == "Windows":
                # Windows approach
                process = subprocess.Popen(
                    command,
                    shell=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                # Unix approach - ensure process is fully detached but trackable
                # We'll use a special marker in the command to help us find it later
                marker = f"SMART_AGENT_TOOL_{tool_id}"
                marked_command = f"{command} # {marker}"

                # Start the process in a way that it continues running but we can still track it
                process = subprocess.Popen(
                    marked_command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,  # Close stdin to prevent any interaction
                    start_new_session=True     # Start a new session so it's not killed when the parent exits
                )
        else:
            # Foreground process
            process = subprocess.Popen(command, shell=True)

        # Save the PID
        pid = process.pid
        self._save_pid(tool_id, pid, port)

        logger.info(f"Started {tool_id} process with PID {pid} on port {port}")
        return pid, port

    def stop_tool_process(self, tool_id: str) -> bool:
        """
        Stop a tool process.

        Args:
            tool_id: ID of the tool

        Returns:
            True if the process was stopped, False otherwise
        """
        success = False
        marker = f"SMART_AGENT_TOOL_{tool_id}"

        # First try to stop the process using the marker
        try:
            if platform.system() == "Windows":
                # Windows approach - use tasklist, find, and taskkill
                # Find PIDs with our marker
                find_cmd = f'tasklist /FO CSV | findstr /C:"{marker}"'
                result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, text=True, check=False)
                if result.stdout.strip():
                    # Extract PIDs and kill them
                    for line in result.stdout.splitlines():
                        if marker in line:
                            parts = line.split(',')
                            if len(parts) > 1:
                                pid_str = parts[1].strip('"')
                                subprocess.call(['taskkill', '/F', '/T', '/PID', pid_str])
                                success = True
            else:
                # Unix approach - use ps, grep, and kill
                # Find processes with our marker
                find_cmd = f"ps -ef | grep '{marker}' | grep -v grep"
                result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, text=True, check=False)
                if result.stdout.strip():
                    # Extract PIDs and kill them
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) > 1:
                            pid_str = parts[1]
                            try:
                                pid = int(pid_str)
                                os.kill(pid, signal.SIGTERM)
                                success = True
                            except (ValueError, ProcessLookupError):
                                pass
        except Exception as e:
            logger.warning(f"Error stopping {tool_id} process using marker: {e}")

        # Fallback to PID-based approach
        pid_info = self._load_pid(tool_id)
        if pid_info:
            pid = pid_info.get("pid")
            if pid:
                try:
                    if platform.system() == "Windows":
                        # Windows approach
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
                    else:
                        # Unix approach - send SIGTERM to process group
                        try:
                            os.killpg(os.getpgid(pid), signal.SIGTERM)
                        except ProcessLookupError:
                            # If process group not found, try killing just the process
                            os.kill(pid, signal.SIGTERM)
                    success = True
                except ProcessLookupError:
                    logger.warning(f"Process {pid} for {tool_id} not found")
                except Exception as e:
                    logger.error(f"Error stopping {tool_id} process using PID: {e}")

        # Remove the PID file regardless of success
        self._remove_pid(tool_id)

        if success:
            logger.info(f"Stopped {tool_id} process")
            return True
        else:
            logger.warning(f"Failed to stop {tool_id} process")
            return False

    def stop_all_processes(self) -> Dict[str, bool]:
        """
        Stop all tool processes.

        Returns:
            Dictionary mapping tool IDs to success status
        """
        results = {}
        for pid_file in os.listdir(self.pid_dir):
            if pid_file.endswith(".pid"):
                tool_id = pid_file[:-4]  # Remove .pid extension
                results[tool_id] = self.stop_tool_process(tool_id)

        return results

    def is_tool_running(self, tool_id: str) -> bool:
        """
        Check if a tool process is running.

        Args:
            tool_id: ID of the tool

        Returns:
            True if the process is running, False otherwise
        """
        # First try to find the process using the marker
        marker = f"SMART_AGENT_TOOL_{tool_id}"

        try:
            if platform.system() == "Windows":
                # Windows approach - use tasklist and find
                result = subprocess.run(
                    ['tasklist', '/FO', 'CSV'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                return marker in result.stdout
            else:
                # Unix approach - use ps and grep
                result = subprocess.run(
                    ['ps', '-ef'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                return marker in result.stdout
        except Exception as e:
            logger.debug(f"Error checking if tool {tool_id} is running using marker: {e}")

        # Fallback to PID-based check
        pid_info = self._load_pid(tool_id)
        if not pid_info:
            return False

        pid = pid_info.get("pid")
        if not pid:
            return False

        # Check if the process is running
        try:
            if platform.system() == "Windows":
                # Windows approach
                subprocess.check_call(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            else:
                # Unix approach
                os.kill(pid, 0)  # Signal 0 doesn't kill the process, just checks if it exists
                return True
        except (subprocess.CalledProcessError, ProcessLookupError):
            # Process not found
            return False
        except Exception as e:
            # Other error
            logger.debug(f"Error checking if tool {tool_id} is running using PID: {e}")
            return False

    def get_tool_port(self, tool_id: str) -> Optional[int]:
        """
        Get the port for a tool process.

        Args:
            tool_id: ID of the tool

        Returns:
            Port number or None if not found
        """
        # First check if the tool is running
        if not self.is_tool_running(tool_id):
            return None

        # Get the port from the PID file
        pid_info = self._load_pid(tool_id)
        if pid_info and pid_info.get("port"):
            return pid_info.get("port")

        # Try to extract port from command line
        marker = f"SMART_AGENT_TOOL_{tool_id}"
        try:
            if platform.system() != "Windows":
                # Unix approach - use ps and grep
                find_cmd = f"ps -ef | grep '{marker}' | grep -v grep"
                result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, text=True, check=False)
                if result.stdout.strip():
                    # Look for --port or -p argument
                    for line in result.stdout.splitlines():
                        if "--port" in line:
                            parts = line.split("--port")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    return int(port_part)
                                except ValueError:
                                    pass
                        elif " -p " in line:
                            parts = line.split(" -p ")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    return int(port_part)
                                except ValueError:
                                    pass
        except Exception as e:
            logger.debug(f"Error extracting port from command line for {tool_id}: {e}")

        return None

    def _save_pid(self, tool_id: str, pid: int, port: int) -> None:
        """
        Save a PID to a file.

        Args:
            tool_id: ID of the tool
            pid: Process ID
            port: Port number
        """
        pid_file = os.path.join(self.pid_dir, f"{tool_id}.pid")
        with open(pid_file, "w") as f:
            f.write(f"{pid},{port}")

    def _load_pid(self, tool_id: str) -> Optional[Dict[str, int]]:
        """
        Load a PID from a file.

        Args:
            tool_id: ID of the tool

        Returns:
            Dictionary with PID and port, or None if not found
        """
        pid_file = os.path.join(self.pid_dir, f"{tool_id}.pid")
        if not os.path.exists(pid_file):
            return None

        try:
            with open(pid_file, "r") as f:
                content = f.read().strip()
                parts = content.split(",")
                if len(parts) >= 2:
                    return {"pid": int(parts[0]), "port": int(parts[1])}
                elif len(parts) == 1:
                    return {"pid": int(parts[0]), "port": None}
                else:
                    return None
        except Exception as e:
            logger.error(f"Error loading PID for {tool_id}: {e}")
            return None

    def _remove_pid(self, tool_id: str) -> None:
        """
        Remove a PID file.

        Args:
            tool_id: ID of the tool
        """
        pid_file = os.path.join(self.pid_dir, f"{tool_id}.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)
