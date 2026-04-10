"""Standardized button styles sourced from the ThemeManager palette."""

from __future__ import annotations

from collections.abc import Callable

from ..theme_manager import get_theme_manager


def _button_style(
    *,
    background: str,
    text: str,
    border: str = "none",
    border_color: str | None = None,
    hover_background: str | None = None,
    hover_text: str | None = None,
    hover_border: str | None = None,
    pressed_background: str | None = None,
    disabled_background: str | None = None,
    disabled_text: str | None = None,
    disabled_border: str | None = None,
    padding_vertical: int = 12,
    padding_horizontal: int = 28,
    font_size: int = 14,
    font_weight: int = 600,
    min_width: int | None = 100,
    border_radius: int = 6,
) -> str:
    """Return a button stylesheet string populated with the provided palette values."""

    def border_line(color: str | None) -> str:
        return f"border: 1px solid {color};" if color else "border: none;"

    min_width_rule = f"min-width: {min_width}px;" if min_width is not None else ""
    lines = [
        "QPushButton {",
        f"    background-color: {background};",
        f"    color: {text};",
        f"    {border_line(border_color) if border == 'auto' else f'border: {border};'}",
        f"    border-radius: {border_radius}px;",
        f"    padding: {padding_vertical}px {padding_horizontal}px;",
        f"    font-size: {font_size}px;",
        f"    font-weight: {font_weight};",
        f"    {min_width_rule}",
        "}",
    ]

    if hover_background or hover_text or hover_border:
        lines.extend(
            [
                "QPushButton:hover {",
                f"    background-color: {hover_background or background};",
                f"    color: {hover_text or text};",
                f"    {border_line(hover_border or border_color) if border == 'auto' else f'border: {hover_border or border};'}",
                "}",
            ]
        )

    if pressed_background:
        lines.extend(
            [
                "QPushButton:pressed {",
                f"    background-color: {pressed_background};",
                "}",
            ]
        )

    if disabled_background or disabled_text or disabled_border:
        lines.extend(
            [
                "QPushButton:disabled {",
                f"    background-color: {disabled_background or background};",
                f"    color: {disabled_text or text};",
                f"    {border_line(disabled_border or border_color) if border == 'auto' else f'border: {disabled_border or border};'}",
                "}",
            ]
        )

    return "\n".join(line for line in lines if line.strip())


def primary_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background=tm.get_color("primary"),
        text=tm.get_color("text_on_primary"),
        hover_background=tm.get_color("primary_dark"),
        pressed_background=tm.get_color("primary_dark"),
        disabled_background=tm.get_color("neutral_100"),
        disabled_text=tm.get_color("text_disabled"),
        padding_vertical=tm.get_spacing("sm") + tm.get_spacing("xs"),
        padding_horizontal=tm.get_spacing("xl"),
        border_radius=tm.get_radius("md"),
    )


def action_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background=tm.get_color("primary"),
        text=tm.get_color("text_on_primary"),
        hover_background=tm.get_color("primary_dark"),
        pressed_background=tm.get_color("primary_dark"),
        disabled_background=tm.get_color("neutral_100"),
        disabled_text=tm.get_color("text_disabled"),
        padding_vertical=tm.get_spacing("sm"),
        padding_horizontal=tm.get_spacing("lg"),
        border_radius=tm.get_radius("md"),
    )


def secondary_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background=tm.get_color("surface_elevated"),
        text=tm.get_color("text_primary"),
        border="auto",
        border_color=tm.get_color("border"),
        hover_background=tm.get_color("neutral_100"),
        hover_text=tm.get_color("text_primary"),
        hover_border=tm.get_color("border_focus"),
        disabled_background=tm.get_color("surface"),
        disabled_text=tm.get_color("text_disabled"),
        disabled_border=tm.get_color("border"),
        padding_vertical=tm.get_spacing("sm") + tm.get_spacing("xs"),
        padding_horizontal=tm.get_spacing("xl"),
        border_radius=tm.get_radius("md"),
    )


def tertiary_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background="transparent",
        text=tm.get_color("text_secondary"),
        border="auto",
        border_color=tm.get_color("border"),
        hover_background=tm.get_color("surface_elevated"),
        hover_text=tm.get_color("text_primary"),
        hover_border=tm.get_color("border_focus"),
        disabled_background="transparent",
        disabled_text=tm.get_color("text_disabled"),
        disabled_border=tm.get_color("border"),
        padding_vertical=tm.get_spacing("sm") + tm.get_spacing("xs"),
        padding_horizontal=tm.get_spacing("lg"),
        border_radius=tm.get_radius("md"),
        min_width=None,
    )


def success_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background=tm.get_color("success"),
        text=tm.get_color("text_on_primary"),
        hover_background=tm.get_color("success_light"),
        pressed_background=tm.get_color("success"),
        disabled_background=tm.get_color("neutral_100"),
        disabled_text=tm.get_color("text_disabled"),
        padding_vertical=tm.get_spacing("sm") + tm.get_spacing("xs"),
        padding_horizontal=tm.get_spacing("xl"),
        border_radius=tm.get_radius("md"),
    )


def destructive_button_style() -> str:
    tm = get_theme_manager()
    return _button_style(
        background=tm.get_color("error"),
        text=tm.get_color("text_on_primary"),
        hover_background=tm.get_color("error_light"),
        pressed_background=tm.get_color("error"),
        disabled_background=tm.get_color("neutral_100"),
        disabled_text=tm.get_color("text_disabled"),
        padding_vertical=tm.get_spacing("sm") + tm.get_spacing("xs"),
        padding_horizontal=tm.get_spacing("xl"),
        border_radius=tm.get_radius("md"),
    )


# Backwards compatible aliases – treat like "constants" by exposing callables
PRIMARY_BUTTON_STYLE: Callable[[], str] = primary_button_style
SECONDARY_BUTTON_STYLE: Callable[[], str] = secondary_button_style
TERTIARY_BUTTON_STYLE: Callable[[], str] = tertiary_button_style
ACTION_BUTTON_STYLE: Callable[[], str] = action_button_style
SUCCESS_BUTTON_STYLE: Callable[[], str] = success_button_style
DESTRUCTIVE_BUTTON_STYLE: Callable[[], str] = destructive_button_style
