"""
Reusable Jinja template validation for the generation service.

Compiles a template string with the engine's custom delimiters and
returns structured, user-safe results. Studio's Model Template Editor
reuses this for inline syntax validation.
"""

from __future__ import annotations

from jinja2 import ChainableUndefined, TemplateSyntaxError
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
    template author.
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
    rendered = lenient_env.from_string(content).render()
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
