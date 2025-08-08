import unittest
from unittest.mock import patch, MagicMock
import subprocess as sp

from mpm import main


class TestManMCP(unittest.TestCase):
    """Unit tests for the Man MCP server."""

    # --- Test Input Validation ---

    def test_validate_topic_valid(self):
        """Test that validate_topic allows valid inputs."""
        self.assertTrue(main.validate_topic("ls"))
        self.assertTrue(main.validate_topic("python3"))
        self.assertTrue(main.validate_topic("my_script-name"))
        self.assertTrue(main.validate_topic("ls.1"))
        self.assertTrue(main.validate_topic("bash.1.gz"))  # Example with extension

    def test_validate_topic_invalid(self):
        """Test that validate_topic rejects invalid and malicious inputs."""
        self.assertFalse(main.validate_topic("ls; rm -rf /"))
        self.assertFalse(main.validate_topic("ls | grep foo"))
        self.assertFalse(main.validate_topic("$(reboot)"))
        self.assertFalse(main.validate_topic("page with spaces"))
        self.assertFalse(main.validate_topic(""))

    def test_validate_search_query_valid(self):
        """Test that validate_search_query allows valid inputs."""
        self.assertTrue(main.validate_search_query("printf"))
        self.assertTrue(main.validate_search_query("copy files"))
        self.assertTrue(main.validate_search_query("network.*(socket|bind)"))

    def test_validate_search_query_invalid(self):
        """Test that validate_search_query rejects invalid and malicious inputs."""
        self.assertFalse(main.validate_search_query("`reboot`"))
        self.assertFalse(main.validate_search_query("search; ls"))
        self.assertFalse(main.validate_search_query("bad<char"))

    # --- Test execute_call ---

    @patch("mpm.main.sp.run")
    def test_execute_call_success(self, mock_sp_run):
        """Test execute_call for a successful command execution."""
        mock_process = MagicMock(spec=sp.CompletedProcess)
        mock_process.returncode = 0
        mock_process.stdout = "Success"
        mock_process.stderr = ""
        mock_sp_run.return_value = mock_process

        result = main.execute_call(["man", "ls"])

        self.assertIsInstance(result, sp.CompletedProcess)
        self.assertEqual(result.stdout, "Success")
        mock_sp_run.assert_called_once_with(
            ["man", "ls"], capture_output=True, timeout=5, text=True
        )

    @patch("mpm.main.sp.run")
    def test_execute_call_failure(self, mock_sp_run):
        """Test execute_call for a failed command execution (non-zero return code)."""
        mock_process = MagicMock(spec=sp.CompletedProcess)
        mock_process.returncode = 1
        mock_process.stdout = "No manual entry for foobar"
        mock_process.stderr = "Error"
        mock_sp_run.return_value = mock_process

        result = main.execute_call(["man", "foobar"])

        self.assertIsInstance(result, main.ManError)
        self.assertEqual(result.return_code, 1)
        self.assertIn("Non zero return code", result.note)
        self.assertIn("No manual entry for", result.note)

    @patch("mpm.main.sp.run", side_effect=sp.TimeoutExpired(cmd="man ls", timeout=5))
    def test_execute_call_timeout(self, mock_sp_run):
        """Test execute_call for a command that times out."""
        result = main.execute_call(["man", "ls"])

        self.assertIsInstance(result, main.ManError)
        self.assertEqual(result.return_code, -1)
        self.assertIn("Timeout exception", result.note)

    @patch("mpm.main.sp.run", side_effect=Exception("Unexpected error"))
    def test_execute_call_unknown_exception(self, mock_sp_run):
        """Test execute_call for an unknown exception."""
        result = main.execute_call(["man", "ls"])

        self.assertIsInstance(result, main.ManError)
        self.assertEqual(result.return_code, -1)
        self.assertIn("Unknown exception", result.note)

    # --- Test Tool Functions ---

    @patch("mpm.main.execute_call")
    def test_get_manpage_success(self, mock_execute_call):
        """Test the get_manpage tool for a successful retrieval."""
        mock_process = MagicMock(spec=sp.CompletedProcess)
        mock_process.stdout = "LS(1) User Commands LS(1)"
        mock_execute_call.return_value = mock_process

        result = main.get_manpage("ls")

        self.assertIsInstance(result.result, main.ManPage)
        self.assertEqual(result.result.text, "LS(1) User Commands LS(1)")
        mock_execute_call.assert_called_once_with(args=["man", "ls"])

    @patch("mpm.main.execute_call")
    def test_get_manpage_with_section_success(self, mock_execute_call):
        """Test get_manpage with a section number."""
        mock_process = MagicMock(spec=sp.CompletedProcess)
        mock_process.stdout = "PRINTF(3) Linux Programmer's Manual PRINTF(3)"
        mock_execute_call.return_value = mock_process

        result = main.get_manpage("printf", section=3)

        self.assertIsInstance(result.result, main.ManPage)
        self.assertEqual(
            result.result.text, "PRINTF(3) Linux Programmer's Manual PRINTF(3)"
        )
        mock_execute_call.assert_called_once_with(args=["man", "3", "printf"])

    def test_get_manpage_invalid_input(self):
        """Test get_manpage with invalid characters in the page name."""
        result = main.get_manpage("ls; id")
        self.assertIsInstance(result.result, main.InputValidationError)
        self.assertEqual(result.result.input, "ls; id")

    @patch("mpm.main.execute_call")
    def test_get_manpage_error_from_call(self, mock_execute_call):
        """Test get_manpage when execute_call returns an error."""
        error = main.ManError(
            stdout="", stderr="some error", return_code=1, note="Failed"
        )
        mock_execute_call.return_value = error

        result = main.get_manpage("nonexistentpage")

        self.assertIsInstance(result.result, main.ManError)
        self.assertEqual(result.result.note, "Failed")

    @patch("mpm.main.execute_call")
    def test_search_descriptions_success(self, mock_execute_call):
        """Test the search_descriptions tool for a successful search."""
        mock_process = MagicMock(spec=sp.CompletedProcess)
        mock_process.stdout = "ls (1) - list directory contents\n"
        mock_execute_call.return_value = mock_process

        result = main.search_descriptions("list")

        self.assertIsInstance(result.result, main.ManSearchResult)
        self.assertEqual(len(result.result.results), 1)
        self.assertEqual(result.result.results[0], "ls (1) - list directory contents")
        mock_execute_call.assert_called_once_with(["man", "-k", "list"])

    def test_search_descriptions_invalid_input(self):
        """Test search_descriptions with invalid characters in the query."""
        result = main.search_descriptions("`echo hi`")
        self.assertIsInstance(result.result, main.InputValidationError)
        self.assertEqual(result.result.input, "`echo hi`")

