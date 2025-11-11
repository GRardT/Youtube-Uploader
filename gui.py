# =============================================================================
# gui.py - YouTube Uploader v2.0 GUI Module
# =============================================================================
# Purpose: Tkinter-based graphical user interface with system tray support.
#
# Key Features:
# - Watch folder selection with automatic monitoring
# - Privacy, playlist, and category dropdowns
# - Single file upload and bulk folder watching
# - Progress bar and status display
# - Scrolling log window
# - System tray minimize/restore
# - Windows shutdown handling
# - User preference persistence
# - Automation settings (auto-start, minimized start, notifications)
# - Windows startup integration
#
# Threading Model:
# - GUI runs on main thread
# - Upload/monitoring runs on background thread
# - All GUI updates use thread-safe methods
# =============================================================================

import tkinter as tk
from tkinter import ttk
import threading
import time
import sys
import os
from datetime import datetime

import config
from notification_manager import NotificationManager
from dialog_manager import DialogManager
from window_manager import WindowManager
from system_tray_manager import SystemTrayManager
from windows_integration import WindowsIntegration
from gui_components import TooltipHelper


class YouTubeUploaderGUI:
    """
    Main GUI application for YouTube Uploader.
    
    This class manages:
    - Tkinter window and widgets
    - System tray icon
    - Background worker thread
    - Event handlers for user actions
    
    Attributes:
        root (tk.Tk): Main Tkinter window
        auth_manager: AuthManager instance
        file_handler: FileHandler instance
        state_manager: StateManager instance
        upload_manager: UploadManager instance
    """
    
    def __init__(self, auth_manager, file_handler, state_manager, upload_manager):
        """
        Initialize the GUI application.

        Args:
            auth_manager: Authenticated AuthManager instance
            file_handler: FileHandler instance
            state_manager: StateManager instance
            upload_manager: UploadManager instance
        """
        # Store references to managers
        self.auth_manager = auth_manager
        self.file_handler = file_handler
        self.state_manager = state_manager
        self.upload_manager = upload_manager

        # Thread control flags
        self.should_stop = False

        # Watch folder path
        self.watch_folder = ""

        # Create main window
        self.root = tk.Tk()
        self.root.title(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.root.geometry(f"{config.GUI_WINDOW_WIDTH}x{config.GUI_WINDOW_HEIGHT}")

        # Set window icon if available
        self._set_window_icon()

        # Initialize component managers
        self.notification_manager = NotificationManager(log_callback=self.log)
        self.dialog_manager = DialogManager()
        self.windows_integration = WindowsIntegration(log_callback=self.log)

        # System tray manager needs callbacks
        self.system_tray_manager = SystemTrayManager(
            on_show_callback=self._on_show_window,
            on_quit_callback=self._on_quit_app,
            log_callback=self.log
        )

        # Window manager needs tray manager reference
        self.window_manager = WindowManager(
            root=self.root,
            tray_manager=self.system_tray_manager,
            log_callback=self.log
        )

        # Handle window close (minimize to tray instead of exiting)
        self.root.protocol("WM_DELETE_WINDOW", self.window_manager.minimize_to_tray)

        # Build GUI components
        self._setup_gui_components()

        # Setup system tray icon
        self.system_tray_manager.setup()

        # Setup Windows shutdown handler
        self.windows_integration.setup_shutdown_handler()

        # Check for incomplete uploads from previous session
        self._check_incomplete_uploads()

        # Populate playlist dropdown from auth_manager
        self._populate_playlist_dropdown()

        # Load user preferences and apply them
        self._load_preferences()

        # Apply automation settings from preferences
        self._apply_automation_preferences()
    
    # -------------------------------------------------------------------------
    # Icon Setup
    # -------------------------------------------------------------------------

    def _set_window_icon(self):
        """
        Sets the window icon if icon file exists.

        Uses icon.png from assets/ folder for window title bar and taskbar.
        Falls back gracefully if icon file doesn't exist.
        """
        try:
            icon_path = config.ICON_PATH
            if os.path.exists(icon_path):
                # Load icon as PhotoImage for tkinter
                icon_image = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon_image)
                # Keep a reference to prevent garbage collection
                self.root.icon_image = icon_image
                self.log(f"Loaded window icon from {icon_path}")
            else:
                self.log(f"Icon file not found at {icon_path}, using default")
        except Exception as e:
            self.log(f"Could not load window icon: {str(e)}")

    # -------------------------------------------------------------------------
    # GUI Component Setup
    # -------------------------------------------------------------------------
    
    def _setup_gui_components(self):
        """
        Creates all GUI widgets and layouts.

        Layout structure:
        - Watch folder selection (top)
        - Privacy, playlist, and category dropdowns
        - Automation Settings panel (collapsible)
        - Next check time and progress bar
        - Control buttons (start/stop/force check/upload file)
        - Log text area (main body)
        - Status bar (bottom)

        All controls include tooltips for user guidance.
        """
        # Use TooltipHelper for creating tooltips
        create_tooltip = TooltipHelper.create_tooltip

        # ===================
        # Watch Folder Frame
        # ===================
        folder_frame = ttk.Frame(self.root)
        folder_frame.pack(fill=tk.X, padx=5, pady=5)

        folder_label = ttk.Label(folder_frame, text="Watch Folder:")
        folder_label.pack(side=tk.LEFT)
        create_tooltip(folder_label, "The folder to monitor for new videos to upload")

        self.folder_path_var = tk.StringVar()
        folder_entry = ttk.Entry(
            folder_frame,
            textvariable=self.folder_path_var
        )
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        create_tooltip(folder_entry, "Path to the folder being monitored\nNew videos added here will be uploaded automatically")

        browse_button = ttk.Button(
            folder_frame,
            text="Browse",
            command=self._on_browse_folder
        )
        browse_button.pack(side=tk.LEFT)
        create_tooltip(browse_button, "Click to select a folder to watch for new videos")

        # ===================
        # Privacy Frame
        # ===================
        privacy_frame = ttk.Frame(self.root)
        privacy_frame.pack(fill=tk.X, padx=5, pady=5)

        privacy_label = ttk.Label(privacy_frame, text="Privacy Setting:")
        privacy_label.pack(side=tk.LEFT)
        create_tooltip(privacy_label, "Who can see your uploaded videos")

        self.privacy_var = tk.StringVar(value=config.DEFAULT_PRIVACY_SETTING)
        self.privacy_combo = ttk.Combobox(
            privacy_frame,
            textvariable=self.privacy_var,
            values=config.PRIVACY_SETTINGS,
            state="readonly",
            width=15
        )
        self.privacy_combo.pack(side=tk.LEFT, padx=5)
        create_tooltip(
            self.privacy_combo,
            "Private: Only you can see\n"
            "Unlisted: Anyone with the link can see\n"
            "Public: Anyone can find and watch"
        )

        # Bind to update upload_manager when changed
        self.privacy_combo.bind('<<ComboboxSelected>>', self._on_privacy_changed)

        # ===================
        # Playlist Frame
        # ===================
        playlist_frame = ttk.Frame(self.root)
        playlist_frame.pack(fill=tk.X, padx=5, pady=5)

        playlist_label = ttk.Label(playlist_frame, text="Playlist:")
        playlist_label.pack(side=tk.LEFT)
        create_tooltip(playlist_label, "Automatically add uploaded videos to this playlist")

        self.playlist_var = tk.StringVar(value="No Playlist")
        self.playlist_combo = ttk.Combobox(
            playlist_frame,
            textvariable=self.playlist_var,
            values=["No Playlist"],  # Will be populated after auth
            state="readonly",
            width=25
        )
        self.playlist_combo.pack(side=tk.LEFT, padx=5)
        create_tooltip(
            self.playlist_combo,
            "Select a playlist to automatically add videos after upload\n"
            "Choose 'No Playlist' to skip playlist addition"
        )

        # Bind to update upload_manager when changed
        self.playlist_combo.bind('<<ComboboxSelected>>', self._on_playlist_changed)

        # Sort Playlist button
        self.sort_playlist_button = ttk.Button(
            playlist_frame,
            text="Sort Playlist",
            command=self._on_sort_playlist
        )
        self.sort_playlist_button.pack(side=tk.LEFT, padx=5)
        create_tooltip(
            self.sort_playlist_button,
            "Sort the selected playlist alphabetically by video title\n"
            "Useful for date-based filenames (e.g., 2025-01-15_clip.mp4)\n"
            "Note: Uses YouTube API quota"
        )

        # ===================
        # Category Frame
        # ===================
        category_frame = ttk.Frame(self.root)
        category_frame.pack(fill=tk.X, padx=5, pady=5)

        category_label = ttk.Label(category_frame, text="Video Category:")
        category_label.pack(side=tk.LEFT)
        create_tooltip(category_label, "YouTube category for uploaded videos")

        self.category_var = tk.StringVar(value=config.DEFAULT_VIDEO_CATEGORY)
        self.category_combo = ttk.Combobox(
            category_frame,
            textvariable=self.category_var,
            values=list(config.VIDEO_CATEGORIES.keys()),
            state="readonly",
            width=20
        )
        self.category_combo.pack(side=tk.LEFT, padx=5)
        create_tooltip(
            self.category_combo,
            "Choose the YouTube category that best fits your videos\n"
            "This helps YouTube recommend your videos to the right audience"
        )

        # Bind to update upload_manager when changed
        self.category_combo.bind('<<ComboboxSelected>>', self._on_category_changed)

        # =====================================
        # Automation Settings (Collapsible)
        # =====================================
        automation_frame = ttk.LabelFrame(self.root, text="⚙ Automation Settings")
        automation_frame.pack(fill=tk.X, padx=5, pady=5)
        create_tooltip(automation_frame, "Configure automatic behavior and Windows integration")

        # Use grid layout with 3 columns for better organization
        # Column 0: Automation controls
        # Column 1: Windows integration
        # Column 2: Toast notifications

        # Autonomous mode checkbox
        self.autonomous_mode_var = tk.BooleanVar(value=config.DEFAULT_AUTONOMOUS_MODE)
        autonomous_check = ttk.Checkbutton(
            automation_frame,
            text="Autonomous Mode (set and forget)",
            variable=self.autonomous_mode_var,
            command=self._on_autonomous_mode_changed
        )
        autonomous_check.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        create_tooltip(
            autonomous_check,
            "Enable fully autonomous operation:\n"
            "- Auto-start watching on app launch\n"
            "- Start minimized to tray\n"
            "- No manual intervention required"
        )

        # Auto-start watching checkbox
        self.auto_start_watching_var = tk.BooleanVar(value=config.DEFAULT_AUTO_START_WATCHING)
        auto_start_check = ttk.Checkbutton(
            automation_frame,
            text="Auto-start watching on launch",
            variable=self.auto_start_watching_var,
            command=self._on_auto_start_watching_changed
        )
        auto_start_check.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        create_tooltip(
            auto_start_check,
            "Automatically begin monitoring the watch folder when app starts\n"
            "No need to click 'Start Watching' button manually"
        )

        # Start minimized checkbox
        self.start_minimized_var = tk.BooleanVar(value=config.DEFAULT_START_MINIMIZED)
        start_minimized_check = ttk.Checkbutton(
            automation_frame,
            text="Start minimized to tray",
            variable=self.start_minimized_var,
            command=self._on_start_minimized_changed
        )
        start_minimized_check.grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        create_tooltip(
            start_minimized_check,
            "Start the app minimized to system tray instead of showing window\n"
            "Useful for running silently in the background"
        )

        # Notify when empty checkbox
        self.notify_when_empty_var = tk.BooleanVar(value=config.DEFAULT_NOTIFY_WHEN_EMPTY)
        notify_empty_check = ttk.Checkbutton(
            automation_frame,
            text="Notify when folder is empty",
            variable=self.notify_when_empty_var,
            command=self._on_notify_when_empty_changed
        )
        notify_empty_check.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        create_tooltip(
            notify_empty_check,
            "Show Windows notification when all videos have been uploaded\n"
            "Lets you know when you can add more videos"
        )

        # Start with Windows checkbox
        self.start_with_windows_var = tk.BooleanVar(value=False)
        start_with_windows_check = ttk.Checkbutton(
            automation_frame,
            text="Start with Windows",
            variable=self.start_with_windows_var,
            command=self._on_start_with_windows_changed
        )
        start_with_windows_check.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        create_tooltip(
            start_with_windows_check,
            "Add YouTube Uploader to Windows startup folder\n"
            "App will launch automatically when Windows starts\n"
            "(Requires restart to take effect)"
        )

        if not self.windows_integration.is_startup_available():
            start_with_windows_check.config(state=tk.DISABLED)
            create_tooltip(
                start_with_windows_check,
                "Windows startup integration not available\n"
                "(Requires pywin32 and winshell packages)"
            )

        # ===================
        # Toast Notifications Column
        # ===================
        # Add a separator label for clarity
        toast_label = ttk.Label(automation_frame, text="📢 Toast Notifications:", font=("Arial", 9, "bold"))
        toast_label.grid(row=0, column=2, sticky=tk.W, padx=(15, 5), pady=(2, 0))
        create_tooltip(toast_label, "Configure which events trigger Windows notifications")

        # Notify upload success
        self.notify_upload_success_var = tk.BooleanVar(value=config.DEFAULT_NOTIFY_UPLOAD_SUCCESS)
        notify_success_check = ttk.Checkbutton(
            automation_frame,
            text="Upload succeeded",
            variable=self.notify_upload_success_var,
            command=self._on_notify_upload_success_changed
        )
        notify_success_check.grid(row=1, column=2, sticky=tk.W, padx=(15, 5), pady=2)
        create_tooltip(
            notify_success_check,
            "Show notification when a video uploads successfully\n"
            "Good for monitoring progress when minimized"
        )

        # Notify upload failed
        self.notify_upload_failed_var = tk.BooleanVar(value=config.DEFAULT_NOTIFY_UPLOAD_FAILED)
        notify_failed_check = ttk.Checkbutton(
            automation_frame,
            text="Upload failed",
            variable=self.notify_upload_failed_var,
            command=self._on_notify_upload_failed_changed
        )
        notify_failed_check.grid(row=2, column=2, sticky=tk.W, padx=(15, 5), pady=2)
        create_tooltip(
            notify_failed_check,
            "Show notification when a video upload fails\n"
            "Alerts you to errors that need attention"
        )

        # Notify quota exceeded
        self.notify_quota_exceeded_var = tk.BooleanVar(value=config.DEFAULT_NOTIFY_QUOTA_EXCEEDED)
        notify_quota_check = ttk.Checkbutton(
            automation_frame,
            text="Quota exceeded",
            variable=self.notify_quota_exceeded_var,
            command=self._on_notify_quota_exceeded_changed
        )
        notify_quota_check.grid(row=3, column=2, sticky=tk.W, padx=(15, 5), pady=2)
        create_tooltip(
            notify_quota_check,
            "Show notification when YouTube API quota is exceeded\n"
            "Lets you know uploads will resume in 24 hours"
        )

        # Notify batch complete
        self.notify_batch_complete_var = tk.BooleanVar(value=config.DEFAULT_NOTIFY_BATCH_COMPLETE)
        notify_batch_check = ttk.Checkbutton(
            automation_frame,
            text="Batch complete",
            variable=self.notify_batch_complete_var,
            command=self._on_notify_batch_complete_changed
        )
        notify_batch_check.grid(row=4, column=2, sticky=tk.W, padx=(15, 5), pady=2)
        create_tooltip(
            notify_batch_check,
            "Show notification when all videos in batch are uploaded\n"
            "Useful for knowing when a large batch finishes"
        )

        # Disable toast checkboxes if win11toast not available
        if not self.notification_manager.is_available():
            for checkbox in [notify_success_check, notify_failed_check, notify_quota_check, notify_batch_check]:
                checkbox.config(state=tk.DISABLED)

        # ===================
        # Next Check Frame
        # ===================
        next_check_frame = ttk.Frame(self.root)
        next_check_frame.pack(fill=tk.X, padx=5, pady=5)

        self.next_check_var = tk.StringVar(value="Next check: Not scheduled")
        next_check_label = ttk.Label(
            next_check_frame,
            textvariable=self.next_check_var
        )
        next_check_label.pack(side=tk.LEFT)
        create_tooltip(next_check_label, "When the app will next check the watch folder for new videos")

        # ===================
        # Progress Frame
        # ===================
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill=tk.X, padx=5, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100
        )
        self.progress_bar.pack(fill=tk.X)
        create_tooltip(self.progress_bar, "Upload progress for current video or batch")

        # ===================
        # Button Frame
        # ===================
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        self.start_button = ttk.Button(
            button_frame,
            text="Start Watching",
            command=self._on_start_watching
        )
        self.start_button.pack(side=tk.LEFT, padx=2)
        create_tooltip(
            self.start_button,
            "Begin monitoring the watch folder for new videos\n"
            "App will automatically upload any videos found"
        )

        self.stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self._on_stop_watching,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=2)
        create_tooltip(
            self.stop_button,
            "Stop monitoring the watch folder\n"
            "Current upload will finish before stopping"
        )

        self.force_check_button = ttk.Button(
            button_frame,
            text="Force Check Now",
            command=self._on_force_check,
            state=tk.DISABLED
        )
        self.force_check_button.pack(side=tk.LEFT, padx=2)
        create_tooltip(
            self.force_check_button,
            "Immediately check the watch folder for new videos\n"
            "Bypasses the normal polling interval"
        )

        self.upload_file_button = ttk.Button(
            button_frame,
            text="Upload File...",
            command=self._on_upload_single_file
        )
        self.upload_file_button.pack(side=tk.LEFT, padx=2)
        create_tooltip(
            self.upload_file_button,
            "Upload a single video file without watching a folder\n"
            "Useful for one-off uploads"
        )

        # Add some spacing before Exit button
        ttk.Frame(button_frame, width=20).pack(side=tk.LEFT)

        self.exit_button = ttk.Button(
            button_frame,
            text="Exit",
            command=self._on_exit_button
        )
        self.exit_button.pack(side=tk.RIGHT, padx=2)
        create_tooltip(
            self.exit_button,
            "Exit the application completely\n"
            "All uploads will stop and app will close"
        )

        # ===================
        # Log Frame
        # ===================
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create scrollbar
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Create text widget
        self.log_text = tk.Text(
            log_frame,
            height=config.GUI_LOG_HEIGHT,
            yscrollcommand=scrollbar.set
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        create_tooltip(self.log_text, "Activity log showing all app operations and status messages")

        scrollbar.config(command=self.log_text.yview)

        # ===================
        # Status Bar
        # ===================
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        create_tooltip(self.status_bar, "Current app status")

        # Initial log message
        self.log("YouTube Uploader initialized successfully")
        self.log(f"Version: {config.APP_VERSION}")
    
    def _populate_playlist_dropdown(self):
        """
        Populates the playlist dropdown with user's playlists from auth_manager.
        """
        playlist_titles = self.auth_manager.get_playlist_titles()
        self.playlist_combo.configure(values=playlist_titles)
        self.playlist_var.set("No Playlist")

    # -------------------------------------------------------------------------
    # Preference Management
    # -------------------------------------------------------------------------

    def _load_preferences(self):
        """
        Loads user preferences from state_manager and applies them to GUI.

        This restores the last-used settings including:
        - Watch folder path
        - Privacy setting
        - Playlist selection
        - Video category
        - All automation flags
        """
        prefs = self.state_manager.get_all_preferences()

        # Apply UI preferences
        if prefs.get('last_watch_folder'):
            self.folder_path_var.set(prefs['last_watch_folder'])

        if prefs.get('privacy_setting'):
            self.privacy_var.set(prefs['privacy_setting'])
            self.upload_manager.set_privacy(prefs['privacy_setting'])

        if prefs.get('playlist_title'):
            self.playlist_var.set(prefs['playlist_title'])
            playlist_id = self.auth_manager.get_playlist_id(prefs['playlist_title'])
            self.upload_manager.set_playlist(playlist_id)

        if prefs.get('video_category'):
            self.category_var.set(prefs['video_category'])
            self.upload_manager.set_category(prefs['video_category'])

        # Apply automation preferences
        self.autonomous_mode_var.set(prefs.get('autonomous_mode', config.DEFAULT_AUTONOMOUS_MODE))
        self.auto_start_watching_var.set(prefs.get('auto_start_watching', config.DEFAULT_AUTO_START_WATCHING))
        self.start_minimized_var.set(prefs.get('start_minimized', config.DEFAULT_START_MINIMIZED))
        self.notify_when_empty_var.set(prefs.get('notify_when_empty', config.DEFAULT_NOTIFY_WHEN_EMPTY))
        self.start_with_windows_var.set(prefs.get('start_with_windows', False))

        # Apply toast notification preferences
        self.notify_upload_success_var.set(prefs.get('notify_upload_success', config.DEFAULT_NOTIFY_UPLOAD_SUCCESS))
        self.notify_upload_failed_var.set(prefs.get('notify_upload_failed', config.DEFAULT_NOTIFY_UPLOAD_FAILED))
        self.notify_quota_exceeded_var.set(prefs.get('notify_quota_exceeded', config.DEFAULT_NOTIFY_QUOTA_EXCEEDED))
        self.notify_batch_complete_var.set(prefs.get('notify_batch_complete', config.DEFAULT_NOTIFY_BATCH_COMPLETE))

        self.log("User preferences loaded successfully")

    def _save_preference(self, key, value):
        """
        Saves a single preference to persistent storage.

        Args:
            key (str): Preference key
            value: Preference value (str, bool, etc.)
        """
        try:
            self.state_manager.set_preference(key, value)
        except Exception as e:
            self.log(f"Warning: Could not save preference '{key}': {str(e)}")

    def _apply_automation_preferences(self):
        """
        Applies automation preferences after GUI is fully loaded.

        This handles:
        - Auto-starting folder watching
        - Minimizing to tray on startup
        - Autonomous mode (combines both above)
        """
        # Autonomous mode overrides individual settings
        if self.autonomous_mode_var.get():
            self.auto_start_watching_var.set(True)
            self.start_minimized_var.set(True)

        # Auto-start watching if enabled
        if self.auto_start_watching_var.get():
            # Need to wait for GUI to be fully rendered
            self.root.after(100, self._auto_start_watching)

        # Minimize to tray if enabled
        if self.start_minimized_var.get():
            self.root.after(200, self.window_manager.minimize_to_tray)

    def _auto_start_watching(self):
        """
        Helper method to auto-start watching after GUI is loaded.
        """
        if self.folder_path_var.get():
            self.log("Auto-starting folder watch (automation preference)")
            self._on_start_watching()
        else:
            self.log("Auto-start disabled: No watch folder configured")

    # -------------------------------------------------------------------------
    # Automation Preference Handlers
    # -------------------------------------------------------------------------

    def _on_autonomous_mode_changed(self):
        """
        Handler for autonomous mode checkbox.

        When enabled, automatically enables auto-start and start-minimized.
        """
        autonomous = self.autonomous_mode_var.get()
        self._save_preference('autonomous_mode', autonomous)

        if autonomous:
            # Enable dependent settings
            self.auto_start_watching_var.set(True)
            self.start_minimized_var.set(True)
            self._save_preference('auto_start_watching', True)
            self._save_preference('start_minimized', True)
            self.log("Autonomous mode enabled (auto-start + minimized startup)")
        else:
            self.log("Autonomous mode disabled")

    def _on_auto_start_watching_changed(self):
        """Handler for auto-start watching checkbox."""
        auto_start = self.auto_start_watching_var.get()
        self._save_preference('auto_start_watching', auto_start)

        if auto_start:
            self.log("Auto-start watching enabled (will start monitoring on app launch)")
        else:
            self.log("Auto-start watching disabled")
            # Disable autonomous mode if auto-start is disabled
            if self.autonomous_mode_var.get():
                self.autonomous_mode_var.set(False)
                self._save_preference('autonomous_mode', False)

    def _on_start_minimized_changed(self):
        """Handler for start minimized checkbox."""
        start_minimized = self.start_minimized_var.get()
        self._save_preference('start_minimized', start_minimized)

        if start_minimized:
            self.log("Start minimized enabled (app will start in system tray)")
        else:
            self.log("Start minimized disabled")
            # Disable autonomous mode if start minimized is disabled
            if self.autonomous_mode_var.get():
                self.autonomous_mode_var.set(False)
                self._save_preference('autonomous_mode', False)

    def _on_notify_when_empty_changed(self):
        """Handler for notify when empty checkbox."""
        notify = self.notify_when_empty_var.get()
        self._save_preference('notify_when_empty', notify)

        if notify:
            if self.notification_manager.is_available():
                self.log("Empty folder notifications enabled")
            else:
                self.log("Notifications enabled (but win11toast library not available)")
                self.dialog_manager.show_warning(
                    "Feature Unavailable",
                    "Windows notifications require the 'win11toast' package.\n\n"
                    "Install with: pip install win11toast"
                )
        else:
            self.log("Empty folder notifications disabled")

    def _on_start_with_windows_changed(self):
        """
        Handler for start with Windows checkbox.

        Creates or removes a shortcut in the Windows startup folder.
        """
        start_with_windows = self.start_with_windows_var.get()
        self._save_preference('start_with_windows', start_with_windows)

        if not self.windows_integration.is_startup_available():
            self.dialog_manager.show_error(
                "Feature Unavailable",
                "Windows startup integration requires:\n"
                "- pywin32 package\n"
                "- winshell package\n\n"
                "Install with: pip install pywin32 winshell"
            )
            self.start_with_windows_var.set(False)
            return

        try:
            if start_with_windows:
                self.windows_integration.add_to_startup()
                self.log("Added to Windows startup (will launch on boot)")
                self.dialog_manager.show_info(
                    "Startup Configured",
                    f"{config.APP_NAME} will now start automatically when Windows boots.\n\n"
                    "Note: Restart your computer for this to take effect."
                )
            else:
                self.windows_integration.remove_from_startup()
                self.log("Removed from Windows startup")
        except Exception as e:
            self.log(f"Error configuring Windows startup: {str(e)}")
            self.dialog_manager.show_error(
                "Startup Configuration Failed",
                f"Could not configure Windows startup:\n\n{str(e)}"
            )
            # Revert checkbox state
            self.start_with_windows_var.set(not start_with_windows)

    def _on_notify_upload_success_changed(self):
        """Handler for upload success notification checkbox."""
        notify = self.notify_upload_success_var.get()
        self._save_preference('notify_upload_success', notify)
        self.log(f"Upload success notifications {'enabled' if notify else 'disabled'}")

    def _on_notify_upload_failed_changed(self):
        """Handler for upload failed notification checkbox."""
        notify = self.notify_upload_failed_var.get()
        self._save_preference('notify_upload_failed', notify)
        self.log(f"Upload failed notifications {'enabled' if notify else 'disabled'}")

    def _on_notify_quota_exceeded_changed(self):
        """Handler for quota exceeded notification checkbox."""
        notify = self.notify_quota_exceeded_var.get()
        self._save_preference('notify_quota_exceeded', notify)
        self.log(f"Quota exceeded notifications {'enabled' if notify else 'disabled'}")

    def _on_notify_batch_complete_changed(self):
        """Handler for batch complete notification checkbox."""
        notify = self.notify_batch_complete_var.get()
        self._save_preference('notify_batch_complete', notify)
        self.log(f"Batch complete notifications {'enabled' if notify else 'disabled'}")

    
    # -------------------------------------------------------------------------
    # Incomplete Upload Check
    # -------------------------------------------------------------------------
    
    def _check_incomplete_uploads(self):
        """
        Checks for uploads interrupted by previous crash and resets them to pending.
        """
        incomplete_count = self.state_manager.reset_incomplete_uploads_to_pending()
        
        if incomplete_count > 0:
            self.log(f"Found {incomplete_count} incomplete upload(s) from previous session")
            self.log("These will be retried when you start watching")
    
    # -------------------------------------------------------------------------
    # Logging (Thread-Safe)
    # -------------------------------------------------------------------------
    
    def log(self, message):
        """
        Adds a timestamped message to the log window.
        
        This is thread-safe - can be called from background thread.
        
        Args:
            message (str): Message to log
        """
        timestamp = datetime.now().strftime(config.LOG_TIMESTAMP_FORMAT)
        log_line = f"{timestamp}: {message}\n"
        
        # Schedule GUI update on main thread
        self.root.after(0, self._append_to_log, log_line)
    
    def _append_to_log(self, text):
        """
        Internal method to append text to log widget (must run on main thread).
        
        Args:
            text (str): Text to append
        """
        try:
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)  # Auto-scroll to bottom
        except Exception as e:
            # If GUI is being destroyed, this might fail - ignore
            print(f"Error appending to log: {e}", file=sys.stderr)
    
    # -------------------------------------------------------------------------
    # Event Handlers - Dropdown Changes
    # -------------------------------------------------------------------------
    
    def _on_privacy_changed(self, event=None):
        """
        Handler for privacy dropdown selection change.

        Updates the upload_manager with new privacy setting and saves preference.
        """
        privacy = self.privacy_var.get()
        self.upload_manager.set_privacy(privacy)
        self._save_preference('privacy_setting', privacy)
        self.log(f"Privacy setting changed to: {privacy}")

    def _on_playlist_changed(self, event=None):
        """
        Handler for playlist dropdown selection change.

        Updates the upload_manager with new playlist selection and saves preference.
        """
        playlist_title = self.playlist_var.get()
        playlist_id = self.auth_manager.get_playlist_id(playlist_title)

        self.upload_manager.set_playlist(playlist_id)
        self._save_preference('playlist_title', playlist_title)

        if playlist_id:
            self.log(f"Playlist changed to: {playlist_title}")
        else:
            self.log("Playlist changed to: No Playlist")

    def _on_category_changed(self, event=None):
        """
        Handler for category dropdown selection change.

        Updates the upload_manager with new category selection and saves preference.
        """
        category = self.category_var.get()
        self.upload_manager.set_category(category)
        self._save_preference('video_category', category)
        self.log(f"Video category changed to: {category}")

    def _on_sort_playlist(self):
        """
        Handler for Sort Playlist button.

        Sorts the currently selected playlist alphabetically by video title.
        For date-based filenames, this sorts chronologically.
        """
        # Get currently selected playlist
        playlist_title = self.playlist_var.get()
        playlist_id = self.auth_manager.get_playlist_id(playlist_title)

        # Validate a playlist is selected
        if not playlist_id:
            self.dialog_manager.show_warning(
                "No Playlist Selected",
                "Please select a playlist to sort.\n\n"
                "(The 'No Playlist' option cannot be sorted)"
            )
            return

        # Get playlist size to estimate quota cost
        self.log(f"Checking playlist size...")
        item_count = self.upload_manager.get_playlist_item_count(playlist_id)

        if item_count == 0:
            self.dialog_manager.show_warning(
                "Empty Playlist",
                "This playlist appears to be empty or could not be accessed.\n\n"
                "Cannot sort an empty playlist."
            )
            return

        # Calculate estimated quota cost
        estimated_cost = self.upload_manager.estimate_sort_quota_cost(item_count)

        # Build confirmation message with quota warning
        confirm_message = (
            f"Sort playlist '{playlist_title}' alphabetically?\n\n"
            f"Playlist contains: {item_count:,} video(s)\n"
            f"Estimated quota cost: {estimated_cost:,} units\n"
            f"Daily quota limit: {config.DEFAULT_DAILY_QUOTA_LIMIT:,} units\n\n"
        )

        if estimated_cost > config.DEFAULT_DAILY_QUOTA_LIMIT:
            confirm_message += (
                "⚠️ WARNING: Estimated cost EXCEEDS daily quota limit!\n\n"
                f"This operation will likely run out of quota after sorting\n"
                f"approximately {config.DEFAULT_DAILY_QUOTA_LIMIT // config.QUOTA_COST_PLAYLIST_UPDATE:,} videos.\n\n"
                "You can run this operation again after 24 hours to continue\n"
                "sorting from where it left off.\n\n"
                "Continue anyway?"
            )
        else:
            confirm_message += (
                "This will reorder all videos in the playlist by title.\n"
                "For date-based filenames, this sorts chronologically.\n\n"
                "Continue?"
            )

        # Confirm with user
        confirm = self.dialog_manager.ask_yes_no(
            "Confirm Playlist Sort",
            confirm_message
        )

        if not confirm:
            self.log("Playlist sort cancelled by user")
            return

        # Disable button during sort
        self.sort_playlist_button.config(state=tk.DISABLED)
        self.log(f"Starting sort for playlist: {playlist_title}")

        # Run sort in background thread to avoid freezing GUI
        def sort_thread():
            try:
                # Progress callback to update GUI
                def progress(current, total, message):
                    self.status_var.set(f"Sorting: {current}/{total}")
                    if total > 0:
                        percent = (current / total) * 100
                        self.progress_var.set(percent)
                    self.log(message)

                # Perform the sort
                success, message, count = self.upload_manager.sort_playlist_alphabetically(
                    playlist_id,
                    progress_callback=progress
                )

                # Reset progress
                self.progress_var.set(0)

                # Re-enable button
                self.sort_playlist_button.config(state=tk.NORMAL)

                # Show result to user
                if success:
                    self.status_var.set("Playlist sorted successfully")
                    self.dialog_manager.show_info(
                        "Sort Complete",
                        f"{message}\n\n"
                        f"Playlist '{playlist_title}' has been sorted alphabetically."
                    )
                else:
                    self.status_var.set("Playlist sort failed")
                    self.dialog_manager.show_error(
                        "Sort Failed",
                        f"Failed to sort playlist:\n\n{message}"
                    )

            except Exception as e:
                self.log(f"Error during playlist sort: {str(e)}")
                self.sort_playlist_button.config(state=tk.NORMAL)
                self.status_var.set("Sort error")
                self.dialog_manager.show_error(
                    "Sort Error",
                    f"An error occurred during sorting:\n\n{str(e)}"
                )

        # Start the sort thread
        thread = threading.Thread(target=sort_thread, daemon=True)
        thread.start()
    
    # -------------------------------------------------------------------------
    # Event Handlers - Folder Selection
    # -------------------------------------------------------------------------
    
    def _on_browse_folder(self):
        """
        Handler for Browse button - opens folder selection dialog and saves preference.
        """
        folder = self.dialog_manager.ask_directory(title="Select Watch Folder")

        if folder:
            self.folder_path_var.set(folder)
            self._save_preference('last_watch_folder', folder)
            self.log(f"Watch folder selected: {folder}")

    def _on_upload_single_file(self):
        """
        Handler for Upload File button - allows uploading a single video without watching folder.

        This is useful for one-off uploads without setting up folder monitoring.
        """
        # Open file dialog to select video file
        filepath = self.dialog_manager.ask_video_file(title="Select Video to Upload")

        if not filepath:
            # User cancelled
            return

        self.log(f"Single file upload selected: {os.path.basename(filepath)}")

        # Disable upload button during upload
        self.upload_file_button.config(state=tk.DISABLED)

        # Run upload in background thread to avoid freezing GUI
        def upload_thread():
            try:
                # Update status
                self.status_var.set(f"Uploading: {os.path.basename(filepath)}")

                # Perform upload
                success, message, video_id = self.upload_manager.upload_video(filepath)

                # Reset progress
                self.progress_var.set(0)

                # Re-enable button
                self.upload_file_button.config(state=tk.NORMAL)

                # Show result to user
                if success:
                    self.status_var.set("Upload complete")
                    self.log(message)

                    # Notify upload success if enabled
                    if self.notify_upload_success_var.get():
                        self.notification_manager.show_notification(
                            "Upload Succeeded",
                            f"Successfully uploaded: {os.path.basename(filepath)}",
                            duration=3
                        )

                    self.dialog_manager.show_info(
                        "Upload Successful",
                        f"Video uploaded successfully!\n\n"
                        f"File: {os.path.basename(filepath)}\n"
                        f"Video ID: {video_id}"
                    )
                else:
                    self.status_var.set("Upload failed")
                    self.log(f"Upload failed: {message}")

                    # Notify upload failed if enabled
                    if self.notify_upload_failed_var.get():
                        self.notification_manager.show_notification(
                            "Upload Failed",
                            f"Failed to upload {os.path.basename(filepath)}: {message}",
                            duration=5
                        )

                    self.dialog_manager.show_error(
                        "Upload Failed",
                        f"Failed to upload video:\n\n{message}"
                    )

            except Exception as e:
                self.log(f"Error during single file upload: {str(e)}")
                self.upload_file_button.config(state=tk.NORMAL)
                self.status_var.set("Upload error")

                # Check if it was a quota error
                if "QuotaExceededError" in str(type(e)) or "quotaExceeded" in str(e):
                    # Notify quota exceeded if enabled
                    if self.notify_quota_exceeded_var.get():
                        self.notification_manager.show_notification(
                            "Quota Exceeded",
                            "YouTube API quota exceeded. Try again in 24 hours.",
                            duration=8
                        )
                else:
                    # Notify upload failed if enabled
                    if self.notify_upload_failed_var.get():
                        self.notification_manager.show_notification(
                            "Upload Error",
                            f"Error uploading {os.path.basename(filepath)}: {str(e)}",
                            duration=5
                        )

                self.dialog_manager.show_error(
                    "Upload Error",
                    f"An error occurred during upload:\n\n{str(e)}"
                )

        # Start the upload thread
        thread = threading.Thread(target=upload_thread, daemon=True)
        thread.start()
    
    # -------------------------------------------------------------------------
    # Event Handlers - Control Buttons
    # -------------------------------------------------------------------------
    
    def _on_start_watching(self):
        """
        Handler for Start Watching button.

        Starts the background worker thread that monitors the watch folder.
        """
        # Validate folder is selected
        if not self.folder_path_var.get():
            self.dialog_manager.show_error("Error", config.ERROR_NO_WATCH_FOLDER)
            return

        self.watch_folder = self.folder_path_var.get()

        # Update button states
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.force_check_button.config(state=tk.NORMAL)

        # Reset control flag
        self.should_stop = False

        # Start background worker thread
        self.worker_thread = threading.Thread(
            target=self._watch_folder_worker,
            daemon=True
        )
        self.worker_thread.start()

        self.log("Started watching folder for new videos")
        self.status_var.set("Watching folder...")

    def _on_stop_watching(self):
        """
        Handler for Stop button.

        Signals the worker thread to stop and resets button states.
        """
        self.should_stop = True

        # Reset button states
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.force_check_button.config(state=tk.DISABLED)

        self.log("Stopped watching folder")
        self.status_var.set("Stopped")

    def _on_exit_button(self):
        """
        Handler for Exit button - cleanly exits the application.
        """
        # Ask for confirmation if currently uploading
        if hasattr(self, 'worker_thread') and self.worker_thread.is_alive():
            confirm = self.dialog_manager.ask_yes_no(
                "Confirm Exit",
                "Folder watching is active.\n\n"
                "Are you sure you want to exit?\n"
                "(Current upload will complete before exit)"
            )
            if not confirm:
                return

        self.log("Exiting application...")
        self._quit_application()
    
    def _on_force_check(self):
        """
        Handler for Force Check Now button.
        
        Immediately checks the watch folder for new videos in a background thread.
        """
        self.log("Force check triggered by user")
        
        # Run in background thread to avoid freezing GUI
        check_thread = threading.Thread(
            target=self._perform_folder_check,
            daemon=True
        )
        check_thread.start()
    
    # -------------------------------------------------------------------------
    # Background Worker Thread
    # -------------------------------------------------------------------------
    
    def _watch_folder_worker(self):
        """
        Background worker thread that monitors the watch folder.

        This runs continuously until stopped, checking for:
        - New videos in watch folder
        - Quota cooldown status
        - Stop signals from user
        """
        while not self.should_stop:
            # Check if we're in quota cooldown
            if self.upload_manager.is_in_cooldown():
                cooldown_end = self.upload_manager.get_cooldown_end_time()

                if cooldown_end:
                    # Update next check display with full date and time
                    # Show date if cooldown ends on a different day
                    now = datetime.now()
                    if cooldown_end.date() != now.date():
                        # Different day - show date and time
                        next_check_str = cooldown_end.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        # Same day - just show time
                        next_check_str = cooldown_end.strftime('%H:%M:%S')

                    self.next_check_var.set(f"Next check: {next_check_str}")
                    self.log(f"In 24-hour cooldown. Next check at {next_check_str}")

                    # Sleep until cooldown ends (in small increments to allow stop signal)
                    seconds_until_end = (cooldown_end - datetime.now()).total_seconds()
                    self._sleep_interruptible(seconds_until_end)

                    continue

            # Perform folder check and upload cycle
            self._perform_folder_check()

            # Wait before next check
            self.next_check_var.set("Next check: Waiting for user action...")
            self._sleep_interruptible(config.WATCH_FOLDER_POLL_INTERVAL)
    
    def _perform_folder_check(self):
        """
        Checks the watch folder for new videos and uploads them.

        This is the core upload cycle called by the worker thread.
        Sends notifications based on user preferences.
        """
        try:
            # Get video files from watch folder
            video_files = self.file_handler.get_video_files(self.watch_folder)

            if not video_files:
                self.log("No new videos found in watch folder")

                # Send notification if enabled
                if self.notify_when_empty_var.get():
                    self.notification_manager.show_notification(
                        "YouTube Uploader",
                        "Watch folder is empty - all videos uploaded!",
                        duration=3
                    )

                return

            self.log(f"Found {len(video_files)} video(s) to upload")

            # Check for stop signal before starting uploads
            if self.should_stop:
                self.log("Stop requested - cancelling upload batch")
                return

            # Track batch statistics
            batch_success_count = 0
            batch_fail_count = 0
            batch_size = len(video_files)

            # Upload each file
            for i, filename in enumerate(video_files):
                # Check for stop signal before each upload
                if self.should_stop:
                    self.log(f"Stop requested - stopped after {batch_success_count} of {batch_size} video(s)")
                    break

                # Upload this file
                filepath = os.path.join(self.watch_folder, filename)

                try:
                    # Update progress
                    percent = (i / len(video_files)) * 100
                    self.progress_var.set(percent)
                    self.status_var.set(f"Uploading {i+1} of {len(video_files)}: {filename}")

                    # Log start of upload (helps user see what's being uploaded)
                    self.log(f"Starting upload {i+1}/{len(video_files)}: {filename}")

                    # Perform upload (this is a long-running operation that cannot be interrupted)
                    success, message, video_id = self.upload_manager.upload_video(filepath)

                    if success:
                        self.log(message)
                        batch_success_count += 1

                        # Notify upload success if enabled
                        if self.notify_upload_success_var.get():
                            self.notification_manager.show_notification(
                                "Upload Succeeded",
                                f"Successfully uploaded: {filename}",
                                duration=3
                            )
                    else:
                        self.log(f"Skipped: {message}")
                        batch_fail_count += 1

                        # Notify upload failed if enabled (and not a duplicate/already uploaded)
                        if self.notify_upload_failed_var.get() and "already uploaded" not in message.lower():
                            self.notification_manager.show_notification(
                                "Upload Failed",
                                f"Failed to upload {filename}: {message}",
                                duration=5
                            )

                except Exception as e:
                    self.log(f"Error uploading {filename}: {str(e)}")
                    batch_fail_count += 1

                    # Check if it was a quota error
                    if "QuotaExceededError" in str(type(e)) or "quotaExceeded" in str(e):
                        self.log("Quota exceeded, stopping upload cycle")

                        # Notify quota exceeded if enabled
                        if self.notify_quota_exceeded_var.get():
                            self.notification_manager.show_notification(
                                "Quota Exceeded",
                                "YouTube API quota exceeded. Uploads will resume in 24 hours.",
                                duration=8
                            )
                        break
                    else:
                        # Notify upload failed if enabled
                        if self.notify_upload_failed_var.get():
                            self.notification_manager.show_notification(
                                "Upload Error",
                                f"Error uploading {filename}: {str(e)}",
                                duration=5
                            )

            # Reset progress
            self.progress_var.set(0)
            self.status_var.set("Upload cycle complete")

            # Notify batch complete if enabled and we uploaded something
            if self.notify_batch_complete_var.get() and batch_success_count > 0:
                summary = f"Uploaded {batch_success_count} of {batch_size} video(s)"
                if batch_fail_count > 0:
                    summary += f" ({batch_fail_count} failed)"

                self.notification_manager.show_notification(
                    "Batch Complete",
                    summary,
                    duration=5
                )

        except Exception as e:
            self.log(f"Error in folder check: {str(e)}")
    
    def _sleep_interruptible(self, seconds):
        """
        Sleeps for the specified duration, but checks for stop signal periodically.
        
        This allows the worker thread to respond quickly to stop requests
        even during long waits.
        
        Args:
            seconds (float): Total seconds to sleep
        """
        end_time = time.time() + seconds
        
        while time.time() < end_time:
            if self.should_stop:
                break
            
            # Sleep in small increments
            time.sleep(config.SLEEP_INCREMENT_SECONDS)
    
    # -------------------------------------------------------------------------
    # Window Management
    # -------------------------------------------------------------------------

    def _on_show_window(self, icon=None):
        """
        Restores window from system tray.

        Args:
            icon: System tray icon (unused, required by pystray callback signature)
        """
        self.window_manager.restore_from_tray()
    
    def _quit_application(self):
        """
        Internal method to cleanly exit the application.

        Can be called from any thread - uses root.after() to ensure
        GUI operations happen on main thread.
        """
        def do_quit():
            try:
                # Signal worker thread to stop
                self.should_stop = True

                # Hide and stop tray icon
                self.system_tray_manager.stop()

                # Give worker thread brief moment to stop
                time.sleep(0.3)

                # Destroy GUI (must be on main thread)
                self.root.quit()
                self.root.destroy()

                # Force process exit (ensures clean termination)
                sys.exit(0)

            except Exception as e:
                print(f"Error during quit: {str(e)}", file=sys.stderr)
                # Force exit if clean exit fails
                sys.exit(1)

        # If called from main thread, execute directly
        # Otherwise, schedule on main thread
        try:
            self.root.after(0, do_quit)
        except:
            # If root is already destroyed or unavailable, force exit
            sys.exit(0)

    def _on_quit_app(self, icon=None):
        """
        Handler for tray icon "Exit" menu item.

        Args:
            icon: System tray icon (unused, required by pystray callback signature)
        """
        self._quit_application()
    
    # -------------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------------
    
    def run(self):
        """
        Starts the GUI main loop.
        
        This blocks until the window is closed.
        """
        try:
            self.root.mainloop()
        except Exception as e:
            self.log(f"Error in main loop: {str(e)}")
            raise
