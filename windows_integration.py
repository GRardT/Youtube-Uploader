# =============================================================================
# windows_integration.py - Windows Integration for YouTube Uploader
# =============================================================================
# Purpose: Handles Windows-specific features like startup and shutdown.
#
# Key Features:
# - Windows startup folder integration (run on boot)
#   - Creates direct shortcut to main.pyw in startup folder
#   - Registers shortcut in StartupApproved registry for Task Manager visibility
#   - Removes Zone.Identifier security flag to prevent blocking
# - Shutdown handler (graceful shutdown on Windows shutdown)
# - Graceful degradation on non-Windows platforms
# =============================================================================

import sys
import os
import ctypes

import config

try:
    import winreg
except ImportError:
    winreg = None

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
        Adds a shortcut to the Windows startup folder and registers it for auto-start.

        This method performs several steps to ensure the shortcut works at boot:
        1. Creates a direct shortcut to main.pyw in the Windows Startup folder
        2. Sets WindowStyle to Normal (not minimized/maximized)
        3. Removes Zone.Identifier security flag to prevent Windows from blocking it
        4. Registers the shortcut in StartupApproved registry for Task Manager visibility

        The shortcut will appear in Task Manager's Startup tab and will execute
        automatically when Windows boots.

        Note: Windows automatically associates .pyw files with pythonw.exe, so the
        shortcut points directly to main.pyw rather than pythonw.exe with arguments.

        Raises:
            RuntimeError: If Windows startup integration is not available
        """
        if not self.startup_available:
            raise RuntimeError("Windows startup integration not available")

        # Get startup folder path
        startup_folder = winshell.startup()

        # Create shortcut path
        shortcut_path = os.path.join(startup_folder, config.WINDOWS_STARTUP_SHORTCUT_NAME)

        # Get path to main.pyw (in same directory as this file)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, 'main.pyw')

        # Create shortcut directly to main.pyw
        # Windows will automatically use pythonw.exe for .pyw files
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.TargetPath = main_script
        shortcut.WorkingDirectory = script_dir
        shortcut.WindowStyle = 1  # 1=Normal, 3=Maximized, 7=Minimized
        shortcut.Description = f"{config.APP_NAME} - Automatic YouTube Uploader"
        shortcut.save()

        # Remove Zone.Identifier to prevent Windows from blocking the shortcut
        # Programmatically created files may be marked as "from internet"
        try:
            zone_identifier = shortcut_path + ':Zone.Identifier'
            if os.path.exists(zone_identifier):
                os.remove(zone_identifier)
        except Exception as e:
            self.log(f"Warning: Could not remove Zone.Identifier: {str(e)}")

        # Register the shortcut in StartupApproved registry
        # This is required for the shortcut to appear in Task Manager and actually run at startup
        self._register_startup_approved(config.WINDOWS_STARTUP_SHORTCUT_NAME)

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

        # Unregister from StartupApproved registry
        self._unregister_startup_approved(config.WINDOWS_STARTUP_SHORTCUT_NAME)

    def _register_startup_approved(self, shortcut_name):
        """
        Registers the shortcut in the StartupApproved registry key.

        This is required for the shortcut to appear in Task Manager's startup tab
        and to actually run at Windows startup. Without this registry entry, the
        shortcut exists but Windows won't execute it on boot.

        Args:
            shortcut_name (str): Name of the shortcut file (e.g., "YouTube Uploader.lnk")
        """
        if not winreg:
            self.log("Warning: winreg not available, cannot register StartupApproved")
            return

        try:
            # Open/create the StartupApproved\StartupFolder key
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)

            # Set binary value: 02 00 00 00 00 00 00 00 00 00 00 00 (enabled)
            # First DWORD = 0x02 means enabled, remaining 8 bytes = 0 (no disable timestamp)
            enabled_value = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            winreg.SetValueEx(key, shortcut_name, 0, winreg.REG_BINARY, enabled_value)
            winreg.CloseKey(key)

            self.log(f"Registered '{shortcut_name}' in StartupApproved registry")
        except Exception as e:
            self.log(f"Warning: Could not register StartupApproved: {str(e)}")

    def _unregister_startup_approved(self, shortcut_name):
        """
        Removes the shortcut from the StartupApproved registry key.

        Args:
            shortcut_name (str): Name of the shortcut file (e.g., "YouTube Uploader.lnk")
        """
        if not winreg:
            return

        try:
            # Open the StartupApproved\StartupFolder key
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)

            # Delete the value
            winreg.DeleteValue(key, shortcut_name)
            winreg.CloseKey(key)

            self.log(f"Unregistered '{shortcut_name}' from StartupApproved registry")
        except FileNotFoundError:
            # Key or value doesn't exist, that's fine
            pass
        except Exception as e:
            self.log(f"Warning: Could not unregister StartupApproved: {str(e)}")
