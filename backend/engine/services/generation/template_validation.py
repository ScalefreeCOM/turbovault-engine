"""
Reusable Jinja template validation for the generation service.

Compiles a template string with the engine's custom delimiters and
returns structured, user-safe results. Studio's Model Template Editor
reuses this for inline syntax validation.
"""

from __future__ import annotations

import logging

from jinja2 import ChainableUndefined, TemplateSyntaxError
from pydantic import BaseModel, ConfigDict

from engine.services.generation.template_resolver import build_jinja_environment

logger = logging.getLogger(__name__)


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


def validate_template(
    content: str,
    check_python_syntax: bool = False,
) -> TemplateValidationResult:
    """Compile a template string and report whether it is syntactically valid.

    Compile-only Jinja check: uses the engine's custom delimiters
    ([% %] / [[ ]] / [# #]). Undefined variables and render-time errors are
    not reported. On failure returns the line and message only, never a raw
    traceback.

    When ``check_python_syntax=True`` (for SQLMesh Python-model templates),
    the template is additionally rendered with all undefined variables
    substituted by empty strings, and the result is compiled as Python. This
    catches structural Python errors in the static parts of the template.
    String-interpolated variables (e.g. ``name="[[ model_name ]]"``) render
    cleanly as ``name=""``; bare variable references without quotes will
    produce a Python SyntaxError, which is also useful feedback for the
    template author. If the template cannot be rendered without real context
    (any render-time error, e.g. ``UndefinedError`` or a ``TypeError`` from
    ``range(n)``), the Python check is skipped and the template is reported as
    valid.
    """
    env = build_jinja_environment()
    try:
        env.from_string(content)
    except TemplateSyntaxError as exc:
        return TemplateValidationResult(
            valid=False,
            error=TemplateValidationError(
                line=exc.lineno, message=exc.message or str(exc)
            ),
        )

    if not check_python_syntax:
        return TemplateValidationResult(valid=True)

    # Render with undefined variables → empty string, then check Python syntax.
    lenient_env = build_jinja_environment()
    lenient_env.undefined = ChainableUndefined
    try:
        rendered = lenient_env.from_string(content).render()
    except Exception:
        # Without real context a valid template can raise any error type,
        # not only Jinja's: ``[[ (n + 1) | py ]]`` raises UndefinedError,
        # ``[% for i in range(n) %]`` a TypeError, and filters run arbitrary
        # code. The Jinja syntax is already valid, so skip the Python check
        # instead of failing; listing exception types would leave the next
        # one uncaught.
        logger.debug(
            "Skipping Python syntax check: template can't render without context",
            exc_info=True,
        )
        return TemplateValidationResult(valid=True)
    try:
        compile(rendered, "<template>", "exec")
        return TemplateValidationResult(valid=True)
    except SyntaxError as exc:
        return TemplateValidationResult(
            valid=False,
            error=TemplateValidationError(
                line=exc.lineno,
                message=exc.msg or str(exc),
            ),
        )
