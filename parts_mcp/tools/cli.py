"""
Parts CLI bridge — runs the `parts` CLI for local project operations.

This tool enables MCP clients to invoke the `parts` CLI with full knowledge
of available commands, flags, and usage patterns. The `parts` CLI must be
installed and available on PATH (or configured via PARTS_CLI_PATH).
"""
import logging
import os
import shutil
import subprocess
from typing import Any

from fastmcp import FastMCP

from parts_mcp.utils.api_client import with_user_context
from parts_mcp.utils.roles import require_role


def setdoc(doc: str):
    """Decorator that sets __doc__ on the wrapped function before outer decorators read it."""
    def decorator(fn):
        fn.__doc__ = doc
        return fn
    return decorator

logger = logging.getLogger(__name__)

_PARTS_CLI = os.environ.get("PARTS_CLI_PATH") or shutil.which("parts")

# Complete command reference — this docstring is what teaches the model
# how to construct correct `parts` CLI invocations.
_CLI_REFERENCE = """
# Parts CLI Command Reference

## ECN Management (project ecn)

### List all ECNs
  parts project ecn list [--dir ECO]
  Alias: parts project ecn ls

### Get ECN details
  Read the file directly: ECO/ECN-006.md

### Create a new ECN
  parts project ecn create \\
    --id ECN-021 \\
    --title "Issue title" \\
    --type "Schematic Change" \\
    --severity HIGH \\
    --disposition REQUIRED \\
    [--category Electrical] \\
    [--author "Name"] \\
    [--source "reference"] \\
    [--affected "U5, R23"] \\
    [--output-dir ECO]

  Types: Design Constraint | Assembly Note | BOM Change | Schematic Change | Process Change
  Severity: CRITICAL | HIGH | MEDIUM | LOW
  Disposition: REQUIRED | RECOMMENDED | OPTIONAL

### Validate ECN files
  parts project ecn validate [--dir ECO]

### Migrate monolithic log to individual files
  parts project ecn migrate --source Reports/ECN_Log_V1.0.md [--output-dir ECO]

## Fabrication (fab)

### Stackup PDF from gerbers
  parts fab stackup <gerbers.zip> [-b "Board Name"] [--scale 3] [-o output.pdf] [--prefix "Board_V1.03"]

### Placement / pick-and-place
  parts fab placement [positions.csv] \\
    [--rows 3] [--cols 3] \\
    [--assemble 1,2,3,7,8] \\
    [--side top|bottom|both] \\
    [--outline board.gko] \\
    [--bom bom.csv] \\
    [--manual-place U,J,SW,MIC] \\
    [--split-csv] \\
    [--rotate-top] \\
    [--machine yy1] \\
    [-b "Board Name"] [-o ./output] [--prefix "Board_V1.03"]

### Net trace highlight
  parts fab highlight <board.kicad_pcb> \\
    --nets "VCC,GND,SDA" \\
    [--colors "VCC=#ff0000,GND=#0000ff"] \\
    [--mode overlay|traces|both] \\
    [--layers "F.Cu"] \\
    [-o ./output]

### Assembly guide PDF
  parts fab assembly

### Test point report
  parts fab testpoints <positions.csv>

### Gerber diff
  parts fab diff <v1.zip> <v2.zip> [--name-a "V1" --name-b "V2"]

### Structural diff report
  parts fab report <v1.zip> <v2.zip>

### X-ray inspection report
  parts fab xray

### Release
  parts fab release <partNumber>

### Machine SD card
  parts fab machine

## BOM

### Upload BOM
  parts bom <filename.xlsx> [-p project_id] [--wait] [--no-lcsc] [--dfm-check]

### Generate BOM PDF
  parts bom pdf [bom.csv] [-b "Board Name"] [-o output.pdf] [--prefix "Board_V1.03"]

### Clean EIA capacitor codes
  parts bom clean <bom.csv>

### Convert CSV to Excel
  parts bom convert <file.csv>

### Fetch datasheets for BOM parts
  parts bom datasheets <bom.csv>

### Enrich BOM with descriptions
  parts bom enrich <bom.csv>

### Check BOM job status
  parts bom status <job_id>

## Project

### Init new project
  parts init [path] [-t dfm|pcb|assembly] [-a "Author"] [-d "Description"] [--skip-git] [-i]

### Project CRUD
  parts project create
  parts project list
  parts project get <id>
  parts project delete <id>

### ECO (Engineering Change Order)
  parts project eco

### Status
  parts status

## Search & Parts

### Search parts
  parts search <query> [--in-stock] [--eu-only|--us-only|--cn-only]

### Smart query (search, URL, SMD codes)
  parts q <query>

### Price estimate
  parts price <partNumber>

### Inventory check
  parts inventory <partNumber>

### Datasheet
  parts datasheet <partNumber>

### Find alternatives
  parts guide <partNumber>

### SMD code decode
  parts smd <code>

### Resistor color bands
  parts resistor <bands>

### Part marking lookup
  parts marking <code>

## IQC / Ingest

### Upload images for identification
  parts ingest <file_or_dir> [-p project_id] [-b box_id] [--wait] [--recursive] [--dry-run]

### Detect from photo
  parts detect <image>

### Scan barcode
  parts scan <image>

### List IQC items
  parts ingest items

### Reprocess item
  parts ingest reprocess <short_code>

## Manufacturing

### DFM analysis
  parts dfm <project_id>

### AOI inspection
  parts aoi

### QC inspection
  parts qc

## EDA (eda)

### DXF board outline info
  parts eda dxf <file.dxf> [--json]
  Parse a DXF file and report board outline dimensions, bounding box,
  entity count, and layer names.
  Example: parts eda dxf board_outline.dxf
  Example: parts eda dxf board_outline.dxf --json

### Electrical Rules Check
  parts eda erc <file.kicad_sch> [--severity all|error|warning] [--rules file] [--json]
  Upload a KiCad schematic and run ERC. Returns violations by severity.

### Design Rules Check
  parts eda drc <file.kicad_pcb> [--severity all|error|warning] [--rules file.kicad_dru] [--json]
  Upload a KiCad PCB and run DRC. Returns violations by severity.

### Import Altium to KiCad
  parts eda import altium <file.SchDoc|.PcbDoc> [-o output] [--name project] [--revision EVT1] [--no-git]
  Convert Altium schematic or PCB to KiCad format.

## Orders & Commerce

### Get quote
  parts fab quote

### RFQ
  parts rfq

### Add to cart
  parts cart

### Buy
  parts buy

### COGS calculation
  parts cogs <bom_id|project_id> [-q quantity]

## Misc

### Auth
  parts auth

### Balance
  parts balance

### History
  parts history

### Labels
  parts label <partNumber>

### Notes
  parts note "text"

### Todos
  parts todo "text"

### Tracker (price/qty watch)
  parts tracker

### Wishlist
  parts wishlist

### Expenses
  parts expense

### Reports
  parts report

### Git operations
  parts push
  parts pull
  parts log
  parts tag

### GitHub Actions
  parts github report --project <id> --repo <owner/repo> [--thread-id <id>]

## Global flags (apply to all commands)
  -q, --quiet     Suppress progress output
  -v, --verbose   Verbose output
  -h, --help      Help for any command
"""

_PARTS_CLI_TOOL_DOC = f"""Run a `parts` CLI command for local project operations.

Executes the `parts` CLI binary with the given command and arguments.
The command string should NOT include the leading `parts` — just the
subcommand and flags.

{_CLI_REFERENCE}

Args:
    command: The parts subcommand and arguments.
             Examples: "project ecn list", "fab stackup gerbers.zip --scale 3",
             "project ecn create --id ECN-021 --title 'New issue' --type 'BOM Change' --severity HIGH --disposition REQUIRED"
    project_path: Working directory for the command (defaults to cwd).
                  Should be the root of the project containing .parts/config.yaml.

Returns:
    Command stdout, stderr, and exit code
"""


def register_cli_tools(mcp: FastMCP) -> None:
    """Register the parts CLI bridge tool with the MCP server."""

    @mcp.tool()
    @with_user_context
    @require_role("admin")
    @setdoc(_PARTS_CLI_TOOL_DOC)
    async def parts_cli(
        command: str,
        project_path: str | None = None,
    ) -> dict[str, Any]:
        if not _PARTS_CLI:
            return {
                "error": "parts CLI not found on PATH",
                "hint": "Install: https://source.parts/docs/cli — or set PARTS_CLI_PATH env var",
            }

        # Defence in depth: reject shell metacharacters (we use list args, not shell=True)
        dangerous = set(";|&$`\\\"\n\r")
        if any(c in command for c in dangerous):
            return {"error": "Command contains disallowed shell characters. Pass arguments without shell operators."}

        args = [_PARTS_CLI] + command.split()
        cwd = project_path or os.getcwd()

        logger.info("Running: %s (cwd=%s)", " ".join(args), cwd)

        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            response: dict[str, Any] = {
                "command": f"parts {command}",
                "exit_code": result.returncode,
                "success": result.returncode == 0,
                "stdout": result.stdout,
            }
            if result.stderr:
                response["stderr"] = result.stderr

            return response

        except FileNotFoundError:
            return {
                "error": f"parts CLI binary not found at {_PARTS_CLI}",
                "hint": "Install: https://source.parts/docs/cli — or set PARTS_CLI_PATH env var",
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after 120 seconds: parts {command}"}
        except Exception as e:
            logger.error("parts CLI execution failed: %s", e)
            return {"error": str(e)}
