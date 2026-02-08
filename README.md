# Parts MCP

A Model Context Protocol (MCP) server for sourcing electronic parts with multi-EDA integration.

## Overview

Parts MCP enables AI assistants to search for electronic components, compare prices, check availability, and process BOMs from popular EDA tools. It provides a unified interface for component sourcing workflows powered by the [Source Parts API](https://source.parts).

## Supported EDA Tools

| Tool | BOM Format | Status |
|------|------------|--------|
| KiCad | CSV, XML | Full support + CLI integration |
| Altium Designer | CSV, XLS | Full support |
| Autodesk Fusion 360 | CSV | Full support |
| Eagle | CSV, BRD | Full support |
| PADS | CSV, ASC | Full support |
| Protel 99 | CSV | Full support |

## Features

- **Universal Parts Search**: Search millions of parts via Source Parts API
- **Multi-EDA BOM Processing**: Import BOMs from KiCad, Altium, Fusion360, Eagle, PADS, Protel99
- **Component Matching**: AI-powered matching with confidence scoring
- **Price Comparison**: Compare prices across distributors
- **Availability Check**: Real-time inventory levels
- **Alternative Parts**: Find drop-in replacements and functional equivalents
- **KiCad CLI Integration**: Generate BOMs directly from schematics
- **Local Caching**: Fast responses with intelligent caching

## Installation

### From PyPI (Recommended)

```bash
pip install parts-mcp
```

### From Source

```bash
git clone https://github.com/SourceParts/parts-mcp.git
cd parts-mcp
pip install -e .
```

### Requirements

- Python 3.10+
- Source Parts API key ([get one here](https://source.parts/docs/api))

## Configuration

Create a `.env` file or set environment variables:

```bash
# Required
SOURCE_PARTS_API_KEY=your_api_key_here

# Optional
SOURCE_PARTS_API_URL=https://api.source.parts/v1
KICAD_SEARCH_PATHS=/path/to/kicad/projects
PARTS_CACHE_DIR=~/.cache/parts-mcp
CACHE_EXPIRY_HOURS=24
```

## Claude Desktop Integration

Add to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "parts": {
      "command": "python",
      "args": ["-m", "parts_mcp"],
      "env": {
        "SOURCE_PARTS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

If installed from source:

```json
{
  "mcpServers": {
    "parts": {
      "command": "/path/to/python",
      "args": ["/path/to/parts-mcp/main.py"],
      "env": {
        "SOURCE_PARTS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

After adding the configuration, restart Claude Desktop.

## Claude Code Integration

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "parts": {
      "command": "python",
      "args": ["-m", "parts_mcp"],
      "env": {
        "SOURCE_PARTS_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Or run directly:

```bash
claude --mcp-server "python -m parts_mcp"
```

## Usage Examples

### Search for Parts
> "Find a 10k resistor in 0603 package"

### Process a BOM
> "Upload my Altium BOM and find the best prices for 100 units"

### KiCad Integration
> "Extract the BOM from my amplifier.kicad_sch and source all components"

### Find Alternatives
> "Find alternatives for the obsolete LM358"

### Check Availability
> "Check stock levels for STM32F103C8T6"

## Available Tools

| Tool | Description |
|------|-------------|
| `search_parts` | Search for components by query |
| `get_part_details` | Get detailed part information |
| `get_part_pricing` | Get pricing across distributors |
| `check_availability` | Check real-time inventory |
| `find_alternatives` | Find replacement parts |
| `process_bom` | Process BOM file from any supported EDA |
| `match_components` | Match BOM components to parts |
| `find_kicad_projects` | Discover local KiCad projects |
| `generate_kicad_bom` | Generate BOM from KiCad schematic |

## Architecture

Parts MCP follows a thin client architecture:

**Local (MCP)**:
- KiCad CLI operations
- Project discovery
- Response caching
- BOM file parsing

**Server (Source Parts API)**:
- Component matching
- Price aggregation
- Inventory checking
- Alternative search

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with debug logging
DEBUG=1 python main.py
```

## Project Structure

```
parts_mcp/
├── server.py          # MCP server entry
├── config.py          # Configuration
├── tools/             # MCP tools
├── resources/         # MCP resources
├── prompts/           # Prompt templates
└── utils/
    ├── api_client.py        # Source Parts API client
    ├── bom_parser.py        # Multi-EDA BOM parsing
    ├── component_matcher.py # Component matching
    ├── cache.py             # Response caching
    └── kicad_utils.py       # KiCad CLI integration
```

## Links

- [Source Parts](https://source.parts) - Component search platform
- [Source Parts API Docs](https://source.parts/docs/api) - API documentation
- [MCP Specification](https://modelcontextprotocol.io) - Model Context Protocol

## License

MIT License with Trademark Protection - see [LICENSE.md](LICENSE.md)

"Source Parts" is a trademark. See license for usage restrictions.
