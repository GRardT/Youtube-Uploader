# =============================================================================
# window_manager.py - Window State Manager for YouTube Uploader
# =============================================================================
# Purpose: Manages window visibility and state changes.
#
# Key Features:
# - Window minimize/restore
# - System tray integration support
# - Thread-safe window operations
# =============================================================================


class WindowManager:
    """
    Manages window state and visibility.

    This class handles window operations like minimizing to tray,
    restoring from tray, and managing window visibility states.
    """

    def __init__(self, root, tray_manager=None, log_callback=None):
        """
        Initialize the window manager.

        Args:
            root: Tkinter root window
            tray_manager: SystemTrayManager instance (optional)
            log_callback (callable, optional): Function to call for logging messages
        """
        self.root = root
        self.tray_manager = tray_manager
        self.log_callback = log_callback

    def log(self, message):
        """
        Logs a message using the callback if provided.

        Args:
            message (str): Message to log
        """
        if self.log_callback:
            self.log_callback(message)

    def minimize_to_tray(self):
        """
        Minimizes window to system tray instead of taskbar.
        """
        try:
            self.root.withdraw()  # Hide window
            if self.tray_manager:
                self.tray_manager.show()
            self.log("Minimized to system tray")
        except Exception as e:
            self.log(f"Error minimizing to tray: {str(e)}")

    def restore_from_tray(self):
        """
        Restores window from system tray.
        """
        try:
            self.root.deiconify()  # Show window
            self.root.lift()  # Bring to front
            if self.tray_manager:
                self.tray_manager.hide()
        except Exception as e:
            self.log(f"Error restoring window: {str(e)}")

    def show(self):
        """
        Shows the window (alias for restore_from_tray for clarity).
        """
        self.restore_from_tray()

    def hide(self):
        """
        Hides the window (alias for minimize_to_tray for clarity).
        """
        self.minimize_to_tray()
