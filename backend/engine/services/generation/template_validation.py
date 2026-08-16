"""
Reusable Jinja template validation for the generation service.

Compiles a template string with the engine's custom delimiters and
returns structured, user-safe results. Studio's Model Template Editor
reuses this for inline syntax validation.
"""

from __future__ import annotations

from jinja2 import TemplateSyntaxError
from pydantic import BaseModel, ConfigDict

from engine.services.generation.template_resolver import build_jinja_environment


class TemplateValidationError(BaseModel):
    """A single, user-safe template syntax error."""

    model_config = ConfigDict(extra="forbid")

    line: int | None = None
    message: str


class TemplateValidationResult(BaseModel):
    """Outcome of validating a template string."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    error: TemplateValidationError | None = None


def validate_template(content: str) -> TemplateValidationResult:
    """Compile a template string and report whether it is syntactically valid.

    Compile-only: this checks syntax with the engine's custom delimiters
    ([% %] / [[ ]] / [# #]). It does not render, so undefined variables and
    other render-time errors are not reported here. On failure it returns the
    line and message only, never a raw traceback.
    """
    env = build_jinja_environment()
    try:
        env.from_string(content)
        return TemplateValidationResult(valid=True)
    except TemplateSyntaxError as exc:
        return TemplateValidationResult(
            valid=False,
            error=TemplateValidationError(
                line=exc.lineno, message=exc.message or str(exc)
            ),
        )
