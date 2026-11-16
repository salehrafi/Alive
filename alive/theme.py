"""Flat, sharp-edged light/dark themes. No radius, shadows or gradients anywhere.

Typography lives in code (font()), not in the stylesheet: any `font-family` rule
in a Qt stylesheet makes Qt load the entire system font database, which was
measured at +13 MB private memory and ~650 extra handles.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str      # subtle panel/hover tone
    line: str         # hairlines and outlines
    text: str
    muted: str
    primary_bg: str   # primary button fill
    primary_fg: str
    disabled: str
    green: str
    red: str
    orange: str


LIGHT = Palette(
    name="light",
    bg="#FFFFFF", surface="#F3F3F3", line="#E2E2E2",
    text="#0A0A0A", muted="#6A6A6A",
    primary_bg="#0A0A0A", primary_fg="#FFFFFF", disabled="#BDBDBD",
    # Accents darkened enough for >= 4.5:1 contrast on white.
    green="#12813A", red="#C42B1C", orange="#B45309",
)

DARK = Palette(
    name="dark",
    bg="#0B0B0B", surface="#171717", line="#2A2A2A",
    text="#F2F2F2", muted="#9C9C9C",
    primary_bg="#F2F2F2", primary_fg="#0B0B0B", disabled="#4A4A4A",
    # Lighter accents for dark backgrounds.
    green="#3DDC7A", red="#FF6B5E", orange="#FFB547",
)


def font(family: str = "Segoe UI", pt: float = 10, weight: int = 400, spacing: float = 0):
    from PySide6.QtGui import QFont
    f = QFont(family)
    f.setPointSizeF(pt)
    f.setWeight(QFont.Weight(weight))
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def palette(name: str) -> Palette:
    return DARK if name == "dark" else LIGHT


def stylesheet(p: Palette, assets_dir: str = "") -> str:
    arrow = f"{assets_dir}/arrow_{p.name}.png".replace("\\", "/")
    return f"""
* {{ border-radius: 0px; outline: none; }}
QWidget#root {{ background: {p.bg}; }}
QWidget {{ color: {p.text}; }}
QLabel {{ background: transparent; }}
QLabel#tagline, QLabel#elapsed, QLabel#key {{ color: {p.muted}; }}
QFrame#rule {{ background: {p.line}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{
    border: 1px solid {p.text}; background: {p.bg}; color: {p.text};
    padding: 0 18px; min-height: 42px;
}}
QPushButton:hover {{ background: {p.surface}; }}
QPushButton:pressed {{ background: {p.line}; }}
QPushButton:disabled {{ border-color: {p.disabled}; color: {p.disabled}; background: {p.bg}; }}
QPushButton#primary {{ background: {p.primary_bg}; color: {p.primary_fg}; border-color: {p.primary_bg}; }}
QPushButton#primary:hover {{ background: {p.muted}; border-color: {p.muted}; }}
QPushButton#primary:disabled {{ background: {p.disabled}; border-color: {p.disabled}; color: {p.bg}; }}
QPushButton#small {{
    border: 1px solid {p.line}; min-height: 24px; max-height: 24px; padding: 0 10px; color: {p.text};
}}
QPushButton#small:hover {{ border-color: {p.text}; background: {p.bg}; }}
QPushButton#small:disabled {{ color: {p.disabled}; border-color: {p.line}; }}
QSlider::groove:horizontal {{ height: 2px; background: {p.line}; border: none; }}
QSlider::sub-page:horizontal {{ background: {p.text}; border: none; }}
QSlider::add-page:horizontal {{ background: {p.line}; border: none; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; background: {p.text}; border: none; }}
QSlider::handle:horizontal:hover {{ background: {p.muted}; }}
QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled {{ background: {p.disabled}; }}
QMessageBox {{ background: {p.bg}; }}
QPushButton#themeToggle {{
    border: 1px solid {p.line}; min-height: 28px; max-height: 28px; padding: 0 10px;
    color: {p.muted};
}}
QPushButton#themeToggle:hover {{ color: {p.text}; border-color: {p.text}; background: {p.bg}; }}

QComboBox {{
    border: 1px solid {p.line}; background: {p.bg}; color: {p.text};
    padding: 4px 8px; min-height: 22px;
}}
QComboBox:hover {{ border-color: {p.text}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {p.text}; background: {p.bg}; color: {p.text};
    selection-background-color: {p.primary_bg}; selection-color: {p.primary_fg}; outline: none; padding: 0;
}}

QMenu {{ background: {p.bg}; color: {p.text}; border: 1px solid {p.text}; padding: 0; }}
QMenu::item {{ padding: 7px 22px; }}
QMenu::item:selected {{ background: {p.primary_bg}; color: {p.primary_fg}; }}
QMenu::item:disabled {{ color: {p.disabled}; }}
QMenu::separator {{ height: 1px; background: {p.line}; margin: 0; }}
QToolTip {{ background: {p.bg}; color: {p.text}; border: 1px solid {p.text}; padding: 4px; }}
"""
