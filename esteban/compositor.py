"""Which session we are in, and which surface kind it can safely use.

Two compositor differences decide the shape of the results box:

  layer-shell     Compositors that implement wlr-layer-shell well (Hyprland, Sway, KWin,
                  Wayfire, wlroots-derived compositors generally). An exclusive layer surface
                  gets keyboard focus when it is mapped, which is what a launcher needs.

  toplevel        COSMIC and GNOME. COSMIC does implement wlr-layer-shell, but it treats a
                  commit on a surface whose role has already been destroyed as a protocol
                  violation and quietly drops the client's connection, so a launcher that hides
                  and re-shows its layer surface can kill itself; an XDG toplevel teardown is
                  fine there (this is why projects fall back to a toplevel on COSMIC).
                  GNOME does not implement layer-shell at all.

  x11             A normal undecorated window.

  none            No display session: the TUI in `ui.py`.

Detection reads what the session exports: XDG_CURRENT_DESKTOP / XDG_SESSION_DESKTOP,
XDG_SESSION_TYPE, WAYLAND_DISPLAY, DISPLAY, and the compositor's own marker variables.
`ESTEBAN_SURFACE` overrides the policy (`layer-shell`, `toplevel`, `x11`, `none`).
"""
from __future__ import annotations

import os

LAYER_SHELL = "layer-shell"
TOPLEVEL = "toplevel"
X11 = "x11"
NONE = "none"

# Compositors where hiding and re-showing a layer surface is the normal pattern.
LAYER_SHELL_COMPOSITORS = {
    "Hyprland", "Sway", "Wayfire", "River", "KDE Plasma (KWin)", "Cocoa (Wayland)",
    # A plain toplevel on COSMIC gets the compositor's own decoration frame around the whole surface, which is
    # what made the box read as a framed window. A layer surface is not decorated, and cosmic-comp takes it: on
    # a live session the hide/show cycle the toggle performs keeps the connection. That path needs the
    # GtkLayerShell typelib, and overlay.py says so when the session does not have it.
    "COSMIC",
}

# Compositors where a launcher is better off as a plain window.
TOPLEVEL_COMPOSITORS = {"GNOME"}

# Measured on a live COSMIC session: a plain toplevel keeps the size the compositor gave it when it was
# mapped, so the client cannot change it afterwards (a `resize` request and a changed size request are both
# ignored). The box therefore has to be mapped with room for its rows there and draw its panel only over the
# content, which is what `overlay.py` does when the session is in this set.
NO_CLIENT_RESIZE_COMPOSITORS = {"COSMIC"}


def detect(env: dict | None = None) -> dict:
    """The session: compositor name, display server, and the surface policy to use."""
    env = dict(os.environ) if env is None else env     # an empty env means "no session", not "inherit"
    desktop = (env.get("XDG_CURRENT_DESKTOP") or env.get("XDG_SESSION_DESKTOP") or "").lower()

    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        compositor = "Hyprland"
    elif env.get("SWAYSOCK"):
        compositor = "Sway"
    elif "cosmic" in desktop:
        compositor = "COSMIC"
    elif "kde" in desktop or "plasma" in desktop:
        compositor = "KDE Plasma (KWin)"
    elif "wayfire" in desktop:
        compositor = "Wayfire"
    elif "gnome" in desktop:
        compositor = "GNOME"
    elif env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
        compositor = "unknown Wayland compositor"
    elif env.get("DISPLAY"):
        compositor = "X11"
    else:
        compositor = "no display session"

    return {
        "compositor": compositor,
        "server": server(env, compositor),
        "policy": policy(env, compositor),
    }


def server(env: dict, compositor: str) -> str:
    if compositor in ("X11",):
        return "x11"
    if compositor == "no display session":
        return "none"
    if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "none"


def policy(env: dict, compositor: str) -> str:
    forced = (env.get("ESTEBAN_SURFACE") or "").strip().lower()
    if forced in (LAYER_SHELL, TOPLEVEL, X11, NONE):
        return forced
    if compositor == "no display session":
        return NONE
    if compositor in TOPLEVEL_COMPOSITORS:
        return TOPLEVEL
    if compositor == "X11":
        return X11
    if compositor in LAYER_SHELL_COMPOSITORS:
        return LAYER_SHELL
    # An unknown Wayland compositor: most of them speak wlr-layer-shell, and a layer surface is
    # the only way a client can put itself on top of everything else.
    return LAYER_SHELL


def reason(policy_name: str, compositor: str) -> str:
    """Why this policy, in one line — printed by `esteban doctor`."""
    if policy_name == LAYER_SHELL:
        if compositor == "COSMIC":
            return ("cosmic-comp takes the layer surface and does not draw its window frame around it, which is "
                    "what a box that sizes itself to its content needs there; focus comes from the anchored top "
                    "edge and the exclusive keyboard mode")
        return "wlr-layer-shell is supported and a launcher keeps keyboard focus as an exclusive surface"
    if policy_name == TOPLEVEL:
        if compositor == "COSMIC":
            return ("asked for with ESTEBAN_SURFACE=toplevel: cosmic-comp draws its own frame around a toplevel, "
                    "and the size it gives the surface at mapping is the size it keeps")
        if compositor == "GNOME":
            return "Mutter does not implement layer-shell; an undecorated window is the only option"
        return "plain window"
    if policy_name == X11:
        return "normal undecorated window"
    return "no display: the terminal launcher is used"
