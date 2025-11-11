# =============================================================================
# state_manager.py - YouTube Uploader v2.0 State Persistence Module
# =============================================================================
# Purpose: Manages all JSON state files with atomic writes and validation.
#
# State Files Managed:
# 1. upload_history.json - MD5 hashes of uploaded files (prevents re-uploads)
# 2. upload_state.json - Current state of files being processed (crash recovery)
# 3. quota_state.json - Timestamp of last quota hit (24-hour cooldown)
#
# Key Features:
# - Atomic writes (write to temp file, then rename)
# - JSON schema validation
# - Backward compatible with existing state files
# - Thread-safe operations with file locking
#
# Data Integrity:
# All writes use atomic operations to prevent corruption if the app crashes.
# =============================================================================

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional
import tempfile
import shutil
import config


class StateManagerError(Exception):
    """
    Custom exception for state management errors.
    
    This allows calling code to distinguish between state management errors
    and other types of errors (network, API, etc.)
    """
    pass


class StateManager:
    """
    Manages all persistent state for the YouTube Uploader.
    
    This class handles reading/writing JSON state files with guarantees:
    - Atomic writes (no partial writes)
    - Validation before loading
    - Automatic backup of corrupted files
    - Thread-safe operations
    
    Attributes:
        upload_history (dict): MD5 hash -> video metadata
        upload_states (dict): filepath -> upload state (pending/uploading/etc)
        quota_state (dict): Contains 'last_quota_hit' timestamp
    """
    
    def __init__(self, logger=None):
        """
        Initialize the StateManager.
        
        Args:
            logger (callable, optional): Function to call for logging messages.
                                        If None, no logging is performed.
        """
        self.logger = logger
        
        # In-memory state (loaded from files)
        self.upload_history = {}  # { md5_hash: { filename, upload_date, video_id } }
        self.upload_states = {}   # { filepath: { state, timestamp } }
        self.quota_state = {}     # { last_quota_hit: ISO timestamp }
        self.playlist_sort_state = {}  # { playlist_id, sorted_items, last_position }

        # Load existing state from disk
        self._load_all_state()
    
    def _log(self, message):
        """
        Internal logging helper.
        
        Args:
            message (str): Message to log
        """
        if self.logger:
            self.logger(message)
    
    # -------------------------------------------------------------------------
    # Atomic File Operations (Prevents Corruption)
    # -------------------------------------------------------------------------
    
    def _atomic_write_json(self, filepath, data):
        """
        Atomically writes JSON data to a file.
        
        This prevents corruption if the app crashes during write:
        1. Write to a temporary file
        2. Flush to disk
        3. Rename temp file to target (atomic operation on most filesystems)
        
        If the app crashes before step 3, the original file is unchanged.
        
        Args:
            filepath (str): Target file path
            data (dict): Data to write as JSON
            
        Raises:
            StateManagerError: If write fails
            
        Example:
            >>> sm = StateManager()
            >>> sm._atomic_write_json("state.json", {"key": "value"})
        """
        try:
            # Get directory of target file
            directory = os.path.dirname(filepath) or '.'
            
            # Create temporary file in same directory as target
            # (ensures same filesystem, making rename atomic)
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=directory,
                delete=False,
                suffix='.tmp'
            ) as tmp_file:
                # Write JSON with nice formatting for human readability
                json.dump(data, tmp_file, indent=2)
                temp_path = tmp_file.name
                
                # Force write to disk (don't rely on OS buffering)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            
            # Atomic rename (this is the critical operation)
            # On Windows, we need to handle the case where target exists
            if os.path.exists(filepath):
                # On Windows, os.replace() is atomic and handles existing files
                os.replace(temp_path, filepath)
            else:
                os.rename(temp_path, filepath)
            
            self._log(f"Atomically wrote {os.path.basename(filepath)}")
            
        except Exception as e:
            # Clean up temp file if something went wrong
            try:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass
            
            error_msg = f"Failed to write {filepath}: {str(e)}"
            self._log(error_msg)
            raise StateManagerError(error_msg)
    
    def _load_json_with_validation(self, filepath, schema_validator=None):
        """
        Loads JSON from a file with optional schema validation.
        
        If the file is corrupted or invalid, creates a backup and returns
        an empty dict instead of crashing.
        
        Args:
            filepath (str): Path to JSON file
            schema_validator (callable, optional): Function that validates the
                                                  loaded data structure
        
        Returns:
            dict: Loaded data, or empty dict if file doesn't exist or is invalid
            
        Example:
            >>> sm = StateManager()
            >>> data = sm._load_json_with_validation("state.json")
        """
        # If file doesn't exist, return empty dict (normal for first run)
        if not os.path.exists(filepath):
            self._log(f"{os.path.basename(filepath)} does not exist (first run?)")
            return {}
        
        try:
            # Load JSON from file
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Validate schema if validator provided
            if schema_validator:
                if not schema_validator(data):
                    raise ValueError("Schema validation failed")
            
            self._log(f"Successfully loaded {os.path.basename(filepath)}")
            return data
            
        except json.JSONDecodeError as e:
            # JSON is malformed - create backup and start fresh
            backup_path = f"{filepath}.corrupt.{int(time.time())}"
            self._log(f"WARNING: {filepath} is corrupted (JSON decode error)")
            self._log(f"Creating backup: {backup_path}")
            
            try:
                shutil.copy2(filepath, backup_path)
            except Exception as backup_error:
                self._log(f"Could not create backup: {backup_error}")
            
            return {}
            
        except Exception as e:
            self._log(f"Error loading {filepath}: {str(e)}")
            return {}
    
    # -------------------------------------------------------------------------
    # Schema Validators (Data Integrity Checks)
    # -------------------------------------------------------------------------
    
    def _validate_upload_history_schema(self, data):
        """
        Validates the structure of upload_history.json.
        
        Expected schema:
        {
            "md5_hash_string": {
                "filename": "video.mp4",
                "upload_date": "2025-10-22T14:30:00",
                "video_id": "abc123xyz"
            }
        }
        
        Args:
            data (dict): Data to validate
            
        Returns:
            bool: True if schema is valid, False otherwise
        """
        if not isinstance(data, dict):
            return False
        
        for hash_key, metadata in data.items():
            # Each value must be a dict
            if not isinstance(metadata, dict):
                self._log(f"Invalid upload_history entry: {hash_key} (not a dict)")
                return False
            
            # Must have required keys
            required_keys = ['filename', 'upload_date', 'video_id']
            if not all(key in metadata for key in required_keys):
                self._log(f"Invalid upload_history entry: {hash_key} (missing keys)")
                return False
        
        return True
    
    def _validate_upload_state_schema(self, data):
        """
        Validates the structure of upload_state.json.

        Expected schema:
        {
            "C:/Videos/video.mp4": {
                "state": "uploading",  # or "pending", "completed", "failed"
                "timestamp": "2025-10-22T14:30:00",
                "retry_count": 0,  # optional, for failed uploads
                "next_retry_time": "2025-10-22T14:35:00"  # optional, for failed uploads
            }
        }

        Args:
            data (dict): Data to validate

        Returns:
            bool: True if schema is valid, False otherwise
        """
        if not isinstance(data, dict):
            return False

        valid_states = ['pending', 'uploading', 'completed', 'failed']

        for filepath, state_info in data.items():
            # Each value must be a dict
            if not isinstance(state_info, dict):
                self._log(f"Invalid upload_state entry: {filepath} (not a dict)")
                return False

            # Must have required keys
            if 'state' not in state_info or 'timestamp' not in state_info:
                self._log(f"Invalid upload_state entry: {filepath} (missing keys)")
                return False

            # State must be valid
            if state_info['state'] not in valid_states:
                self._log(f"Invalid upload_state entry: {filepath} (invalid state)")
                return False

            # Optional retry fields (must be valid if present)
            if 'retry_count' in state_info and not isinstance(state_info['retry_count'], int):
                self._log(f"Invalid upload_state entry: {filepath} (retry_count not an int)")
                return False

        return True
    
    def _validate_quota_state_schema(self, data):
        """
        Validates the structure of quota_state.json.
        
        Expected schema:
        {
            "last_quota_hit": "2025-10-22T14:30:00"
        }
        
        Args:
            data (dict): Data to validate
            
        Returns:
            bool: True if schema is valid, False otherwise
        """
        if not isinstance(data, dict):
            return False
        
        # Can be empty (no quota hit yet)
        if not data:
            return True
        
        # If it has data, must have last_quota_hit key
        if 'last_quota_hit' in data:
            # Validate it's a string that looks like a timestamp
            if isinstance(data['last_quota_hit'], str):
                return True
        
        self._log("Invalid quota_state schema")
        return False

    def _validate_playlist_sort_state_schema(self, data):
        """
        Validates the structure of playlist_sort_state.json.

        Expected schema:
        {
            "playlist_id": "PLxxx...",
            "sorted_items": [
                {"id": "xxx", "video_id": "yyy", "title": "zzz", ...},
                ...
            ],
            "last_position": 42
        }

        Args:
            data (dict): Data to validate

        Returns:
            bool: True if schema is valid, False otherwise
        """
        if not isinstance(data, dict):
            return False

        # Can be empty (no sort in progress)
        if not data:
            return True

        # If it has data, must have required keys
        required_keys = ['playlist_id', 'sorted_items', 'last_position']
        if not all(key in data for key in required_keys):
            self._log("Invalid playlist_sort_state schema: missing keys")
            return False

        # sorted_items must be a list
        if not isinstance(data['sorted_items'], list):
            self._log("Invalid playlist_sort_state schema: sorted_items not a list")
            return False

        # last_position must be an integer
        if not isinstance(data['last_position'], int):
            self._log("Invalid playlist_sort_state schema: last_position not an int")
            return False

        return True

    def _validate_preferences_schema(self, data):
        """
        Validates the structure of user_preferences.json.

        Expected schema:
        {
            "last_watch_folder": "C:/Videos",
            "privacy_setting": "unlisted",
            "playlist_title": "Gaming Clips",
            "video_category": "Gaming",
            "autonomous_mode": false,
            "auto_start_watching": false,
            "start_minimized": false,
            "notify_when_empty": true,
            "auto_close_when_empty": false,
            "start_with_windows": false,
            "notify_upload_success": false,
            "notify_upload_failed": true,
            "notify_quota_exceeded": true,
            "notify_batch_complete": false
        }

        Args:
            data (dict): Data to validate

        Returns:
            bool: True if schema is valid, False otherwise
        """
        if not isinstance(data, dict):
            return False

        # All fields are optional - just validate types if present
        optional_string_fields = ['last_watch_folder', 'privacy_setting', 'playlist_title', 'video_category']
        optional_bool_fields = ['autonomous_mode', 'auto_start_watching', 'start_minimized',
                               'notify_when_empty', 'auto_close_when_empty', 'start_with_windows',
                               'notify_upload_success', 'notify_upload_failed', 'notify_quota_exceeded',
                               'notify_batch_complete']

        for field in optional_string_fields:
            if field in data and not isinstance(data[field], str):
                self._log(f"Invalid user_preferences: {field} not a string")
                return False

        for field in optional_bool_fields:
            if field in data and not isinstance(data[field], bool):
                self._log(f"Invalid user_preferences: {field} not a boolean")
                return False

        return True

    # -------------------------------------------------------------------------
    # Load State from Disk
    # -------------------------------------------------------------------------
    
    def _load_all_state(self):
        """
        Loads all state files from disk into memory.
        
        This is called during initialization. If any file is corrupted,
        it's backed up and we start with an empty state.
        """
        # Load upload history
        self.upload_history = self._load_json_with_validation(
            config.UPLOAD_HISTORY_FILE,
            self._validate_upload_history_schema
        )
        
        # Load upload states
        self.upload_states = self._load_json_with_validation(
            config.UPLOAD_STATE_FILE,
            self._validate_upload_state_schema
        )
        
        # Load quota state
        self.quota_state = self._load_json_with_validation(
            config.QUOTA_STATE_FILE,
            self._validate_quota_state_schema
        )

        # Load playlist sort state
        self.playlist_sort_state = self._load_json_with_validation(
            config.PLAYLIST_SORT_STATE_FILE,
            self._validate_playlist_sort_state_schema
        )

        # Load user preferences
        self.user_preferences = self._load_json_with_validation(
            config.USER_PREFERENCES_FILE,
            self._validate_preferences_schema
        )

        self._log("State loading complete")
    
    # -------------------------------------------------------------------------
    # Upload History Management
    # -------------------------------------------------------------------------
    
    def is_file_uploaded(self, file_hash):
        """
        Checks if a file has already been uploaded (by MD5 hash).
        
        Args:
            file_hash (str): MD5 hash of the file
            
        Returns:
            bool: True if file was previously uploaded, False otherwise
            
        Example:
            >>> sm = StateManager()
            >>> if sm.is_file_uploaded("abc123..."):
            ...     print("Already uploaded!")
        """
        return file_hash in self.upload_history
    
    def add_upload_to_history(self, file_hash, filename, video_id):
        """
        Records a successful upload in the history.
        
        This prevents the same file from being uploaded again in the future.
        
        Args:
            file_hash (str): MD5 hash of the uploaded file
            filename (str): Original filename
            video_id (str): YouTube video ID returned by API
            
        Example:
            >>> sm = StateManager()
            >>> sm.add_upload_to_history("abc123...", "video.mp4", "dQw4w9WgXcQ")
        """
        self.upload_history[file_hash] = {
            'filename': filename,
            'upload_date': datetime.now().isoformat(),
            'video_id': video_id
        }
        
        # Persist to disk immediately
        self._atomic_write_json(config.UPLOAD_HISTORY_FILE, self.upload_history)
        self._log(f"Added {filename} to upload history")
    
    def get_upload_count(self):
        """
        Returns the total number of files uploaded (all time).
        
        Returns:
            int: Number of uploads in history
        """
        return len(self.upload_history)
    
    # -------------------------------------------------------------------------
    # Upload State Management (Crash Recovery)
    # -------------------------------------------------------------------------
    
    def set_upload_state(self, filepath, state, retry_count=None, next_retry_time=None):
        """
        Sets the current state of a file being processed with optional retry tracking.

        States: 'pending', 'uploading', 'completed', 'failed'

        This is used for crash recovery and retry management. If the app crashes
        while a file is in 'uploading' state, we know to retry it on next startup.
        For failed uploads, tracks retry attempts and next retry time.

        Args:
            filepath (str): Full path to the file
            state (str): One of: pending, uploading, completed, failed
            retry_count (int, optional): Number of retry attempts for failed uploads
            next_retry_time (str, optional): ISO timestamp for next retry attempt

        Example:
            >>> sm = StateManager()
            >>> sm.set_upload_state("C:/Videos/clip.mp4", "uploading")
            >>> # ... upload fails ...
            >>> sm.set_upload_state("C:/Videos/clip.mp4", "failed", retry_count=1, next_retry_time="2025-10-22T15:00:00")
        """
        state_info = {
            'state': state,
            'timestamp': datetime.now().isoformat()
        }

        # Add retry information if provided (for failed uploads)
        if retry_count is not None:
            state_info['retry_count'] = retry_count
        if next_retry_time is not None:
            state_info['next_retry_time'] = next_retry_time

        self.upload_states[filepath] = state_info

        # Persist to disk immediately (important for crash recovery)
        self._atomic_write_json(config.UPLOAD_STATE_FILE, self.upload_states)
        self._log(f"Set upload state for {os.path.basename(filepath)}: {state}")
    
    def get_upload_state(self, filepath):
        """
        Gets the current state of a file.
        
        Args:
            filepath (str): Full path to the file
            
        Returns:
            str: State ('pending', 'uploading', 'completed', 'failed'), or None
        """
        if filepath in self.upload_states:
            return self.upload_states[filepath].get('state')
        return None
    
    def get_incomplete_uploads(self):
        """
        Returns list of files that were being uploaded when app crashed.
        
        These are files in 'uploading' state that still exist on disk.
        They should be retried on next startup.
        
        Returns:
            list: Filepaths that need to be retried
            
        Example:
            >>> sm = StateManager()
            >>> incomplete = sm.get_incomplete_uploads()
            >>> for filepath in incomplete:
            ...     print(f"Retrying: {filepath}")
        """
        incomplete = []
        
        for filepath, state_info in self.upload_states.items():
            # Check if state is 'uploading' (interrupted)
            if state_info['state'] == 'uploading':
                # Only include if file still exists
                if os.path.exists(filepath):
                    incomplete.append(filepath)
                    self._log(f"Found incomplete upload: {os.path.basename(filepath)}")
        
        return incomplete
    
    def reset_incomplete_uploads_to_pending(self):
        """
        Resets all 'uploading' states to 'pending' for crash recovery.

        This should be called during app startup to handle files that
        were being uploaded when the app crashed.

        Returns:
            int: Number of uploads reset to pending
        """
        count = 0

        for filepath, state_info in list(self.upload_states.items()):
            if state_info['state'] == 'uploading' and os.path.exists(filepath):
                self.set_upload_state(filepath, 'pending')
                count += 1

        if count > 0:
            self._log(f"Reset {count} incomplete upload(s) to pending")

        return count

    def get_retry_count(self, filepath):
        """
        Gets the retry count for a file.

        Args:
            filepath (str): Full path to the file

        Returns:
            int: Number of retry attempts, or 0 if not tracked
        """
        if filepath in self.upload_states:
            return self.upload_states[filepath].get('retry_count', 0)
        return 0

    def is_ready_for_retry(self, filepath):
        """
        Checks if a failed upload is ready to be retried.

        A file is ready for retry if:
        1. It's in 'failed' state
        2. It hasn't exceeded max retry attempts
        3. The next retry time has been reached (or no retry time set)

        Args:
            filepath (str): Full path to the file

        Returns:
            bool: True if ready to retry, False otherwise
        """
        if filepath not in self.upload_states:
            return False

        state_info = self.upload_states[filepath]

        # Must be in failed state
        if state_info.get('state') != 'failed':
            return False

        # Check retry count
        retry_count = state_info.get('retry_count', 0)
        if retry_count >= config.MAX_UPLOAD_RETRY_ATTEMPTS:
            return False

        # Check if retry time has been reached
        next_retry_time = state_info.get('next_retry_time')
        if next_retry_time:
            try:
                next_retry_dt = datetime.fromisoformat(next_retry_time)
                if datetime.now() < next_retry_dt:
                    return False
            except Exception:
                # If we can't parse the time, allow retry
                pass

        return True

    def get_failed_uploads_for_retry(self):
        """
        Returns list of failed uploads that are ready to be retried.

        Only includes files that:
        - Are in 'failed' state
        - Haven't exceeded max retry attempts
        - Have reached their next retry time
        - Still exist on disk

        Returns:
            list: Filepaths that should be retried

        Example:
            >>> sm = StateManager()
            >>> failed = sm.get_failed_uploads_for_retry()
            >>> for filepath in failed:
            ...     print(f"Retrying: {filepath}")
        """
        retry_list = []

        for filepath, state_info in self.upload_states.items():
            if self.is_ready_for_retry(filepath) and os.path.exists(filepath):
                retry_list.append(filepath)
                self._log(f"File ready for retry: {os.path.basename(filepath)} "
                         f"(attempt {state_info.get('retry_count', 0) + 1}/{config.MAX_UPLOAD_RETRY_ATTEMPTS})")

        return retry_list
    
    # -------------------------------------------------------------------------
    # Quota State Management (24-Hour Cooldown)
    # -------------------------------------------------------------------------
    
    def get_last_quota_hit(self):
        """
        Returns the timestamp of the last quota hit.
        
        Returns:
            str: ISO format timestamp, or None if never hit quota
            
        Example:
            >>> sm = StateManager()
            >>> last_hit = sm.get_last_quota_hit()
            >>> if last_hit:
            ...     print(f"Last quota hit: {last_hit}")
        """
        return self.quota_state.get('last_quota_hit')
    
    def record_quota_hit(self):
        """
        Records that quota was hit right now.
        
        This starts the 24-hour cooldown period. No uploads will be attempted
        until 24 hours (+ buffer) after this timestamp.
        
        Example:
            >>> sm = StateManager()
            >>> sm.record_quota_hit()  # Starts 24-hour cooldown
        """
        now = datetime.now().isoformat()
        self.quota_state['last_quota_hit'] = now
        
        # Persist immediately (critical for cooldown enforcement)
        self._atomic_write_json(config.QUOTA_STATE_FILE, self.quota_state)
        self._log(f"Recorded quota hit at {now}")
    
    def clear_quota_state(self):
        """
        Clears the quota state (removes cooldown).
        
        This can be used for manual reset, though normally the cooldown
        expires automatically after 24 hours.
        
        Example:
            >>> sm = StateManager()
            >>> sm.clear_quota_state()  # Removes cooldown
        """
        self.quota_state = {}
        self._atomic_write_json(config.QUOTA_STATE_FILE, self.quota_state)
        self._log("Cleared quota state")

    # -------------------------------------------------------------------------
    # Playlist Sort State Management (Resume Capability)
    # -------------------------------------------------------------------------

    def get_playlist_sort_state(self, playlist_id):
        """
        Gets the saved sort state for a playlist (if any).

        Args:
            playlist_id (str): ID of the playlist

        Returns:
            dict or None: Sort state with 'sorted_items' and 'last_position',
                         or None if no state saved for this playlist

        Example:
            >>> sm = StateManager()
            >>> state = sm.get_playlist_sort_state("PLxxx")
            >>> if state:
            ...     print(f"Resume from position {state['last_position']}")
        """
        if not self.playlist_sort_state:
            return None

        # Check if saved state is for this playlist
        if self.playlist_sort_state.get('playlist_id') == playlist_id:
            return self.playlist_sort_state
        else:
            return None

    def save_playlist_sort_state(self, playlist_id, sorted_items, last_position):
        """
        Saves the current playlist sort progress for resume capability.

        Args:
            playlist_id (str): ID of the playlist being sorted
            sorted_items (list): List of playlist items with sorted order
            last_position (int): Last position successfully updated (0-indexed)

        Example:
            >>> sm = StateManager()
            >>> sm.save_playlist_sort_state("PLxxx", items, 42)
        """
        self.playlist_sort_state = {
            'playlist_id': playlist_id,
            'sorted_items': sorted_items,
            'last_position': last_position
        }

        # Persist immediately
        self._atomic_write_json(config.PLAYLIST_SORT_STATE_FILE, self.playlist_sort_state)
        self._log(f"Saved playlist sort state at position {last_position}")

    def clear_playlist_sort_state(self):
        """
        Clears the playlist sort state (sort completed or cancelled).

        Example:
            >>> sm = StateManager()
            >>> sm.clear_playlist_sort_state()
        """
        self.playlist_sort_state = {}
        self._atomic_write_json(config.PLAYLIST_SORT_STATE_FILE, self.playlist_sort_state)
        self._log("Cleared playlist sort state")

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_statistics(self):
        """
        Returns statistics about the current state.
        
        Useful for displaying in GUI or logs.
        
        Returns:
            dict: Statistics including upload counts, pending uploads, etc.
            
        Example:
            >>> sm = StateManager()
            >>> stats = sm.get_statistics()
            >>> print(f"Total uploads: {stats['total_uploads']}")
        """
        stats = {
            'total_uploads': len(self.upload_history),
            'pending_uploads': sum(1 for s in self.upload_states.values() if s['state'] == 'pending'),
            'uploading_now': sum(1 for s in self.upload_states.values() if s['state'] == 'uploading'),
            'completed_uploads': sum(1 for s in self.upload_states.values() if s['state'] == 'completed'),
            'failed_uploads': sum(1 for s in self.upload_states.values() if s['state'] == 'failed'),
            'in_quota_cooldown': bool(self.get_last_quota_hit())
        }
        
        return stats
    
    def export_state_for_backup(self, backup_dir):
        """
        Exports all state files to a backup directory.
        
        Useful for manual backups before major changes.
        
        Args:
            backup_dir (str): Directory to store backup files
            
        Returns:
            bool: True if backup succeeded, False otherwise
        """
        try:
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Backup each state file
            files_to_backup = [
                config.UPLOAD_HISTORY_FILE,
                config.UPLOAD_STATE_FILE,
                config.QUOTA_STATE_FILE,
                config.PLAYLIST_SORT_STATE_FILE
            ]
            
            for filename in files_to_backup:
                if os.path.exists(filename):
                    backup_name = f"{filename}.{timestamp}.backup"
                    backup_path = os.path.join(backup_dir, backup_name)
                    shutil.copy2(filename, backup_path)
                    self._log(f"Backed up {filename} to {backup_path}")
            
            return True

        except Exception as e:
            self._log(f"Error creating backup: {str(e)}")
            return False

    # -------------------------------------------------------------------------
    # User Preferences Management
    # -------------------------------------------------------------------------

    def get_preference(self, key, default=None):
        """
        Gets a user preference value.

        Args:
            key (str): Preference key
            default: Default value if key doesn't exist

        Returns:
            The preference value, or default if not found

        Example:
            >>> sm = StateManager()
            >>> folder = sm.get_preference('last_watch_folder', 'C:/Videos')
        """
        return self.user_preferences.get(key, default)

    def set_preference(self, key, value):
        """
        Sets a user preference and saves to disk.

        Args:
            key (str): Preference key
            value: Preference value

        Example:
            >>> sm = StateManager()
            >>> sm.set_preference('last_watch_folder', 'C:/Videos/Gaming')
        """
        self.user_preferences[key] = value
        self._atomic_write_json(config.USER_PREFERENCES_FILE, self.user_preferences)
        self._log(f"Saved preference: {key}")

    def get_all_preferences(self):
        """
        Gets all user preferences with defaults applied.

        Returns:
            dict: All preferences with defaults for missing keys
        """
        defaults = {
            'last_watch_folder': '',
            'privacy_setting': config.DEFAULT_PRIVACY_SETTING,
            'playlist_title': 'No Playlist',
            'video_category': config.DEFAULT_VIDEO_CATEGORY,
            'autonomous_mode': config.DEFAULT_AUTONOMOUS_MODE,
            'auto_start_watching': config.DEFAULT_AUTO_START_WATCHING,
            'start_minimized': config.DEFAULT_START_MINIMIZED,
            'notify_when_empty': config.DEFAULT_NOTIFY_WHEN_EMPTY,
            'auto_close_when_empty': config.DEFAULT_AUTO_CLOSE_WHEN_EMPTY,
            'start_with_windows': False,
            'notify_upload_success': config.DEFAULT_NOTIFY_UPLOAD_SUCCESS,
            'notify_upload_failed': config.DEFAULT_NOTIFY_UPLOAD_FAILED,
            'notify_quota_exceeded': config.DEFAULT_NOTIFY_QUOTA_EXCEEDED,
            'notify_batch_complete': config.DEFAULT_NOTIFY_BATCH_COMPLETE
        }

        # Merge user preferences with defaults
        prefs = defaults.copy()
        prefs.update(self.user_preferences)
        return prefs

    def save_all_preferences(self, preferences):
        """
        Saves all preferences at once.

        Args:
            preferences (dict): Dictionary of preferences to save

        Example:
            >>> sm = StateManager()
            >>> prefs = {
            ...     'last_watch_folder': 'C:/Videos',
            ...     'autonomous_mode': True
            ... }
            >>> sm.save_all_preferences(prefs)
        """
        self.user_preferences = preferences
        self._atomic_write_json(config.USER_PREFERENCES_FILE, self.user_preferences)
        self._log("Saved all user preferences")
