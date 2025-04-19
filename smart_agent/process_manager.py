"""
Process management functionality for the Smart Agent CLI.
"""

import os
import time
import signal
import socket
import subprocess
import logging
import platform
from typing import Dict, Optional, Tuple

# Set up logging
logger = logging.getLogger(__name__)


class ProcessManager:
    """
    Manages tool processes for the Smart Agent.

    This class handles starting, stopping, and managing tool processes
    for the Smart Agent CLI.
    """

    def __init__(self, config_dir: Optional[str] = None, debug: bool = False):
        """
        Initialize the process manager.

        Args:
            config_dir: Directory for configuration files
            debug: Enable debug mode for verbose logging
        """
        self.config_dir = config_dir or os.path.join(os.path.expanduser("~"), ".smart_agent")
        self.pid_dir = os.path.join(self.config_dir, "pids")
        self.debug = debug

        # Create directories if they don't exist
        os.makedirs(self.pid_dir, exist_ok=True)

        # Set up logging level based on debug flag
        if self.debug:
            logger.setLevel(logging.DEBUG)
            # Add a console handler if not already present
            if not logger.handlers:
                console_handler = logging.StreamHandler()
                console_handler.setLevel(logging.DEBUG)
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                console_handler.setFormatter(formatter)
                logger.addHandler(console_handler)

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
        background: bool = True,
        redirect_io: bool = True
    ) -> Tuple[int, int]:
        """
        Start a tool process.

        Args:
            tool_id: ID of the tool
            command: Command to run
            port: Port to use (if None, find an available port)
            background: Whether to run in background
            redirect_io: Whether to redirect stdin/stdout/stderr to DEVNULL

        Returns:
            Tuple of (process ID, port)
        """
        # Find an available port if not specified
        if port is None:
            port = self.find_available_port()

        # Replace {port} in the command with the actual port
        original_command = command
        command = command.replace("{port}", str(port))

        # Check if this is a Docker run command and add a consistent name
        if "docker run" in command:
            # Create a consistent container name based on tool_id
            container_name = f"smart_agent_{tool_id}"
            
            # Add the --name flag to the Docker command
            # We need to insert it after "docker run" but before the image name
            docker_run_pos = command.find("docker run")
            if docker_run_pos >= 0:
                # Find the position after "docker run"
                insert_pos = docker_run_pos + len("docker run")
                # Insert the --name flag
                command = f"{command[:insert_pos]} --name {container_name}{command[insert_pos:]}"
                
                if self.debug:
                    logger.debug(f"Added consistent name to Docker command: {container_name}")

        if self.debug:
            logger.debug(f"Command before port replacement: {original_command}")
            logger.debug(f"Command after port replacement: {command}")
            logger.debug(f"Final command to be executed: {command}")

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

                if self.debug:
                    logger.debug(f"Added marker to command: {marked_command}")

                # Start the process in a way that it continues running but we can still track it
                if redirect_io:
                    process = subprocess.Popen(
                        marked_command,
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,  # Close stdin to prevent any interaction
                        start_new_session=True     # Start a new session so it's not killed when the parent exits
                    )
                else:
                    # Don't redirect stdin/stdout/stderr for processes that need them
                    process = subprocess.Popen(
                        marked_command,
                        shell=True,
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
        
        # Timeout for graceful termination before force kill (seconds)
        termination_timeout = 3.0

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
                        # Unix approach - first send SIGTERM to process group, then SIGKILL if needed
                        try:
                            # Always start with SIGTERM for graceful shutdown
                            os.killpg(os.getpgid(pid), signal.SIGTERM)
                            logger.info(f"Sent SIGTERM to process group for {tool_id}")
                            
                            # Wait for the process to terminate gracefully
                            termination_start = time.time()
                            process_terminated = False
                            
                            while time.time() - termination_start < termination_timeout:
                                try:
                                    # Check if process still exists
                                    os.killpg(os.getpgid(pid), 0)  # Signal 0 just checks if process exists
                                    # Process still exists, wait a bit
                                    time.sleep(0.1)
                                except ProcessLookupError:
                                    # Process terminated
                                    process_terminated = True
                                    break
                            
                            # If process is still running after timeout, send SIGKILL
                            if not process_terminated:
                                logger.warning(f"Process {pid} for {tool_id} did not terminate within {termination_timeout}s, sending SIGKILL")
                                try:
                                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                                    logger.info(f"Sent SIGKILL to process group for {tool_id}")
                                except ProcessLookupError:
                                    # Process terminated between check and kill
                                    pass
                        except ProcessLookupError:
                            # If process group not found, try killing just the process
                            os.kill(pid, signal.SIGTERM)
                            logger.info(f"Sent SIGTERM to process {pid} for {tool_id}")
                            
                            # Wait for the process to terminate gracefully
                            termination_start = time.time()
                            process_terminated = False
                            
                            while time.time() - termination_start < termination_timeout:
                                try:
                                    # Check if process still exists
                                    os.kill(pid, 0)  # Signal 0 just checks if process exists
                                    # Process still exists, wait a bit
                                    time.sleep(0.1)
                                except ProcessLookupError:
                                    # Process terminated
                                    process_terminated = True
                                    break
                            
                            # If process is still running after timeout, send SIGKILL
                            if not process_terminated:
                                logger.warning(f"Process {pid} for {tool_id} did not terminate within {termination_timeout}s, sending SIGKILL")
                                try:
                                    os.kill(pid, signal.SIGKILL)
                                    logger.info(f"Sent SIGKILL to process {pid} for {tool_id}")
                                except ProcessLookupError:
                                    # Process terminated between check and kill
                                    pass
                    success = True
                except ProcessLookupError:
                    logger.warning(f"Process {pid} for {tool_id} not found")
                except Exception as e:
                    logger.error(f"Error stopping {tool_id} process using PID: {e}")

        # Try to stop Docker container with our consistent naming pattern
        container_name = f"smart_agent_{tool_id}"
        
        # Try to find and stop the Docker container with our consistent name
        find_cmd = f"docker ps -q --filter name={container_name}"
        result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        
        if result.stdout.strip():
            # Found a container with our naming pattern
            docker_container_id = result.stdout.strip()
            if self.debug:
                logger.debug(f"Found Docker container {docker_container_id} with name {container_name}")
                
            # Try to stop the container
            stop_cmd = f"docker stop {docker_container_id}"
            stop_result = subprocess.run(stop_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            
            if stop_result.returncode == 0:
                success = True
                logger.info(f"Stopped Docker container {docker_container_id} for {tool_id}")
            else:
                # Try to kill the container if stopping failed
                kill_cmd = f"docker kill {docker_container_id}"
                logger.info(f"Attempting to kill Docker container {docker_container_id} for {tool_id}")
                kill_result = subprocess.run(kill_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                
                if kill_result.returncode == 0:
                    success = True
                    logger.info(f"Killed Docker container {docker_container_id} for {tool_id}")
                else:
                    logger.warning(f"Failed to stop or kill Docker container {docker_container_id} for {tool_id}")

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
        if self.debug:
            logger.debug(f"Checking if tool {tool_id} is running")

        # Get the PID from the PID file
        pid_info = self._load_pid(tool_id)
        if self.debug:
            logger.debug(f"PID info for {tool_id}: {pid_info}")

        if not pid_info:
            if self.debug:
                logger.debug(f"No PID info found for {tool_id}")
            return False

        pid = pid_info.get("pid")
        if not pid:
            if self.debug:
                logger.debug(f"No PID found in PID info for {tool_id}")
            return False

        # Check if the process is running using the PID
        if self.debug:
            logger.debug(f"Checking if process with PID {pid} is running for {tool_id}")

        try:
            if platform.system() == "Windows":
                # Windows approach
                if self.debug:
                    result = subprocess.run(
                        ['tasklist', '/FI', f'PID eq {pid}'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    logger.debug(f"Tasklist output for PID {pid}: {result.stdout}")
                else:
                    subprocess.check_call(
                        ['tasklist', '/FI', f'PID eq {pid}'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                return True
            else:
                # Unix approach - check if process exists
                try:
                    # First try to check if the process exists
                    os.kill(pid, 0)  # Signal 0 doesn't kill the process, just checks if it exists
                    if self.debug:
                        logger.debug(f"Process with PID {pid} exists for {tool_id}")

                        # Get process details for debugging
                        ps_cmd = f"ps -p {pid} -o pid,ppid,cmd"
                        ps_result = subprocess.run(ps_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                        logger.debug(f"Process details for PID {pid}: {ps_result.stdout}")
                    return True
                except ProcessLookupError:
                    if self.debug:
                        logger.debug(f"Process with PID {pid} not found for {tool_id}")

                        # Try to find any processes with the tool ID in the command line
                        find_cmd = f"ps -ef | grep {tool_id} | grep -v grep"
                        find_result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                        if find_result.stdout.strip():
                            logger.debug(f"Found processes matching {tool_id}: {find_result.stdout}")
                        else:
                            logger.debug(f"No processes found matching {tool_id}")
                    return False
        except (subprocess.CalledProcessError, ProcessLookupError):
            # Process not found
            if self.debug:
                logger.debug(f"Process with PID {pid} not found for {tool_id}")
            return False
        except Exception as e:
            # Other error
            logger.debug(f"Error checking if tool {tool_id} is running: {e}")
            return False

    def get_tool_port(self, tool_id: str) -> Optional[int]:
        """
        Get the port for a tool process.

        Args:
            tool_id: ID of the tool

        Returns:
            Port number or None if not found
        """
        if self.debug:
            logger.debug(f"Getting port for tool {tool_id}")

        # First check if the tool is running
        is_running = self.is_tool_running(tool_id)
        if self.debug:
            logger.debug(f"Tool {tool_id} is running: {is_running}")

        if not is_running:
            if self.debug:
                logger.debug(f"Tool {tool_id} is not running, cannot get port")
            return None

        # Get the port from the PID file
        pid_info = self._load_pid(tool_id)
        if self.debug:
            logger.debug(f"PID info for {tool_id}: {pid_info}")

        if pid_info and pid_info.get("port"):
            port = pid_info.get("port")
            if self.debug:
                logger.debug(f"Found port {port} in PID file for {tool_id}")
            return port

        # Try to extract port from command line
        pid = pid_info.get("pid") if pid_info else None
        if self.debug:
            logger.debug(f"Trying to extract port from command line for PID {pid}")

        if pid:
            try:
                # Get the command line for this PID
                if platform.system() != "Windows":
                    # Unix approach - use ps to get the command line
                    ps_cmd = f"ps -p {pid} -o command= || ps -p {pid} -o args="
                    ps_result = subprocess.run(ps_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                    if self.debug:
                        logger.debug(f"Command line for PID {pid}: {ps_result.stdout}")

                    if ps_result.stdout.strip():
                        cmd_line = ps_result.stdout.strip()
                        # Look for --port or -p argument
                        if "--port" in cmd_line:
                            parts = cmd_line.split("--port")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    port = int(port_part)
                                    if self.debug:
                                        logger.debug(f"Found port {port} in command line for {tool_id}")
                                    return port
                                except ValueError:
                                    if self.debug:
                                        logger.debug(f"Could not parse port from {port_part}")
                        elif " -p " in cmd_line:
                            parts = cmd_line.split(" -p ")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    port = int(port_part)
                                    if self.debug:
                                        logger.debug(f"Found port {port} in command line for {tool_id}")
                                    return port
                                except ValueError:
                                    if self.debug:
                                        logger.debug(f"Could not parse port from {port_part}")
            except Exception as e:
                logger.debug(f"Error extracting port from command line for PID {pid}: {e}")

        # Try to find the port from any process with the tool ID in the command line
        if self.debug:
            logger.debug(f"Trying to find port from any process with {tool_id} in the command line")

        try:
            if platform.system() != "Windows":
                # Look for processes with the tool ID in the command line
                find_cmd = f"ps -ef | grep {tool_id} | grep -v grep"
                find_result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                if self.debug:
                    logger.debug(f"Processes matching {tool_id}: {find_result.stdout}")

                if find_result.stdout.strip():
                    # Look for --port or -p argument in any of the matching processes
                    for line in find_result.stdout.splitlines():
                        if "--port" in line:
                            parts = line.split("--port")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    port = int(port_part)
                                    if self.debug:
                                        logger.debug(f"Found port {port} in process matching {tool_id}")
                                    return port
                                except ValueError:
                                    if self.debug:
                                        logger.debug(f"Could not parse port from {port_part}")
                        elif " -p " in line:
                            parts = line.split(" -p ")
                            if len(parts) > 1:
                                port_part = parts[1].strip().split()[0]
                                try:
                                    port = int(port_part)
                                    if self.debug:
                                        logger.debug(f"Found port {port} in process matching {tool_id}")
                                    return port
                                except ValueError:
                                    if self.debug:
                                        logger.debug(f"Could not parse port from {port_part}")
        except Exception as e:
            logger.debug(f"Error extracting port from ps output for {tool_id}: {e}")

        if self.debug:
            logger.debug(f"Could not find port for {tool_id}")
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
