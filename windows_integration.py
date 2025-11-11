# =============================================================================
# windows_integration.py - Windows Integration for YouTube Uploader
# =============================================================================
# Purpose: Handles Windows-specific features like startup and shutdown.
#
# Key Features:
# - Windows startup folder integration (run on boot)
# - Shutdown handler (graceful shutdown on Windows shutdown)
# - Graceful degradation on non-Windows platforms
# =============================================================================

import sys
import os
import ctypes

import config

# Windows-specific imports (graceful degradation on other platforms)
try:
    import winshell
    from win32com.client import Dispatch
    WINDOWS_STARTUP_AVAILABLE = True
except ImportError:
    WINDOWS_STARTUP_AVAILABLE = False


class WindowsIntegration:
    """
    Manages Windows-specific integrations.

    This class handles Windows startup folder integration and
    shutdown handlers for graceful application termination.
    """

    def __init__(self, log_callback=None):
        """
        Initialize the Windows integration manager.

        Args:
            log_callback (callable, optional): Function to call for logging messages
        """
        self.log_callback = log_callback
        self.startup_available = WINDOWS_STARTUP_AVAILABLE

    def log(self, message):
        """
        Logs a message using the callback if provided.

        Args:
            message (str): Message to log
        """
        if self.log_callback:
            self.log_callback(message)

    def is_startup_available(self):
        """
        Check if Windows startup integration is available.

        Returns:
            bool: True if winshell and pywin32 are available, False otherwise
        """
        return self.startup_available

    def setup_shutdown_handler(self):
        """
        Configures Windows shutdown handling.

        This gives the app time to finish current uploads before
        Windows forces it to close during shutdown.
        """
        try:
            # Set shutdown priority (higher = more time before forced close)
            ctypes.windll.kernel32.SetProcessShutdownParameters(0x4FF, 0)
            self.log("Shutdown handler configured")
        except Exception as e:
            self.log(f"Warning: Could not set shutdown handler: {str(e)}")

    def add_to_startup(self):
        """
        Adds a shortcut to the Windows startup folder.

        The shortcut points to the current Python executable and main.py.
        This ensures the app launches automatically when Windows starts.

        Raises:
            RuntimeError: If Windows startup integration is not available
        """
        if not self.startup_available:
            raise RuntimeError("Windows startup integration not available")

        # Get startup folder path
        startup_folder = winshell.startup()

        # Create shortcut path
        shortcut_path = os.path.join(startup_folder, config.WINDOWS_STARTUP_SHORTCUT_NAME)

        # Get path to current Python executable
        python_exe = sys.executable

        # Get path to main.py (in same directory as this file)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, 'main.py')

        # Create shortcut
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.TargetPath = python_exe
        shortcut.Arguments = f'"{main_script}"'
        shortcut.WorkingDirectory = script_dir
        shortcut.IconLocation = python_exe
        shortcut.Description = f"{config.APP_NAME} - Automatic YouTube Uploader"
        shortcut.save()

    def remove_from_startup(self):
        """
        Removes the shortcut from the Windows startup folder.

        Raises:
            RuntimeError: If Windows startup integration is not available
        """
        if not self.startup_available:
            raise RuntimeError("Windows startup integration not available")

        # Get startup folder path
        startup_folder = winshell.startup()

        # Create shortcut path
        shortcut_path = os.path.join(startup_folder, config.WINDOWS_STARTUP_SHORTCUT_NAME)

        # Remove shortcut if it exists
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
