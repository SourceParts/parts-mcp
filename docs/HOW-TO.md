# Parts MCP How-To Guide

This guide provides practical examples of using Parts MCP for common electronic component sourcing and KiCad integration tasks.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Finding KiCad Projects](#finding-kicad-projects)
3. [Extracting BOMs from KiCad](#extracting-boms-from-kicad)
4. [Searching for Parts](#searching-for-parts)
5. [Analyzing Projects](#analyzing-projects)
6. [Exporting Data](#exporting-data)
7. [Common Workflows](#common-workflows)

## Getting Started

### Setting Up Environment Variables

Create a `.env` file in the project root:

```bash
# Source Parts API Configuration
SOURCE_PARTS_API_KEY=your_api_key_here
SOURCE_PARTS_API_URL=https://api.sourceparts.com/v1

# KiCad Project Paths
KICAD_SEARCH_PATHS=~/Documents/KiCad,~/Projects/Electronics

# Cache Settings
PARTS_CACHE_DIR=~/.cache/parts-mcp
```

### Running the Server

```bash
# Install dependencies
pip install -e .

# Run the server
python main.py
```

## Finding KiCad Projects

### List All Projects

To discover all KiCad projects in your configured search paths:

```
"Can you find all my KiCad projects?"
```

The server will search through:
- Default KiCad directories
- Paths specified in `KICAD_SEARCH_PATHS`
- Common project locations

### Filter by Recent Projects

```
"Show me KiCad projects I've worked on recently"
```

Projects are automatically sorted by modification date.

## Extracting BOMs from KiCad

### Extract from Existing BOM Files

```
"Extract the BOM from my amplifier project at ~/Projects/audio-amp/audio-amp.kicad_pro"
```

The tool will:
1. Look for existing BOM files (CSV, JSON, XML)
2. Parse and analyze component data
3. Provide component counts and categories

### Generate BOM Using KiCad CLI

If no BOM file exists:

```
"Generate a BOM for the project ~/Projects/led-driver/led-driver.kicad_pro"
```

This will use KiCad CLI to generate a fresh BOM from the schematic.

### Analyze BOM Data

```
"What components are in my power supply project's BOM?"
```

Returns:
- Total component count
- Component categories (Resistors, Capacitors, ICs, etc.)
- Most common values
- Missing data analysis

## Searching for Parts

### Basic Part Search

```
"Find a 10kΩ resistor in 0805 package"
```

### Parametric Search

```
"Search for voltage regulators with:
- Output voltage: 3.3V
- Current rating: >500mA
- Package: SOT-23"
```

### Find Alternatives

```
"Find alternatives for LM7805 voltage regulator"
```

## Analyzing Projects

### Project Overview

```
"Analyze the KiCad project at ~/Projects/sensor-board/sensor-board.kicad_pro"
```

Returns:
- Project metadata
- File counts (schematics, PCBs, data files)
- Board settings
- Text variables

### Extract Netlist

```
"Extract the netlist from my motor controller project"
```

Provides:
- Component list with connections
- Net count and names
- Power and ground net identification
- Connectivity analysis

### Connectivity Analysis

```
"Show me the most connected components in my project"
```

Returns:
- Components with most connections
- Isolated components
- Net fanout analysis

## Exporting Data

### Export BOM to CSV

```
"Export the matched parts to ~/Documents/bom_with_parts.csv"
```

Creates a KiCad-compatible CSV with:
- Reference designators
- Values and footprints
- Manufacturer part numbers
- Supplier information
- Pricing data

### Export to JSON

```
"Export the BOM analysis to JSON format"
```

## Common Workflows

### 1. Complete BOM Sourcing Workflow

```
1. "Find my LED matrix project"
2. "Extract the BOM from /path/to/project.kicad_pro"
3. "Search for parts matching each component in the BOM"
4. "Compare prices for all components"
5. "Export the complete BOM with supplier info to CSV"
```

### 2. New Project Component Selection

```
1. "I need to design a 5V to 3.3V power supply"
2. "Search for suitable voltage regulators"
3. "Find the recommended capacitors for the selected regulator"
4. "Export the parts list for KiCad"
```

### 3. Design Review and Cost Analysis

```
1. "Analyze my latest PCB project"
2. "Extract the BOM and check component availability"
3. "Calculate total cost for 100 units"
4. "Find cheaper alternatives for expensive components"
```

### 4. Netlist Verification

```
1. "Extract netlist from my schematic"
2. "Show me all power connections"
3. "Find components that aren't connected to anything"
4. "Verify critical signal paths"
```

## Tips and Best Practices

### Project Organization

1. Keep KiCad projects in directories listed in `KICAD_SEARCH_PATHS`
2. Use consistent naming for BOM files (e.g., `project_name_bom.csv`)
3. Generate netlists after major schematic changes

### BOM Management

1. Export BOMs from KiCad with complete component information
2. Include manufacturer part numbers in component properties
3. Use consistent reference designator prefixes

### Part Selection

1. Search for parts with specific parameters first
2. Check availability before finalizing component selection
3. Consider alternatives for critical components
4. Verify footprints match your PCB design

### Integration Tips

1. Open projects directly in KiCad: `"Open the sensor project in KiCad"`
2. Use the analysis tools before ordering parts
3. Keep BOM exports for version tracking
4. Cache frequently used parts for faster searches

## Troubleshooting

### KiCad CLI Not Found

If BOM generation fails:
1. Ensure KiCad is installed
2. Set `KICAD_CLI_PATH` environment variable
3. Check PATH includes KiCad binary directory

### Empty Search Results

1. Verify `SOURCE_PARTS_API_KEY` is set
2. Check network connectivity
3. Try broader search terms

### BOM Parsing Issues

1. Ensure BOM files use standard formats
2. Check for UTF-8 encoding
3. Verify CSV delimiter (comma, semicolon, or tab)

### Project Not Found

1. Add project directory to `KICAD_SEARCH_PATHS`
2. Use absolute paths for direct access
3. Check file permissions