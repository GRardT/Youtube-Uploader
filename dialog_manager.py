# =============================================================================
# dialog_manager.py - Dialog Manager for YouTube Uploader
# =============================================================================
# Purpose: Centralized dialog management for file selection and user prompts.
#
# Key Features:
# - File and folder selection dialogs
# - Standard message boxes (info, warning, error, confirmation)
# - Consistent dialog styling and behavior
# =============================================================================

from tkinter import filedialog, messagebox
import config


class DialogManager:
    """
    Manages all file dialogs and message boxes.

    This class provides a centralized interface for showing dialogs,
    making it easier to test and maintain consistent dialog behavior.
    """

    @staticmethod
    def ask_directory(title="Select Folder"):
        """
        Opens a folder selection dialog.

        Args:
            title (str): Dialog window title

        Returns:
            str: Selected folder path, or empty string if cancelled
        """
        folder = filedialog.askdirectory(title=title)
        return folder if folder else ""

    @staticmethod
    def ask_open_filename(title="Select File", filetypes=None):
        """
        Opens a file selection dialog.

        Args:
            title (str): Dialog window title
            filetypes (list): List of (description, pattern) tuples for file filtering
                Example: [("Video files", "*.mp4 *.avi"), ("All files", "*.*")]

        Returns:
            str: Selected file path, or empty string if cancelled
        """
        if filetypes is None:
            filetypes = [("All files", "*.*")]

        filepath = filedialog.askopenfilename(title=title, filetypes=filetypes)
        return filepath if filepath else ""

    @staticmethod
    def ask_video_file(title="Select Video to Upload"):
        """
        Opens a video file selection dialog with appropriate filters.

        Args:
            title (str): Dialog window title

        Returns:
            str: Selected video file path, or empty string if cancelled
        """
        filetypes = [
            ("Video files", " ".join(f"*{ext}" for ext in config.SUPPORTED_VIDEO_EXTENSIONS)),
            ("All files", "*.*")
        ]
        return DialogManager.ask_open_filename(title=title, filetypes=filetypes)

    @staticmethod
    def show_info(title, message):
        """
        Shows an informational message box.

        Args:
            title (str): Dialog title
            message (str): Message to display
        """
        messagebox.showinfo(title, message)

    @staticmethod
    def show_warning(title, message):
        """
        Shows a warning message box.

        Args:
            title (str): Dialog title
            message (str): Warning message to display
        """
        messagebox.showwarning(title, message)

    @staticmethod
    def show_error(title, message):
        """
        Shows an error message box.

        Args:
            title (str): Dialog title
            message (str): Error message to display
        """
        messagebox.showerror(title, message)

    @staticmethod
    def ask_yes_no(title, message):
        """
        Shows a yes/no confirmation dialog.

        Args:
            title (str): Dialog title
            message (str): Question to ask

        Returns:
            bool: True if user clicked Yes, False if No
        """
        return messagebox.askyesno(title, message)
