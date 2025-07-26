#!/usr/bin/env python3
"""
Parts MCP Server - A Model Context Protocol server for electronic parts sourcing.
"""
import os
import sys
import logging
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from parts_mcp.server import main as server_main


def load_dotenv():
    """Load environment variables from .env file if it exists."""
    env_file = project_dir / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv as _load_dotenv
            _load_dotenv(env_file)
            return True
        except ImportError:
            logging.warning("python-dotenv not installed, skipping .env file")
            return False
    return False


if __name__ == "__main__":
    # Load environment variables
    if load_dotenv():
        logging.info("Loaded environment variables from .env file")
    
    # Run the server
    server_main()