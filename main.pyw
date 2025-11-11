# =============================================================================
# main.py - YouTube Uploader v2.0 Entry Point
# =============================================================================
# Purpose: Application entry point that orchestrates all modules.
#
# Initialization Flow:
# 1. Validate configuration
# 2. Setup global exception handler
# 3. Create managers (state, file, auth, upload)
# 4. Initialize GUI
# 5. Run application
#
# This is the ONLY file that should be executed directly.
# Run with: pythonw main.py (to hide console window)
# =============================================================================

import sys
import traceback
from tkinter import messagebox

# Import configuration first (validates on import)
import config

# Import all manager classes
from auth_manager import AuthManager, AuthenticationError
from file_handler import FileHandler
from state_manager import StateManager
from upload_manager import UploadManager, QuotaExceededError
from gui import YouTubeUploaderGUI


class Application:
    """
    Main application orchestrator.
    
    This class initializes all components in the correct order and
    handles any fatal errors during startup.
    
    Attributes:
        auth_manager: AuthManager instance (handles YouTube authentication)
        file_handler: FileHandler instance (handles file operations)
        state_manager: StateManager instance (handles persistence)
        upload_manager: UploadManager instance (handles uploads)
        gui: YouTubeUploaderGUI instance (handles user interface)
    """
    
    def __init__(self):
        """
        Initialize the application.
        
        Raises:
            Exception: If any critical initialization step fails
        """
        # List to store log messages before GUI is ready
        self.startup_logs = []
        
        # References to managers (initialized in setup)
        self.auth_manager = None
        self.file_handler = None
        self.state_manager = None
        self.upload_manager = None
        self.gui = None
        
    def _startup_log(self, message):
        """
        Logs messages during startup (before GUI is ready).
        
        These messages are displayed in the GUI log once it's initialized.
        
        Args:
            message (str): Message to log
        """
        print(f"[STARTUP] {message}")
        self.startup_logs.append(message)
    
    def _setup_global_exception_handler(self):
        """
        Installs a global exception handler to catch unhandled exceptions.
        
        This prevents the app from crashing silently and helps with debugging.
        All unhandled exceptions are logged to the GUI (if available) or stderr.
        """
        def global_exception_handler(exc_type, exc_value, exc_traceback):
            """
            Handler for uncaught exceptions.
            
            Args:
                exc_type: Exception class
                exc_value: Exception instance
                exc_traceback: Traceback object
            """
            # Don't log KeyboardInterrupt (Ctrl+C)
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            # Format the exception
            error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            
            # Log to GUI if available
            if self.gui:
                self.gui.log("=" * 60)
                self.gui.log("UNHANDLED EXCEPTION:")
                self.gui.log(error_msg)
                self.gui.log("=" * 60)
            else:
                # GUI not available, log to stderr
                print(error_msg, file=sys.stderr)
            
            # Show error dialog
            try:
                messagebox.showerror(
                    "Unhandled Exception",
                    f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
                    "Check the log for details."
                )
            except:
                pass  # If GUI isn't available, ignore
        
        # Install the handler
        sys.excepthook = global_exception_handler
        self._startup_log("Global exception handler installed")
    
    def _initialize_managers(self):
        """
        Initializes all manager classes in the correct order.
        
        Order matters:
        1. FileHandler (no dependencies)
        2. StateManager (no dependencies)
        3. AuthManager (needs internet, may prompt for auth)
        4. UploadManager (needs all of the above)
        
        Raises:
            Exception: If any manager fails to initialize
        """
        self._startup_log("Initializing managers...")
        
        # Step 1: Create FileHandler (no dependencies)
        self._startup_log("Creating FileHandler...")
        self.file_handler = FileHandler(logger=self._startup_log)
        self._startup_log("FileHandler created successfully")
        
        # Step 2: Create StateManager (no dependencies)
        self._startup_log("Creating StateManager...")
        self.state_manager = StateManager(logger=self._startup_log)
        self._startup_log("StateManager created successfully")
        
        # Display state statistics
        stats = self.state_manager.get_statistics()
        self._startup_log(f"Loaded state: {stats['total_uploads']} total uploads")
        if stats['pending_uploads'] > 0:
            self._startup_log(f"  - {stats['pending_uploads']} pending uploads")
        if stats['in_quota_cooldown']:
            self._startup_log("  - Currently in quota cooldown")
        
        # Step 3: Create AuthManager (may take time for internet/auth)
        self._startup_log("Creating AuthManager...")
        self.auth_manager = AuthManager(logger=self._startup_log)
        
        # Initialize YouTube client (this may open browser for first-time auth)
        self._startup_log("Initializing YouTube client (may open browser)...")
        try:
            self.auth_manager.initialize_youtube_client()
        except AuthenticationError as e:
            self._startup_log(f"Authentication failed: {str(e)}")
            messagebox.showerror(
                "Authentication Error",
                f"Failed to authenticate with YouTube:\n\n{str(e)}\n\n"
                "Please check your client_secrets.json and internet connection."
            )
            raise
        
        self._startup_log("YouTube client initialized successfully")
        
        # Step 4: Create UploadManager (depends on all above)
        self._startup_log("Creating UploadManager...")
        self.upload_manager = UploadManager(
            youtube_client=self.auth_manager.get_client(),
            file_handler=self.file_handler,
            state_manager=self.state_manager,
            logger=self._startup_log
        )
        self._startup_log("UploadManager created successfully")
        
        self._startup_log("All managers initialized successfully")
    
    def _initialize_gui(self):
        """
        Initializes the GUI and transfers startup logs to it.
        
        Raises:
            Exception: If GUI creation fails
        """
        self._startup_log("Creating GUI...")
        
        # Create GUI (passes all managers to it)
        self.gui = YouTubeUploaderGUI(
            auth_manager=self.auth_manager,
            file_handler=self.file_handler,
            state_manager=self.state_manager,
            upload_manager=self.upload_manager
        )
        
        # Transfer startup logs to GUI
        for log_message in self.startup_logs:
            self.gui.log(log_message)
        
        # Clear startup logs (no longer needed)
        self.startup_logs = []
        
        self._startup_log("GUI created successfully")
    
    def run(self):
        """
        Main application entry point.
        
        This orchestrates the entire initialization sequence and starts the GUI.
        
        Returns:
            int: Exit code (0 = success, 1 = error)
        """
        try:
            # Step 1: Validate configuration
            print("[STARTUP] Validating configuration...")
            config.validate_config()
            print("[STARTUP] Configuration valid")
            
            # Step 2: Setup exception handler
            self._setup_global_exception_handler()
            
            # Step 3: Initialize managers
            self._initialize_managers()
            
            # Step 4: Initialize GUI
            self._initialize_gui()
            
            # Step 5: Run GUI main loop (blocks until window closed)
            self._startup_log("Starting application...")
            self._startup_log("=" * 60)
            self.gui.run()
            
            # If we get here, user closed the window normally
            print("[SHUTDOWN] Application closed normally")
            return 0
            
        except FileNotFoundError as e:
            # Configuration file missing (e.g., client_secrets.json)
            error_msg = str(e)
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            
            try:
                messagebox.showerror(
                    "Configuration Error",
                    error_msg
                )
            except:
                pass
            
            return 1
            
        except AuthenticationError as e:
            # Authentication failed (already showed error dialog in _initialize_managers)
            print(f"[ERROR] Authentication failed: {str(e)}", file=sys.stderr)
            return 1
            
        except Exception as e:
            # Unexpected error during initialization
            error_msg = f"Failed to start application: {str(e)}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            traceback.print_exc()
            
            try:
                messagebox.showerror(
                    "Startup Error",
                    f"{error_msg}\n\nSee console for details."
                )
            except:
                pass
            
            return 1


def main():
    """
    Main entry point for the application.
    
    This is the function that gets called when you run: pythonw main.py
    
    Returns:
        int: Exit code (0 = success, 1 = error)
    """
    # Print startup banner
    print("=" * 60)
    print(f"{config.APP_NAME} v{config.APP_VERSION}")
    print("=" * 60)
    
    # Create and run application
    app = Application()
    exit_code = app.run()
    
    # Print shutdown banner
    print("=" * 60)
    print("Application terminated")
    print("=" * 60)
    
    return exit_code


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    """
    This block runs when the script is executed directly.
    
    Usage:
        python main.py      # With console window
        pythonw main.py     # Without console window (recommended)
    """
    sys.exit(main())
