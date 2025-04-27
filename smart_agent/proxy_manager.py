"""
Proxy Manager for Smart Agent.

This module handles the management of proxy services like LiteLLM.
"""

import os
import logging
import subprocess
from typing import Dict, Optional, Any
from urllib.parse import urlparse

# Set up logging
logger = logging.getLogger(__name__)


class ProxyManager:
    """
    Manager for proxy services like LiteLLM.
    """

    def __init__(self, config_dir: Optional[str] = None, debug: bool = False):
        """
        Initialize the proxy manager.

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

    def launch_litellm_proxy(self, config_manager, background: bool = True) -> Optional[int]:
        """
        Launch LiteLLM proxy using Docker.

        Args:
            config_manager: Configuration manager instance
            background: Whether to run in background

        Returns:
            Process ID if successful, None otherwise
        """
        if self.debug:
            logger.debug("Launching LiteLLM proxy using Docker...")
        else:
            logger.info("Launching LiteLLM proxy using Docker...")

        # Check if container already exists and is running
        container_name = "smart-agent-litellm-proxy"
        try:
            result = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={container_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if result.stdout.strip():
                if self.debug:
                    logger.debug(f"LiteLLM proxy container '{container_name}' is already running.")
                else:
                    logger.info(f"LiteLLM proxy container '{container_name}' is already running.")
                # Return a dummy PID to indicate success
                return 999999  # Using a large number that's unlikely to be a real PID
        except Exception as e:
            logger.warning(f"Error checking for existing LiteLLM proxy container: {str(e)}")

        # Get LiteLLM config path
        try:
            litellm_config_path = config_manager.get_litellm_config_path()
            if self.debug:
                logger.debug(f"LiteLLM config path: {litellm_config_path}")
        except Exception as e:
            litellm_config_path = None
            logger.warning(f"Could not get LiteLLM config path: {str(e)}")

        # Get API settings
        api_base_url = config_manager.get_api_base_url()

        try:
            parsed_url = urlparse(api_base_url)
            if parsed_url.port:
                api_port = parsed_url.port
                if self.debug:
                    logger.debug(f"Extracted port {api_port} from API base URL {api_base_url}")
        except Exception as e:
            if self.debug:
                logger.debug(f"Error parsing API base URL: {str(e)}")
            # Use default port

        # Create command
        cmd = [
            "docker",
            "run",
            "-d",  # Run as daemon
            "-p",
            f"{api_port}:{api_port}",
            "--name",
            container_name,
        ]

        # Add volume if we have a config file
        if litellm_config_path and os.path.exists(litellm_config_path):
            # Mount the config file directly to /app/config.yaml as in docker-compose
            cmd.extend([
                "-v",
                f"{litellm_config_path}:/app/config.yaml",
            ])

            # Add image
            cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")

            # Add command line arguments as in docker-compose
            cmd.extend([
                "--config", "/app/config.yaml",
                "--port", str(api_port),
                "--host", "0.0.0.0",  # Bind to all interfaces
                "--num_workers", "8"
            ])
        else:
            # Add image only if no config file
            cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")
            # Add port and host arguments
            cmd.extend([
                "--port", str(api_port),
                "--host", "0.0.0.0"  # Bind to all interfaces
            ])

        # Print the command for debugging
        if self.debug:
            logger.debug(f"Launching LiteLLM proxy with command: {' '.join(cmd)}")

        # Run command
        try:
            if background:
                # Start the process in the background
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
            else:
                # Start in foreground for debugging
                process = subprocess.Popen(cmd)

            # Get the PID
            pid = process.pid

            # Save the PID
            if pid:
                pid_file = os.path.join(self.pid_dir, "litellm_proxy.pid")
                with open(pid_file, "w") as f:
                    f.write(str(pid))

            if self.debug:
                logger.debug(f"Started LiteLLM proxy with PID {pid} on port {api_port}")
            else:
                logger.info(f"Started LiteLLM proxy with PID {pid} on port {api_port}")
            return pid
        except Exception as e:
            logger.error(f"Error launching LiteLLM proxy: {str(e)}")
            return None

    def restart_litellm_proxy(self, config_manager, background: bool = True) -> Optional[int]:
        """
        Restart the LiteLLM proxy if it's not running.

        Args:
            config_manager: Configuration manager instance
            background: Whether to run in background

        Returns:
            Process ID if successful, None otherwise
        """
        if self.debug:
            logger.debug("Restarting LiteLLM proxy...")
        else:
            logger.info("Restarting LiteLLM proxy...")

        # First stop the proxy if it's running
        self.stop_litellm_proxy()

        # Then start it again
        return self.launch_litellm_proxy(config_manager, background)

    def stop_litellm_proxy(self) -> bool:
        """
        Stop the LiteLLM proxy.

        Returns:
            True if successful, False otherwise
        """
        if self.debug:
            logger.debug("Stopping LiteLLM proxy...")
        else:
            logger.info("Stopping LiteLLM proxy...")

        container_name = "smart-agent-litellm-proxy"
        success = False

        try:
            # Check if container exists
            result = subprocess.run(
                ["docker", "ps", "-a", "-q", "-f", f"name={container_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if result.stdout.strip():
                # Container exists, try to stop it
                stop_result = subprocess.run(
                    ["docker", "stop", container_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )

                if stop_result.returncode == 0:
                    if self.debug:
                        logger.debug(f"Successfully stopped LiteLLM proxy container '{container_name}'")
                    else:
                        logger.info(f"Successfully stopped LiteLLM proxy container '{container_name}'")

                    # Also remove the container to ensure a clean restart
                    rm_result = subprocess.run(
                        ["docker", "rm", container_name],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )

                    if rm_result.returncode == 0:
                        if self.debug:
                            logger.debug(f"Successfully removed LiteLLM proxy container '{container_name}'")
                    else:
                        logger.warning(f"Failed to remove LiteLLM proxy container: {rm_result.stderr}")

                    success = True
                else:
                    logger.warning(f"Failed to stop LiteLLM proxy container: {stop_result.stderr}")
            else:
                logger.warning(f"LiteLLM proxy container '{container_name}' not found")
        except Exception as e:
            logger.error(f"Error stopping LiteLLM proxy: {str(e)}")

        # Remove the PID file if it exists
        pid_file = os.path.join(self.pid_dir, "litellm_proxy.pid")
        if os.path.exists(pid_file):
            os.remove(pid_file)

        return success

    def is_litellm_proxy_running(self) -> bool:
        """
        Check if the LiteLLM proxy is running.

        Returns:
            True if running, False otherwise
        """
        if self.debug:
            logger.debug("Checking if LiteLLM proxy is running...")

        container_name = "smart-agent-litellm-proxy"

        try:
            # Check if container exists and is running
            result = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={container_name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            is_running = bool(result.stdout.strip())

            if self.debug:
                if is_running:
                    logger.debug(f"LiteLLM proxy container '{container_name}' is running")
                else:
                    logger.debug(f"LiteLLM proxy container '{container_name}' is not running")

            return is_running
        except Exception as e:
            logger.error(f"Error checking if LiteLLM proxy is running: {str(e)}")
            return False

    def get_litellm_proxy_status(self) -> Dict[str, Any]:
        """
        Get the status of the LiteLLM proxy.

        Returns:
            Dictionary with status information
        """
        if self.debug:
            logger.debug("Getting LiteLLM proxy status...")

        container_name = "smart-agent-litellm-proxy"
        status = {
            "running": False,
            "container_id": None,
            "port": None,
            "image": None,
        }

        try:
            # First check if container is running (only running containers)
            running_result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.ID}}|{{.Ports}}|{{.Image}}|{{.Status}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            # Check if container exists (including stopped containers)
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.ID}}|{{.Ports}}|{{.Image}}|{{.Status}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            # If the container is running, use that result
            if running_result.stdout.strip():
                result = running_result
                status["running"] = True
                if self.debug:
                    logger.debug(f"LiteLLM proxy container is running")

            if result.stdout.strip():
                # Parse the output
                parts = result.stdout.strip().split("|")
                if len(parts) >= 4:
                    container_id = parts[0]
                    ports = parts[1]
                    image = parts[2]
                    container_status = parts[3]

                    status["container_id"] = container_id
                    status["image"] = image
                    status["running"] = container_status.startswith("Up")

                    # Extract port from ports string (e.g., "0.0.0.0:4000->4000/tcp")
                    if ":" in ports:
                        try:
                            port = ports.split(":")[1].split("->")[0]
                            status["port"] = int(port)
                        except (IndexError, ValueError):
                            pass

                    if self.debug:
                        logger.debug(f"LiteLLM proxy status: {status}")
            else:
                if self.debug:
                    logger.debug("LiteLLM proxy container not found")
        except Exception as e:
            logger.error(f"Error getting LiteLLM proxy status: {str(e)}")

        return status
