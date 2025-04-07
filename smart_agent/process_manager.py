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

        # Check if this is a Docker-based tool
        is_docker_tool = False
        docker_cmd_line = None

        if pid:
            try:
                # Get the command line for this PID
                if platform.system() != "Windows":
                    # Unix approach - use ps to get the command line
                    ps_cmd = f"ps -p {pid} -o command= || ps -p {pid} -o args="
                    ps_result = subprocess.run(ps_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                    if ps_result.stdout.strip():
                        cmd_line = ps_result.stdout.strip()
                        if "docker run" in cmd_line:
                            is_docker_tool = True
                            docker_cmd_line = cmd_line
                            if self.debug:
                                logger.debug(f"Tool {tool_id} is a Docker-based tool")
            except Exception as e:
                logger.debug(f"Error checking if {tool_id} is a Docker tool: {e}")

        # If this is a Docker-based tool, we need to find and stop the Docker container
        if is_docker_tool:
            try:
                # First, try to find the Docker container ID
                if self.debug:
                    logger.debug(f"Stopping Docker container for {tool_id}")

                # Try different approaches to find the Docker container
                container_found = False
                docker_container_id = None

                # We won't rely on container names as they can be randomly generated
                # Instead, focus on extracting the image name from the command line
                # and using that to find containers

                # 2. Try to extract the Docker image name from the command line
                if not container_found and docker_cmd_line:
                    # Parse the command line to find the image name
                    parts = docker_cmd_line.split()
                    docker_image = None

                    # Find the position of 'docker run' in the command
                    docker_run_pos = -1
                    for i, part in enumerate(parts):
                        if part == "docker" and i+1 < len(parts) and parts[i+1] == "run":
                            docker_run_pos = i
                            break

                    # Look for the image name after 'docker run' and its options
                    if docker_run_pos >= 0:
                        for i in range(docker_run_pos + 2, len(parts)):
                            # Skip options that start with - or have volume mappings
                            if parts[i].startswith("-") or ":" in parts[i] and "/" in parts[i] and not parts[i].startswith("ghcr.io/"):
                                continue
                            # This is likely the image name
                            docker_image = parts[i]
                            if self.debug:
                                logger.debug(f"Found Docker image {docker_image} in command line")
                            break

                    if docker_image:
                        # Try to find containers using that image
                        find_cmd = f"docker ps -q --filter ancestor={docker_image}"
                        result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                        if result.stdout.strip():
                            docker_container_id = result.stdout.strip()
                            container_found = True
                            if self.debug:
                                logger.debug(f"Found Docker container {docker_container_id} using image {docker_image}")

                # 3. Try to find containers by looking at the command line in 'docker ps'
                if not container_found:
                    # Get all running containers with their command lines
                    find_cmd = "docker ps --format \"{{.ID}}|{{.Command}}|{{.Image}}\""
                    result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                    if result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            parts = line.split('|')
                            if len(parts) >= 3:
                                container_id = parts[0]
                                command = parts[1]
                                image = parts[2]

                                # Check if the tool ID or name appears in the command or image
                                if tool_id in command or tool_id in image or tool_name in command or tool_name in image:
                                    docker_container_id = container_id
                                    container_found = True
                                    if self.debug:
                                        logger.debug(f"Found Docker container {docker_container_id} with matching command/image for {tool_id}")
                                    break

                # If we found a container ID, stop it
                if container_found and docker_container_id:
                    if self.debug:
                        logger.debug(f"Stopping Docker container {docker_container_id} for {tool_id}")
                    stop_cmd = f"docker stop {docker_container_id}"
                    stop_result = subprocess.run(stop_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                    if stop_result.returncode == 0:
                        success = True
                        logger.info(f"Stopped Docker container {docker_container_id} for {tool_id}")
                    else:
                        logger.warning(f"Failed to stop Docker container {docker_container_id} for {tool_id}: {stop_result.stderr}")
                else:
                    # If we couldn't find a specific container, try a more general approach
                    # Look for any container that might be related to this tool

                    # 1. Try by tool name
                    tool_name = tool_id.replace("_", "-")
                    if self.debug:
                        logger.debug(f"Trying to find Docker containers by name pattern: {tool_name}")
                    # This will find and stop any container with the tool name in its name
                    find_cmd = f"docker ps -q --filter name={tool_name} | xargs -r docker stop"
                    stop_result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                    if stop_result.returncode == 0 and stop_result.stdout.strip():
                        success = True
                        logger.info(f"Stopped Docker containers for {tool_id} by name")

                    # 2. Try a more direct approach - find all containers with the image name in their image
                    if not success:
                        if self.debug:
                            logger.debug(f"Trying to find Docker containers by image pattern")
                        # Get all running containers
                        find_cmd = "docker ps --format \"{{.ID}}|{{.Image}}\""
                        result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                        if result.stdout.strip():
                            for line in result.stdout.strip().split('\n'):
                                parts = line.split('|')
                                if len(parts) >= 2:
                                    container_id = parts[0]
                                    image = parts[1]

                                    # Check if this is a relevant container by comparing with the extracted image
                                    # or by looking for any similarity with the tool ID
                                    if (docker_image and docker_image in image) or \
                                       (tool_id.lower() in image.lower()) or \
                                       (tool_id.replace("_", "-").lower() in image.lower()):
                                        if self.debug:
                                            logger.debug(f"Found container {container_id} with image {image}")
                                        # Stop this container
                                        stop_cmd = f"docker stop {container_id}"
                                        stop_result = subprocess.run(stop_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                                        if stop_result.returncode == 0:
                                            success = True
                                            logger.info(f"Stopped Docker container {container_id} with image {image}")

                    # 3. Try a more generic approach - find all containers and check their command lines
                    if not success:
                        if self.debug:
                            logger.debug(f"Trying to find Docker containers by inspecting all running containers")
                        # Get all running containers
                        find_cmd = "docker ps -a --format \"{{.ID}}|{{.Image}}|{{.Command}}\""
                        result = subprocess.run(find_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                        if result.stdout.strip():
                            for line in result.stdout.strip().split('\n'):
                                parts = line.split('|')
                                if len(parts) >= 3:
                                    container_id = parts[0]
                                    image = parts[1]
                                    command = parts[2]

                                    # Check for any pattern that might match our tool
                                    # Compare with extracted image or look for tool ID in image name
                                    if (docker_image and docker_image in image) or \
                                       (tool_id.lower() in image.lower()) or \
                                       (tool_id.replace("_", "-").lower() in image.lower()):
                                        if self.debug:
                                            logger.debug(f"Found matching container {container_id} with image {image}")
                                        # Stop this container
                                        stop_cmd = f"docker stop {container_id}"
                                        stop_result = subprocess.run(stop_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                                        if stop_result.returncode == 0:
                                            success = True
                                            logger.info(f"Stopped Docker container {container_id} for {tool_id}")

                    # 4. Last resort - kill the docker run process itself
                    if not success and pid:
                        if self.debug:
                            logger.debug(f"Trying to kill the docker run process with PID {pid}")
                        try:
                            # Kill the docker run process
                            if platform.system() == "Windows":
                                subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
                            else:
                                # Unix approach - send SIGTERM to process group
                                try:
                                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                                except ProcessLookupError:
                                    # If process group not found, try killing just the process
                                    os.kill(pid, signal.SIGTERM)

                            # Wait a moment for the process to terminate
                            time.sleep(0.5)

                            # Check if the process is still running
                            try:
                                os.kill(pid, 0)  # Signal 0 doesn't kill the process, just checks if it exists
                                # Process still exists, use SIGKILL
                                if platform.system() != "Windows":
                                    os.kill(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                # Process already gone, good
                                pass

                            success = True
                            logger.info(f"Killed docker run process with PID {pid} for {tool_id}")
                        except Exception as e:
                            logger.warning(f"Error killing docker run process with PID {pid}: {e}")
            except Exception as e:
                logger.warning(f"Error stopping Docker container for {tool_id}: {e}")

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
