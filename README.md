# Parts MCP

A Model Context Protocol (MCP) server for sourcing electronic parts with KiCad integration.

## Overview

Parts MCP enables AI assistants to search for electronic components across multiple suppliers, compare prices, check availability, and integrate seamlessly with KiCad projects. It provides a unified interface for component sourcing workflows.

## Features

- **Universal Parts Search**: Search parts using the Source Parts API
- **Price Comparison**: Compare prices and availability across suppliers
- **KiCad Integration**: Extract BOMs from KiCad projects and match components to real parts
- **Parametric Search**: Find components by electrical and physical parameters
- **Alternative Parts**: Get suggestions for alternative components
- **Caching**: Local caching for improved performance

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/parts-mcp.git
cd parts-mcp
```

2. Install dependencies (requires Python 3.10+):
```bash
pip install -e .
```

3. Configure your environment:
```bash
cp .env.example .env
# Edit .env with your API keys
```

4. Run the server:
```bash
python main.py
```

## Configuration

Configure the server by setting environment variables in `.env`:

- `SOURCE_PARTS_API_KEY`: Your Source Parts API key
- `SOURCE_PARTS_API_URL`: Source Parts API endpoint (optional)
- `KICAD_SEARCH_PATHS`: Directories to search for KiCad projects
- `PARTS_CACHE_DIR`: Cache directory location

## MCP Client Configuration

Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
    "mcpServers": {
        "parts": {
            "command": "/path/to/python",
            "args": ["/path/to/parts-mcp/main.py"]
        }
    }
}
```

## Usage Examples

### Search for Parts
"Find me a 10kΩ resistor in 0805 package with 1% tolerance"

### Extract KiCad BOM
"Extract the BOM from my amplifier project and find suppliers for all components"

### Compare Prices
"Compare prices for STM32F103C8T6 across all suppliers for quantity 100"

### Find Alternatives
"Find alternatives for the obsolete LM358 op-amp"

## Development

The project structure:
- `parts_mcp/resources/` - Read-only data sources
- `parts_mcp/tools/` - Action functions for searching and sourcing
- `parts_mcp/prompts/` - Reusable prompt templates
- `parts_mcp/utils/` - Utility functions and API clients

## License

MIT