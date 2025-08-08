from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
import subprocess as sp
from pydantic import BaseModel, Field
import logging
import re

mcp = FastMCP("Man MCP")

LOG = logging.getLogger("man_mcp")
LOG.setLevel(logging.INFO)
LOG.addHandler(logging.StreamHandler())

# Allow alphanumeric strings, optionally followed by a dot
# and a number indicating section.
ALLOWED_TOPIC_INPUT = re.compile(r"^[a-zA-Z0-9_\-]+(\.[a-zA-Z0-9_]+)*$")

# Allow all characters needed for regular expression search
ALLOWED_SEARCH_INPUT = re.compile(
    r"^[a-zA-Z0-9\s\.\,\:\/'\"\(\)\[\]\{\}\*\+\?\|\^\$_\-]+$"
)


class InputValidationError(BaseModel):
    """Issue encountered while validating input"""

    input: str = Field(description="Original input")
    note: str = Field(description="Information about possible cause")


class ManError(BaseModel):
    """Description of error encountered while calling `man`"""

    stdout: str = Field(description="Standard output stream capture")
    stderr: str = Field(description="Standard error stream capture")
    return_code: int = Field(description="Return code of executed `man`")
    note: str = Field(description="Note on issues encountered during execution")


class ManSearchResult(BaseModel):
    """Results from execution of man search with either `man -k`."""

    results: list[str] = Field(
        description="List of pages where given pattern was found"
    )


class ManPage(BaseModel):
    """Contents of man page"""

    text: str = Field(description="Contents of requested man page")


class ManResult(BaseModel):
    """General result of the tool call. Used to ensure that parsed JSON matches
    the structured MCP content."""

    result: ManError | ManSearchResult | ManPage | InputValidationError = Field(
        description="Result of `man` call, successful or not."
    )


def validate_topic(input: str) -> bool:
    """Verifies that string contains only allowed characters
    in order to prevent shell injection."""

    return bool(ALLOWED_TOPIC_INPUT.fullmatch(input))


def validate_search_query(input: str) -> bool:
    """Veriffies that search query doesn't contain characters that could be
    used to escape shell, and that it matches allowed pattern."""

    return bool(ALLOWED_SEARCH_INPUT.fullmatch(input))


def execute_call(args: list[str]) -> ManError | sp.CompletedProcess[str]:
    """Safely execute call to binary and checks for errors"""
    note = ""
    try:
        LOG.info("Executing `%s` from MCP call", " ".join(args))
        process = sp.run(args, capture_output=True, timeout=5, text=True)
    except sp.TimeoutExpired as ex:
        LOG.error(
            "Timeout encountered while calling `man` with args %s", " ".join(args)
        )
        return ManError(
            stdout="", stderr="", return_code=-1, note=f"Timeout exception {ex}."
        )
    except Exception as ex:
        LOG.error(
            "Unknown exception encountered while calling `man` with args %s",
            " ".join(args),
        )
        return ManError(
            stdout="", stderr="", return_code=-1, note=f"Unknown exception {ex}."
        )

    if process.stderr:
        note += f"Unexpected error encountered: {process.stderr}\n"
    if "No manual entry for " in process.stdout:
        note += f"{process.stdout}\n"
    if process.returncode != 0:
        note += f"Non zero return code `{process.returncode}`\n"

    if note:
        LOG.error(
            "error encountered while attempting to retrieve page with `man` error: \n%s",
            note,
        )
        return ManError(
            stdout=process.stdout,
            stderr=process.stderr,
            return_code=process.returncode,
            note=note,
        )
    return process


@mcp.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True))
def search_descriptions(query: str) -> ManResult:
    """Search descriptions of man pages for given string or pattern"""

    if not validate_search_query(query):
        LOG.error("Invalid input '%s' submitted", query)

        return ManResult(
            result=InputValidationError(
                input=query, note="Query contains invalid characters"
            )
        )

    out = execute_call(["man", "-k", query])

    if isinstance(out, ManError):
        return ManResult(result=out)
    results = out.stdout.splitlines()
    LOG.info("MCP call successful, returning %d matches in man pages", len(results))
    return ManResult(result=ManSearchResult(results=results))


@mcp.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True))
def get_manpage(page: str, section: int | None = None) -> ManResult:
    """Retrieve specific man page."""

    if not validate_topic(page):
        LOG.error("Invalid input '%s' submitted", page)

        return ManResult(
            result=InputValidationError(
                input=page,
                note=(
                    "Page name must contain only alphanumeric characters, underscores and dashes. "
                    "Optionally followed by a '.' and number for section."
                ),
            )
        )

    if section:
        args = ["man", str(section), page]
    else:
        args = ["man", page]

    out = execute_call(args=args)

    if isinstance(out, ManError):
        return ManResult(result=out)

    LOG.info("MCP call successful, returning man page '%s'", page)
    return ManResult(result=ManPage(text=out.stdout))


if __name__ == "__main__":
    mcp.run(transport="stdio")
