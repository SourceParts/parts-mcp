"""
Unit tests for KiCad utilities.
"""
import os
from unittest.mock import MagicMock, patch

from parts_mcp.utils.kicad_utils import (
    extract_project_info,
    find_kicad_cli,
    find_kicad_projects,
    generate_bom_from_schematic,
    generate_netlist,
    get_kicad_version,
    get_project_files,
    load_project_json,
    run_kicad_cli,
    validate_kicad_installation,
)


class TestFindKicadProjects:
    """Tests for find_kicad_projects function."""

    def test_find_projects_in_directory(self, sample_kicad_project):
        """Find projects in a directory."""
        with patch('parts_mcp.utils.kicad_utils.KICAD_SEARCH_PATHS', [str(sample_kicad_project.parent)]):
            projects = find_kicad_projects()

        assert len(projects) == 1
        assert projects[0]["name"] == "test_project"

    def test_find_projects_empty_directory(self, tmp_path):
        """Find no projects in empty directory."""
        with patch('parts_mcp.utils.kicad_utils.KICAD_SEARCH_PATHS', [str(tmp_path)]):
            projects = find_kicad_projects()

        assert len(projects) == 0


class TestGetProjectFiles:
    """Tests for get_project_files function."""

    def test_get_files_basic_project(self, sample_kicad_project):
        """Get files from basic project."""
        pro_file = sample_kicad_project / "test_project.kicad_pro"
        files = get_project_files(str(pro_file))

        assert "project" in files
        assert "schematic" in files

    def test_get_files_with_bom(self, sample_kicad_project):
        """Detect BOM file in project."""
        # Create a BOM file
        bom_file = sample_kicad_project / "test_project_bom.csv"
        bom_file.write_text("Reference,Value\nR1,10k")

        pro_file = sample_kicad_project / "test_project.kicad_pro"
        files = get_project_files(str(pro_file))

        assert "bom" in files


class TestLoadProjectJson:
    """Tests for load_project_json function."""

    def test_load_valid_project(self, sample_kicad_project):
        """Load a valid project file."""
        pro_file = sample_kicad_project / "test_project.kicad_pro"
        data = load_project_json(str(pro_file))

        assert data is not None
        assert "meta" in data

    def test_load_invalid_path(self):
        """Load from invalid path returns None."""
        data = load_project_json("/nonexistent/path/project.kicad_pro")
        assert data is None


class TestExtractProjectInfo:
    """Tests for extract_project_info function."""

    def test_extract_basic_info(self, sample_kicad_project):
        """Extract basic project information."""
        pro_file = sample_kicad_project / "test_project.kicad_pro"
        info = extract_project_info(str(pro_file))

        assert info["name"] == "test_project"
        assert "files" in info
        assert "metadata" in info


class TestFindKicadCli:
    """Tests for find_kicad_cli function."""

    def test_find_from_env_variable(self, tmp_path):
        """Find CLI from environment variable."""
        cli_path = tmp_path / "kicad-cli"
        cli_path.touch()

        with patch.dict(os.environ, {"KICAD_CLI_PATH": str(cli_path)}):
            result = find_kicad_cli()

        assert result == str(cli_path)

    def test_find_from_path(self):
        """Find CLI from system PATH."""
        with patch('shutil.which') as mock_which:
            mock_which.return_value = "/usr/bin/kicad-cli"
            result = find_kicad_cli()

        assert result == "/usr/bin/kicad-cli"

    def test_not_found_returns_none(self):
        """Return None when CLI not found."""
        with patch.dict(os.environ, {"KICAD_CLI_PATH": ""}):
            with patch('shutil.which', return_value=None):
                with patch('os.path.exists', return_value=False):
                    result = find_kicad_cli()

        assert result is None


class TestRunKicadCli:
    """Tests for run_kicad_cli function."""

    def test_run_successful_command(self):
        """Run a successful CLI command."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="output",
                    stderr=""
                )
                result = run_kicad_cli(["version"])

        assert result["success"] is True
        assert result["stdout"] == "output"

    def test_run_with_cli_not_found(self):
        """Handle CLI not found."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli', return_value=None):
            result = run_kicad_cli(["version"])

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_run_with_timeout(self):
        """Handle command timeout."""
        import subprocess
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)
                result = run_kicad_cli(["test"], timeout=30)

        assert result["success"] is False
        assert "timed out" in result["error"].lower()


class TestGetKicadVersion:
    """Tests for get_kicad_version function."""

    def test_parse_version_string(self):
        """Parse version string correctly."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="8.0.4"
                )
                version = get_kicad_version()

        assert version is not None
        assert version["major"] == 8
        assert version["minor"] == 0
        assert version["patch"] == 4

    def test_version_not_available(self):
        """Handle version not available."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli', return_value=None):
            version = get_kicad_version()

        assert version is None


class TestGenerateBomFromSchematic:
    """Tests for generate_bom_from_schematic function."""

    def test_schematic_not_found(self):
        """Handle missing schematic file."""
        result = generate_bom_from_schematic("/nonexistent/schematic.kicad_sch")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_cli_not_found(self, sample_kicad_project):
        """Handle missing CLI."""
        sch_file = sample_kicad_project / "test_project.kicad_sch"

        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli', return_value=None):
            result = generate_bom_from_schematic(str(sch_file))

        assert result["success"] is False
        assert "CLI not found" in result["error"]

    def test_successful_bom_generation(self, sample_kicad_project):
        """Successful BOM generation."""
        sch_file = sample_kicad_project / "test_project.kicad_sch"

        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                result = generate_bom_from_schematic(str(sch_file))

        assert result["success"] is True
        assert "bom_path" in result


class TestGenerateNetlist:
    """Tests for generate_netlist function."""

    def test_schematic_not_found(self):
        """Handle missing schematic file."""
        result = generate_netlist("/nonexistent/schematic.kicad_sch")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_successful_netlist_generation(self, sample_kicad_project):
        """Successful netlist generation."""
        sch_file = sample_kicad_project / "test_project.kicad_sch"

        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                result = generate_netlist(str(sch_file))

        assert result["success"] is True
        assert "netlist_path" in result


class TestValidateKicadInstallation:
    """Tests for validate_kicad_installation function."""

    def test_kicad_installed(self):
        """Validate installed KiCad."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli') as mock_find:
            mock_find.return_value = "/usr/bin/kicad-cli"
            with patch('parts_mcp.utils.kicad_utils.get_kicad_version') as mock_version:
                mock_version.return_value = {
                    "full_version": "8.0.4",
                    "major": 8,
                    "minor": 0,
                    "patch": 4
                }
                result = validate_kicad_installation()

        assert result["installed"] is True
        assert result["cli_available"] is True
        assert "bom_export" in result["capabilities"]
        assert "drc" in result["capabilities"]

    def test_kicad_not_installed(self):
        """Handle uninstalled KiCad."""
        with patch('parts_mcp.utils.kicad_utils.find_kicad_cli', return_value=None):
            result = validate_kicad_installation()

        assert result["installed"] is False
        assert result["cli_available"] is False
        assert result["capabilities"] == []
