"""Domain exceptions used to keep failures explicit at subsystem boundaries."""


class CodeAgentError(Exception):
    """Base class for expected, user-facing failures."""


class ConfigurationError(CodeAgentError):
    """Raised when required runtime configuration is missing or invalid."""


class ModelError(CodeAgentError):
    """Raised when the model endpoint fails or returns an invalid response."""


class ToolError(CodeAgentError):
    """Raised when a tool request is invalid or cannot be completed."""


class PathOutsideWorkspaceError(ToolError):
    """Raised when a tool attempts to escape the configured workspace."""


class ApprovalDeniedError(ToolError):
    """Raised when a mutating action is not approved."""

