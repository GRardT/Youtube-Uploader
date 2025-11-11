# =============================================================================
# notification_manager.py - Windows Toast Notification Manager
# =============================================================================
# Purpose: Handles Windows 10/11 toast notifications for YouTube Uploader.
#
# Key Features:
# - Thread-safe toast notifications
# - Graceful degradation when win11toast unavailable
# - Uses win11toast (actively maintained, no WPARAM errors)
# - Non-blocking notification display
# =============================================================================

import threading

# Windows-specific imports (graceful degradation on other platforms)
try:
    from win11toast import toast
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False


class NotificationManager:
    """
    Manages Windows toast notifications.

    This class provides a simple interface for showing toast notifications
    on Windows 10+, with proper error handling and graceful degradation.
    """

    def __init__(self, log_callback=None):
        """
        Initialize the notification manager.

        Args:
            log_callback (callable, optional): Function to call for logging messages.
                Should accept a single string argument.
        """
        self.log_callback = log_callback
        self.available = TOAST_AVAILABLE

    def log(self, message):
        """
        Logs a message using the callback if provided.

        Args:
            message (str): Message to log
        """
        if self.log_callback:
            self.log_callback(message)

    def show_notification(self, title, message, duration=5):
        """
        Shows a Windows toast notification.

        Args:
            title (str): Notification title
            message (str): Notification message
            duration (int): How long to show notification (seconds)
        """
        if not self.available:
            self.log(f"Notification (toast unavailable): {title} - {message}")
            return

        try:
            # Run in background thread to avoid blocking GUI
            def show_toast_async():
                try:
                    # win11toast has a simple API - just call toast() function
                    # No WPARAM errors like win10toast had!
                    # Duration is specified as 'short' or 'long', we'll use 'short' for <= 5s
                    duration_str = 'short' if duration <= 5 else 'long'
                    toast(title, message, duration=duration_str)
                except Exception as e:
                    # Catch any exceptions from win11toast
                    self.log(f"Notification error: {str(e)}")

            thread = threading.Thread(target=show_toast_async, daemon=True)
            thread.start()

        except Exception as e:
            self.log(f"Could not show notification: {str(e)}")

    def is_available(self):
        """
        Check if toast notifications are available.

        Returns:
            bool: True if win11toast is available, False otherwise
        """
        return self.available
