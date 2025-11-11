# =============================================================================
# gui_components.py - GUI Component Helpers for YouTube Uploader
# =============================================================================
# Purpose: Provides reusable GUI widget creation utilities.
#
# Key Features:
# - Tooltip creation with hover delay
# - Consistent widget styling
# - Reduces code duplication in GUI setup
# =============================================================================

import tkinter as tk


class TooltipHelper:
    """
    Helper class for creating tooltips on widgets.

    Tooltips appear after a short delay when hovering over widgets,
    and disappear when the mouse leaves.
    """

    @staticmethod
    def create_tooltip(widget, text):
        """
        Creates a tooltip for a widget.

        Args:
            widget: The tkinter widget to attach the tooltip to
            text (str): The tooltip text to display
        """
        tooltip_window = None
        scheduled_show = None

        def on_enter(event):
            nonlocal tooltip_window, scheduled_show
            # Cancel any previously scheduled tooltip
            if scheduled_show is not None:
                widget.after_cancel(scheduled_show)
                scheduled_show = None

            # Destroy any existing tooltip first
            if tooltip_window is not None:
                try:
                    tooltip_window.destroy()
                except:
                    pass
                tooltip_window = None

            # Create new tooltip after short delay (prevents flicker on quick hover)
            def show_tooltip():
                nonlocal tooltip_window, scheduled_show
                scheduled_show = None  # Clear the scheduled ID
                if tooltip_window is None:  # Only create if not cancelled
                    tooltip_window = tk.Toplevel()
                    tooltip_window.wm_overrideredirect(True)
                    tooltip_window.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                    label = tk.Label(
                        tooltip_window,
                        text=text,
                        background="#ffffe0",
                        relief=tk.SOLID,
                        borderwidth=1,
                        font=("Arial", 9),
                        padx=5,
                        pady=3
                    )
                    label.pack()

            # Delay tooltip creation slightly to avoid flicker
            scheduled_show = widget.after(300, show_tooltip)

        def on_leave(event):
            nonlocal tooltip_window, scheduled_show
            # Cancel scheduled tooltip if it hasn't shown yet
            if scheduled_show is not None:
                widget.after_cancel(scheduled_show)
                scheduled_show = None

            # Destroy existing tooltip if visible
            if tooltip_window is not None:
                try:
                    tooltip_window.destroy()
                except:
                    pass
                tooltip_window = None

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
