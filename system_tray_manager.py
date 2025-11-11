# =============================================================================
# system_tray_manager.py - System Tray Manager for YouTube Uploader
# =============================================================================
# Purpose: Manages the system tray icon and context menu.
#
# Key Features:
# - System tray icon with custom image
# - Context menu for restore and exit
# - Graceful fallback to colored square icon
# =============================================================================

import os
from PIL import Image
import pystray

import config


class SystemTrayManager:
    """
    Manages the system tray icon and menu.

    This class handles creating and managing the system tray icon,
    including the context menu and icon visibility.
    """

    def __init__(self, on_show_callback, on_quit_callback, log_callback=None):
        """
        Initialize the system tray manager.

        Args:
            on_show_callback (callable): Function to call when user clicks "Show"
            on_quit_callback (callable): Function to call when user clicks "Exit"
            log_callback (callable, optional): Function to call for logging messages
        """
        self.on_show_callback = on_show_callback
        self.on_quit_callback = on_quit_callback
        self.log_callback = log_callback
        self.tray_icon = None

    def log(self, message):
        """
        Logs a message using the callback if provided.

        Args:
            message (str): Message to log
        """
        if self.log_callback:
            self.log_callback(message)

    def setup(self):
        """
        Creates and initializes the system tray icon.

        Uses custom icon from assets/ if available, otherwise creates a colored square.
        """
        try:
            # Try to load custom icon from file
            if os.path.exists(config.ICON_PATH):
                icon_image = Image.open(config.ICON_PATH)
                # Resize to tray icon size
                icon_image = icon_image.resize(
                    (config.TRAY_ICON_SIZE, config.TRAY_ICON_SIZE),
                    Image.Resampling.LANCZOS
                )
                self.log(f"Loaded tray icon from {config.ICON_PATH}")
            else:
                # Fallback: create simple colored square
                icon_image = Image.new(
                    'RGB',
                    (config.TRAY_ICON_SIZE, config.TRAY_ICON_SIZE),
                    color=config.FALLBACK_TRAY_ICON_COLOR
                )
                self.log(f"Using fallback tray icon ({config.FALLBACK_TRAY_ICON_COLOR} square)")

            # Create context menu
            menu = (
                pystray.MenuItem("Show", self._on_show_clicked),
                pystray.MenuItem("Exit", self._on_quit_clicked)
            )

            # Create icon
            self.tray_icon = pystray.Icon(
                "youtube_uploader",
                icon_image,
                config.APP_NAME,
                menu
            )

            # Run in detached mode (non-blocking)
            self.tray_icon.run_detached()

            self.log("System tray icon created")

        except Exception as e:
            self.log(f"Warning: Could not create system tray icon: {str(e)}")

    def _on_show_clicked(self, icon=None):
        """
        Internal handler for "Show" menu item.

        Args:
            icon: System tray icon (unused, required by pystray)
        """
        if self.on_show_callback:
            self.on_show_callback()

    def _on_quit_clicked(self, icon=None):
        """
        Internal handler for "Exit" menu item.

        Args:
            icon: System tray icon (unused, required by pystray)
        """
        if self.on_quit_callback:
            self.on_quit_callback()

    def show(self):
        """
        Makes the tray icon visible.
        """
        if self.tray_icon:
            self.tray_icon.visible = True

    def hide(self):
        """
        Hides the tray icon.
        """
        if self.tray_icon:
            self.tray_icon.visible = False

    def stop(self):
        """
        Stops and removes the tray icon.
        """
        if self.tray_icon:
            try:
                self.tray_icon.visible = False
                self.tray_icon.stop()
            except Exception as e:
                self.log(f"Error stopping tray icon: {str(e)}")
