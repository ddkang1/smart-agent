#!/bin/bash
# This script sets up the development environment for Smart Agent

# Exit on error
set -e

# Install the package in development mode
echo "Installing Smart Agent in development mode..."
pip install -e .

# Install development dependencies
echo "Installing development dependencies..."
pip install pytest pytest-cov pytest-asyncio black flake8 mypy

# Display success message
echo "Development environment setup complete!"
echo "You can now run tests with: pytest tests/unit -v"
echo "You can run linting with: flake8 smart_agent tests"
echo "You can check formatting with: black --check smart_agent tests"
echo "You can run type checking with: bash run_mypy.sh"
