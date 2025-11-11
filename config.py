# =============================================================================
# config.py - YouTube Uploader v2.0 Configuration
# =============================================================================
# Purpose: Centralized configuration constants for the entire application.
#          No business logic here - just constants that might need to change.
#
# Security: No sensitive data stored here. All credentials are in separate
#           files (client_secrets.json, token.pickle) that are gitignored.
# =============================================================================

import os
from pathlib import Path

# -----------------------------------------------------------------------------
# Application Metadata
# -----------------------------------------------------------------------------
APP_NAME = "YouTube Uploader"
APP_VERSION = "2.0.1"
APP_AUTHOR = "GRard"

# -----------------------------------------------------------------------------
# File Paths - All JSON state files and credentials
# -----------------------------------------------------------------------------
# These files are created/managed by the application at runtime

# OAuth credentials from Google Cloud Console (user must provide this)
CLIENT_SECRETS_FILE = 'client_secrets.json'

# Generated after first OAuth authorization (stores refresh token)
TOKEN_FILE = 'token.pickle'

# Tracks MD5 hashes of uploaded files to prevent re-uploads
# Format: { "md5_hash": { "filename": "video.mp4", "upload_date": "...", "video_id": "..." } }
UPLOAD_HISTORY_FILE = 'upload_history.json'

# Tracks current state of files (pending/uploading/completed/failed)
# Used for crash recovery - if app crashes during upload, we can resume
# Format: { "filepath": { "state": "uploading", "timestamp": "..." } }
UPLOAD_STATE_FILE = 'upload_state.json'

# Tracks when quota was last exceeded to enforce 24-hour cooldown
# Format: { "last_quota_hit": "2025-10-22T14:30:00" }
QUOTA_STATE_FILE = 'quota_state.json'

# Tracks playlist sort progress for resume capability
# Format: { "playlist_id": "PLxxx", "sorted_items": [...], "last_position": 42 }
PLAYLIST_SORT_STATE_FILE = 'playlist_sort_state.json'

# Stores user preferences (watch folder, privacy, playlist, automation settings)
# Format: { "last_watch_folder": "C:/Videos", "privacy": "unlisted", ... }
USER_PREFERENCES_FILE = 'user_preferences.json'

# -----------------------------------------------------------------------------
# YouTube API Configuration
# -----------------------------------------------------------------------------
# These scopes determine what the app can do with your YouTube account
# - youtube.upload: Allows uploading videos
# - youtube: Allows reading playlists and adding videos to them
YOUTUBE_API_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube'
]

# YouTube API version (should not change unless Google releases new version)
YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'

# Maximum number of playlists to fetch from YouTube API
# Note: This is a known limitation - we only fetch first 50 playlists
# TODO: Implement pagination to fetch all playlists
MAX_PLAYLISTS_TO_FETCH = 50

# YouTube video categories
# See: https://developers.google.com/youtube/v3/docs/videoCategories/list
# These are the most commonly used categories
VIDEO_CATEGORIES = {
    'Film & Animation': '1',
    'Autos & Vehicles': '2',
    'Music': '10',
    'Pets & Animals': '15',
    'Sports': '17',
    'Travel & Events': '19',
    'Gaming': '20',
    'People & Blogs': '22',
    'Comedy': '23',
    'Entertainment': '24',
    'News & Politics': '25',
    'Howto & Style': '26',
    'Education': '27',
    'Science & Technology': '28',
    'Nonprofits & Activism': '29'
}

# Default video category for uploads
# 22 = "People & Blogs" category (safe default)
DEFAULT_VIDEO_CATEGORY = 'People & Blogs'

# -----------------------------------------------------------------------------
# Quota Management
# -----------------------------------------------------------------------------
# YouTube enforces a daily upload quota (typically ~10 videos per 24 hours)
# Once quota is hit, we must wait 24 hours before trying again

# Buffer time added to 24-hour cooldown (in minutes)
# This ensures we don't retry too early and waste API calls
QUOTA_COOLDOWN_BUFFER_MINUTES = 5

# Total cooldown period in hours (24 hours is YouTube's standard reset period)
QUOTA_COOLDOWN_HOURS = 24

# YouTube API quota costs (in units)
# See: https://developers.google.com/youtube/v3/determine_quota_cost
QUOTA_COST_PLAYLIST_LIST = 1         # Fetching playlist items (per page of 50)
QUOTA_COST_PLAYLIST_UPDATE = 50      # Updating a single playlist item position
QUOTA_COST_VIDEO_UPLOAD = 1600       # Uploading a video
QUOTA_COST_PLAYLIST_INSERT = 50      # Adding a video to a playlist

# Default daily quota limit for YouTube API
# Most accounts get 10,000 units per day
DEFAULT_DAILY_QUOTA_LIMIT = 10000

# -----------------------------------------------------------------------------
# Upload Retry Configuration
# -----------------------------------------------------------------------------
# Maximum number of retry attempts for failed uploads
MAX_UPLOAD_RETRY_ATTEMPTS = 3

# Initial retry delay in seconds (will be doubled with each retry)
INITIAL_RETRY_DELAY_SECONDS = 60  # 1 minute

# Maximum retry delay in seconds (cap for exponential backoff)
MAX_RETRY_DELAY_SECONDS = 3600  # 1 hour

# -----------------------------------------------------------------------------
# File Operation Retry Configuration
# -----------------------------------------------------------------------------
# Maximum number of retry attempts for file operations (move, delete)
MAX_FILE_OPERATION_RETRIES = 5

# Initial delay before file operations in seconds
INITIAL_FILE_OPERATION_DELAY = 0.5  # 500ms

# Maximum delay for file operation retries
MAX_FILE_OPERATION_DELAY = 10  # 10 seconds

# -----------------------------------------------------------------------------
# Automation Settings
# -----------------------------------------------------------------------------
# Enable autonomous mode by default
DEFAULT_AUTONOMOUS_MODE = False

# Auto-start watching when app launches
DEFAULT_AUTO_START_WATCHING = False

# Start minimized to system tray
DEFAULT_START_MINIMIZED = False

# Show notification when watch folder is empty
DEFAULT_NOTIFY_WHEN_EMPTY = True

# Auto-close app after folder is empty (requires notify_when_empty)
DEFAULT_AUTO_CLOSE_WHEN_EMPTY = False

# Windows startup shortcut name
WINDOWS_STARTUP_SHORTCUT_NAME = 'YouTube Uploader.lnk'

# -----------------------------------------------------------------------------
# Toast Notification Settings
# -----------------------------------------------------------------------------
# Control which types of events trigger Windows toast notifications

# Notify when a video upload succeeds
DEFAULT_NOTIFY_UPLOAD_SUCCESS = False

# Notify when a video upload fails
DEFAULT_NOTIFY_UPLOAD_FAILED = True

# Notify when quota is exceeded
DEFAULT_NOTIFY_QUOTA_EXCEEDED = True

# Notify when batch upload completes (multiple videos)
DEFAULT_NOTIFY_BATCH_COMPLETE = False

# -----------------------------------------------------------------------------
# Application Icon
# -----------------------------------------------------------------------------
# Path to application icon file (PNG or ICO)
# Icon is used for window, tray, and future .exe packaging
ICON_PATH = os.path.join('assets', 'icon.png')

# Fallback tray icon color if icon file not found
FALLBACK_TRAY_ICON_COLOR = 'red'

# -----------------------------------------------------------------------------
# File Handling
# -----------------------------------------------------------------------------
# Supported video file extensions (lowercase)
# YouTube accepts these formats: .mp4, .mov, .avi, .wmv, .flv, .3gp, .webm, .mkv
# We're conservative and only auto-detect the most common formats
SUPPORTED_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi')

# Subfolder name where uploaded files are moved after successful upload
# This folder is created inside the watch folder
UPLOADED_FOLDER_NAME = 'Uploaded'

# MD5 hash chunk size (in bytes)
# We read files in 64KB chunks for efficient memory usage
# This is the same size used in the original implementation
MD5_CHUNK_SIZE = 65536  # 64KB

# Maximum file size for YouTube uploads (in bytes)
# YouTube's limit is 256GB for most accounts (128GB for unverified)
# We use 256GB as the limit here
MAX_FILE_SIZE_BYTES = 256 * 1024 * 1024 * 1024  # 256GB in bytes

# Chunk size for resumable uploads (in bytes)
# For large files, we upload in chunks to handle network interruptions
# 10MB chunks provide good balance between reliability and performance
UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB

# -----------------------------------------------------------------------------
# Internet Connectivity
# -----------------------------------------------------------------------------
# Maximum time to wait for internet connection before giving up (in seconds)
MAX_INTERNET_WAIT_SECONDS = 300  # 5 minutes

# Interval between connectivity checks (in seconds)
INTERNET_CHECK_INTERVAL_SECONDS = 10

# URLs to check for internet connectivity
# We use multiple reliable endpoints to ensure we're not blocked by one service
# These are chosen because they're fast, reliable, and geographically distributed
CONNECTIVITY_CHECK_URLS = [
    "https://1.1.1.1",           # Cloudflare DNS (very fast)
    "https://8.8.8.8",           # Google DNS (very fast)
    "https://api.github.com",    # GitHub API (reliable)
    "https://cloudflare.com",    # Cloudflare main site
    "https://amazon.com"         # Amazon (almost always up)
]

# Timeout for each connectivity check request (in seconds)
CONNECTIVITY_CHECK_TIMEOUT = 5

# -----------------------------------------------------------------------------
# GUI Configuration
# -----------------------------------------------------------------------------
# Main window dimensions
GUI_WINDOW_WIDTH = 800
GUI_WINDOW_HEIGHT = 600

# Log text widget height (in lines)
GUI_LOG_HEIGHT = 10

# System tray icon size (in pixels)
TRAY_ICON_SIZE = 64

# Timestamp format for log messages
# Example: "14:30:45: Upload started"
LOG_TIMESTAMP_FORMAT = '%H:%M:%S'

# Full timestamp format for state files
# Example: "2025-10-22T14:30:45"
STATE_TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S'

# -----------------------------------------------------------------------------
# Threading and Timing
# -----------------------------------------------------------------------------
# Sleep increment for interruptible waits (in seconds)
# This allows us to check for stop signals frequently during long waits
SLEEP_INCREMENT_SECONDS = 5

# Polling interval for watch folder checks (in seconds)
# After completing an upload cycle, we wait this long before checking again
WATCH_FOLDER_POLL_INTERVAL = 30

# Maximum time to wait for current upload to complete before forcing exit (seconds)
CLEANUP_TIMEOUT_SECONDS = 5

# -----------------------------------------------------------------------------
# Privacy Settings
# -----------------------------------------------------------------------------
# Valid YouTube privacy status values
# These are the only values accepted by YouTube API
PRIVACY_SETTINGS = ['private', 'unlisted', 'public']

# Default privacy setting for new uploads
DEFAULT_PRIVACY_SETTING = 'private'

# -----------------------------------------------------------------------------
# Error Messages
# -----------------------------------------------------------------------------
# User-friendly error messages (displayed in messageboxes)
ERROR_NO_CLIENT_SECRETS = (
    "client_secrets.json not found!\n\n"
    "Please download your OAuth credentials from Google Cloud Console "
    "and place them in the same directory as this script."
)

ERROR_NO_WATCH_FOLDER = "Please select a watch folder before starting."

ERROR_YOUTUBE_CLIENT_INIT = "Failed to initialize YouTube client. Check logs for details."

ERROR_AUTHENTICATION_FAILED = "Authentication failed. Please check your credentials."

# -----------------------------------------------------------------------------
# Success Messages
# -----------------------------------------------------------------------------
SUCCESS_AUTH = "YouTube client initialized successfully"
SUCCESS_UPLOAD = "Successfully uploaded {filename} (Total uploads this session: {count})"
SUCCESS_PLAYLIST_ADD = "Successfully added video {video_id} to playlist {playlist_id}"

# -----------------------------------------------------------------------------
# Info Messages
# -----------------------------------------------------------------------------
INFO_NO_VIDEOS_FOUND = "No new videos found in the watch folder."
INFO_ALREADY_UPLOADED = "File already uploaded: {filename}"
INFO_QUOTA_EXCEEDED = "Quota or upload limit exceeded. Recording last quota hit and stopping uploads."
INFO_IN_COOLDOWN = "In a 24-hour cooldown. Will re-check at {cooldown_end}."
INFO_COOLDOWN_EXPIRED = "Cooldown appears to have expired, proceeding with normal check."

# -----------------------------------------------------------------------------
# Validation Functions
# -----------------------------------------------------------------------------

def validate_config():
    """
    Validates that all required configuration values are properly set.
    
    This function is called at application startup to catch configuration
    errors early before they cause problems during runtime.
    
    Raises:
        ValueError: If any configuration value is invalid
        FileNotFoundError: If required files are missing
    """
    # Validate that client_secrets.json exists
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError(ERROR_NO_CLIENT_SECRETS)
    
    # Validate MD5 chunk size is positive
    if MD5_CHUNK_SIZE <= 0:
        raise ValueError("MD5_CHUNK_SIZE must be positive")
    
    # Validate quota cooldown values
    if QUOTA_COOLDOWN_HOURS <= 0:
        raise ValueError("QUOTA_COOLDOWN_HOURS must be positive")
    if QUOTA_COOLDOWN_BUFFER_MINUTES < 0:
        raise ValueError("QUOTA_COOLDOWN_BUFFER_MINUTES cannot be negative")
    
    # Validate privacy settings
    if DEFAULT_PRIVACY_SETTING not in PRIVACY_SETTINGS:
        raise ValueError(f"DEFAULT_PRIVACY_SETTING must be one of {PRIVACY_SETTINGS}")
    
    # Validate video extensions are lowercase and start with dot
    for ext in SUPPORTED_VIDEO_EXTENSIONS:
        if not ext.startswith('.'):
            raise ValueError(f"Video extension '{ext}' must start with a dot")
        if ext != ext.lower():
            raise ValueError(f"Video extension '{ext}' must be lowercase")
    
    return True


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_uploaded_folder_path(watch_folder):
    """
    Returns the full path to the 'Uploaded' subfolder within the watch folder.
    
    Args:
        watch_folder (str): Path to the watch folder
        
    Returns:
        str: Full path to the Uploaded subfolder
        
    Example:
        >>> get_uploaded_folder_path("C:/Videos")
        "C:/Videos/Uploaded"
    """
    return os.path.join(watch_folder, UPLOADED_FOLDER_NAME)


def is_supported_video_file(filename):
    """
    Checks if a filename has a supported video extension.

    Args:
        filename (str): Name of the file to check

    Returns:
        bool: True if file has a supported video extension, False otherwise

    Example:
        >>> is_supported_video_file("video.mp4")
        True
        >>> is_supported_video_file("document.pdf")
        False
    """
    return filename.lower().endswith(SUPPORTED_VIDEO_EXTENSIONS)


def format_file_size(size_bytes):
    """
    Formats a file size in bytes to a human-readable string.

    Args:
        size_bytes (int): File size in bytes

    Returns:
        str: Formatted file size (e.g., "1.5 GB", "500 MB")

    Example:
        >>> format_file_size(1536)
        "1.50 KB"
        >>> format_file_size(1073741824)
        "1.00 GB"
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
