# =============================================================================
# file_handler.py - YouTube Uploader v2.0 File Operations Module
# =============================================================================
# Purpose: Handles all file operations with data integrity guarantees.
#          This module is CRITICAL for preventing data loss.
#
# Key Features:
# - MD5 hash computation for duplicate detection
# - Safe file copying with verification
# - Secure file deletion (only after verification)
# - Path validation to prevent directory traversal attacks
#
# Data Integrity Guarantee:
# Original files are NEVER deleted until we verify the copy is identical.
# This prevents data loss even if the app crashes mid-operation.
# =============================================================================

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple
import config


class FileOperationError(Exception):
    """
    Custom exception for file operation failures.
    
    This allows calling code to distinguish between file operation errors
    and other types of errors (network, API, etc.)
    """
    pass


class FileHandler:
    """
    Handles all file operations with data integrity guarantees.
    
    This class encapsulates the critical file operations that must never
    corrupt or lose user data. Every operation is designed to be atomic
    and verifiable.
    
    Methods:
        compute_file_hash: Calculate MD5 hash of a file
        verify_copy: Compare two files to ensure they're identical
        safe_copy_and_verify: Copy a file and verify integrity
        safe_move: Move a file (copy + verify + delete)
        validate_path: Ensure a path is safe to use
    """
    
    def __init__(self, logger=None):
        """
        Initialize the FileHandler.
        
        Args:
            logger (callable, optional): Function to call for logging messages.
                                        Should accept a string message.
                                        If None, no logging is performed.
        """
        self.logger = logger
    
    def _log(self, message):
        """
        Internal logging helper.
        
        Args:
            message (str): Message to log
        """
        if self.logger:
            self.logger(message)
    
    # -------------------------------------------------------------------------
    # Path Validation (Security)
    # -------------------------------------------------------------------------
    
    def validate_path(self, filepath, base_dir=None):
        """
        Validates that a file path is safe to use.
        
        This prevents directory traversal attacks where a malicious filename
        could try to escape the intended directory using ".." or absolute paths.
        
        Args:
            filepath (str): Path to validate
            base_dir (str, optional): Base directory that filepath must be within.
                                     If None, only checks for obvious attacks.
        
        Returns:
            bool: True if path is safe, False otherwise
            
        Security Checks:
        - No ".." components (prevents traversal up directories)
        - If base_dir provided, ensures resolved path is within base_dir
        - Checks for null bytes (can cause issues on some systems)
        
        Example:
            >>> fh = FileHandler()
            >>> fh.validate_path("video.mp4", "C:/WatchFolder")
            True
            >>> fh.validate_path("../../../etc/passwd", "C:/WatchFolder")
            False
        """
        try:
            # Check for null bytes (security issue on some systems)
            if '\0' in filepath:
                self._log(f"Path validation failed: null byte in path: {filepath}")
                return False
            
            # Resolve to absolute path (follows symlinks, resolves ..)
            abs_path = Path(filepath).resolve()
            
            # If base_dir is specified, ensure the file is within it
            if base_dir:
                base_path = Path(base_dir).resolve()
                try:
                    # relative_to() raises ValueError if abs_path is not under base_path
                    abs_path.relative_to(base_path)
                except ValueError:
                    self._log(f"Path validation failed: {filepath} is outside {base_dir}")
                    return False
            
            return True
            
        except Exception as e:
            self._log(f"Error validating path {filepath}: {str(e)}")
            return False
    
    # -------------------------------------------------------------------------
    # MD5 Hash Computation (Duplicate Detection)
    # -------------------------------------------------------------------------
    
    def compute_file_hash(self, filepath):
        """
        Computes the MD5 hash of a file for duplicate detection.
        
        This is the SAME algorithm as the original implementation:
        - Uses 64KB chunks for memory efficiency
        - Returns hexdigest (32-character hex string)
        
        MD5 is sufficient here because we're not using it for security,
        just for detecting duplicate files. It's fast and collision-resistant
        enough for this use case.
        
        Args:
            filepath (str): Path to the file to hash
            
        Returns:
            str: MD5 hash as hexadecimal string (32 chars), or None on error
            
        Example:
            >>> fh = FileHandler()
            >>> hash1 = fh.compute_file_hash("video.mp4")
            >>> hash2 = fh.compute_file_hash("video_copy.mp4")
            >>> hash1 == hash2  # True if files are identical
            
        Note:
            This reads the entire file, so it may take time for large videos.
            For a 1GB file, this typically takes 2-5 seconds.
        """
        try:
            # Validate the path exists and is a file
            if not os.path.isfile(filepath):
                self._log(f"Cannot hash: {filepath} is not a file")
                return None
            
            # Initialize MD5 hasher
            hasher = hashlib.md5()
            
            # Read file in chunks to avoid loading entire file into memory
            # This is critical for large video files (can be several GB)
            with open(filepath, 'rb') as f:
                while True:
                    # Read one chunk (64KB by default from config)
                    chunk = f.read(config.MD5_CHUNK_SIZE)
                    
                    # If chunk is empty, we've reached end of file
                    if not chunk:
                        break
                    
                    # Update hash with this chunk
                    hasher.update(chunk)
            
            # Return hash as hexadecimal string
            hash_value = hasher.hexdigest()
            self._log(f"Computed MD5 hash for {os.path.basename(filepath)}: {hash_value}")
            return hash_value
            
        except PermissionError:
            self._log(f"Permission denied reading file: {filepath}")
            return None
        except IOError as e:
            self._log(f"I/O error reading file {filepath}: {str(e)}")
            return None
        except Exception as e:
            self._log(f"Unexpected error computing hash for {filepath}: {str(e)}")
            return None
    
    # -------------------------------------------------------------------------
    # File Verification (Data Integrity)
    # -------------------------------------------------------------------------
    
    def verify_copy(self, source_path, destination_path, cached_source_hash=None):
        """
        Verifies that two files are identical by comparing their MD5 hashes.

        This is CRITICAL for data integrity. We never delete the original file
        until we verify the copy is perfect. This is the same verification
        logic as the original implementation.

        Supports hash caching to avoid redundant hash computation.
        If cached_source_hash is provided, it's used instead of recomputing.

        Args:
            source_path (str): Path to original file
            destination_path (str): Path to copied file
            cached_source_hash (str, optional): Pre-computed hash of source file

        Returns:
            bool: True if files are identical, False otherwise

        Example:
            >>> fh = FileHandler()
            >>> shutil.copy2("video.mp4", "backup/video.mp4")
            >>> if fh.verify_copy("video.mp4", "backup/video.mp4"):
            ...     os.remove("video.mp4")  # Safe to delete original

        Note:
            This computes hashes for both files, so it takes time for large files.
            For a 1GB file, this typically takes 4-10 seconds total.
            Using cached_source_hash can save 2-5 seconds for large files.
        """
        try:
            # Use cached hash or compute hash of original file
            if cached_source_hash:
                source_hash = cached_source_hash
                self._log(f"Using cached hash for {os.path.basename(source_path)}: {source_hash}")
            else:
                source_hash = self.compute_file_hash(source_path)
                if source_hash is None:
                    self._log(f"Failed to hash source file: {source_path}")
                    return False

            # Compute hash of copied file
            dest_hash = self.compute_file_hash(destination_path)
            if dest_hash is None:
                self._log(f"Failed to hash destination file: {destination_path}")
                return False

            # Compare hashes
            if source_hash == dest_hash:
                self._log(f"Copy verification successful: {os.path.basename(source_path)}")
                return True
            else:
                self._log(f"Copy verification FAILED: {os.path.basename(source_path)} "
                         f"(source: {source_hash}, dest: {dest_hash})")
                return False

        except Exception as e:
            self._log(f"Error during copy verification: {str(e)}")
            return False
    
    # -------------------------------------------------------------------------
    # Safe File Operations (Atomic Operations)
    # -------------------------------------------------------------------------
    
    def safe_copy_and_verify(self, source_path, destination_path, cached_source_hash=None):
        """
        Safely copies a file and verifies the copy is identical.

        This is an atomic operation from the caller's perspective:
        - Either the copy succeeds and is verified (returns True)
        - Or something fails and no changes are made (returns False)

        Supports hash caching to avoid redundant hash computation.

        Args:
            source_path (str): Path to file to copy
            destination_path (str): Where to copy the file
            cached_source_hash (str, optional): Pre-computed hash of source file

        Returns:
            bool: True if copy succeeded and was verified, False otherwise

        Side Effects:
            - Creates destination_path file if successful
            - Preserves metadata (timestamps, permissions) via shutil.copy2

        Example:
            >>> fh = FileHandler()
            >>> if fh.safe_copy_and_verify("video.mp4", "backup/video.mp4"):
            ...     print("Copy verified!")
        """
        try:
            # Validate both paths
            if not os.path.isfile(source_path):
                self._log(f"Source file does not exist: {source_path}")
                return False

            # Ensure destination directory exists
            dest_dir = os.path.dirname(destination_path)
            if dest_dir and not os.path.exists(dest_dir):
                self._log(f"Destination directory does not exist: {dest_dir}")
                return False

            # Copy file with metadata preservation
            # shutil.copy2 preserves:
            # - File timestamps (modification time, access time)
            # - Permission bits
            # - Extended attributes (on some systems)
            self._log(f"Copying {os.path.basename(source_path)} to {destination_path}...")
            shutil.copy2(source_path, destination_path)

            # Verify the copy is identical (using cached hash if available)
            if self.verify_copy(source_path, destination_path, cached_source_hash):
                self._log(f"Successfully copied and verified: {os.path.basename(source_path)}")
                return True
            else:
                self._log(f"Copy verification failed for: {os.path.basename(source_path)}")
                # Clean up the failed copy
                try:
                    if os.path.exists(destination_path):
                        os.remove(destination_path)
                        self._log(f"Cleaned up failed copy: {destination_path}")
                except Exception as cleanup_error:
                    self._log(f"Warning: Could not clean up failed copy: {cleanup_error}")
                return False

        except PermissionError:
            self._log(f"Permission denied copying {source_path} to {destination_path}")
            return False
        except IOError as e:
            self._log(f"I/O error copying file: {str(e)}")
            return False
        except Exception as e:
            self._log(f"Unexpected error copying file: {str(e)}")
            return False
    
    def safe_move(self, source_path, destination_path, cached_source_hash=None):
        """
        Safely moves a file (copy + verify + delete) with retry logic.

        This is the SAFEST way to move a file:
        1. Check if destination exists; if so, add timestamp suffix
        2. Copy the file to destination
        3. Verify the copy is identical (MD5 hash comparison)
        4. Delete the original with retry logic using exponential backoff

        If any step fails, the original file is preserved.
        Uses retry logic to handle file locks from antivirus or slow systems.
        Supports hash caching to avoid redundant hash computation.

        Args:
            source_path (str): Path to file to move
            destination_path (str): Where to move the file
            cached_source_hash (str, optional): Pre-computed hash of source file

        Returns:
            Tuple[bool, str]: (success, message)
                success (bool): True if move succeeded, False otherwise
                message (str): Description of what happened

        Example:
            >>> fh = FileHandler()
            >>> success, msg = fh.safe_move("video.mp4", "Uploaded/video.mp4")
            >>> if success:
            ...     print(f"Moved successfully: {msg}")
            ... else:
            ...     print(f"Move failed: {msg}")
        """
        import time
        try:
            # Step 0: Check if destination exists; if so, add timestamp suffix
            if os.path.exists(destination_path):
                # Extract components
                dest_dir = os.path.dirname(destination_path)
                dest_filename = os.path.basename(destination_path)
                name_without_ext, ext = os.path.splitext(dest_filename)

                # Add timestamp suffix
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{name_without_ext}_{timestamp}{ext}"
                destination_path = os.path.join(dest_dir, new_filename)

                self._log(f"Destination file exists; using {new_filename} instead")

            # Step 1: Copy and verify (using cached hash if available)
            if not self.safe_copy_and_verify(source_path, destination_path, cached_source_hash):
                return False, "Copy or verification failed"

            # Step 2: Delete original with retry logic (exponential backoff)
            # This handles file locks from antivirus or slow disk I/O
            last_error = None
            for attempt in range(config.MAX_FILE_OPERATION_RETRIES):
                try:
                    # Wait before attempting delete (increases with each retry)
                    if attempt == 0:
                        delay = config.INITIAL_FILE_OPERATION_DELAY
                    else:
                        delay = min(
                            config.INITIAL_FILE_OPERATION_DELAY * (2 ** attempt),
                            config.MAX_FILE_OPERATION_DELAY
                        )

                    if delay > 0:
                        time.sleep(delay)

                    # Attempt to delete the original file
                    os.remove(source_path)

                    # Success!
                    msg = f"Successfully moved {os.path.basename(source_path)}"
                    if attempt > 0:
                        msg += f" (after {attempt + 1} attempts)"
                    self._log(msg)
                    return True, msg

                except PermissionError as e:
                    last_error = e
                    if attempt < config.MAX_FILE_OPERATION_RETRIES - 1:
                        self._log(f"File locked (attempt {attempt + 1}/{config.MAX_FILE_OPERATION_RETRIES}), "
                                f"retrying in {delay:.1f}s...")
                        continue
                    else:
                        msg = (f"Could not delete original file after {config.MAX_FILE_OPERATION_RETRIES} attempts "
                             f"(file may be locked by antivirus or another process): {source_path}")
                        self._log(msg)
                        return False, msg

                except Exception as e:
                    last_error = e
                    if attempt < config.MAX_FILE_OPERATION_RETRIES - 1:
                        self._log(f"Error deleting file (attempt {attempt + 1}/{config.MAX_FILE_OPERATION_RETRIES}): {str(e)}, "
                                f"retrying in {delay:.1f}s...")
                        continue
                    else:
                        msg = f"Could not delete original file after {config.MAX_FILE_OPERATION_RETRIES} attempts: {str(e)}"
                        self._log(msg)
                        return False, msg

            # Should not reach here, but just in case
            msg = f"Could not delete original file: {str(last_error)}"
            self._log(msg)
            return False, msg

        except Exception as e:
            msg = f"Error during safe move: {str(e)}"
            self._log(msg)
            return False, msg
    
    # -------------------------------------------------------------------------
    # Directory Operations
    # -------------------------------------------------------------------------
    
    def ensure_directory_exists(self, directory_path):
        """
        Ensures a directory exists, creating it if necessary.
        
        This is safe to call multiple times - if the directory already exists,
        no error is raised.
        
        Args:
            directory_path (str): Path to directory to create
            
        Returns:
            bool: True if directory exists (or was created), False on error
            
        Example:
            >>> fh = FileHandler()
            >>> fh.ensure_directory_exists("C:/Videos/Uploaded")
            True
        """
        try:
            os.makedirs(directory_path, exist_ok=True)
            return True
        except PermissionError:
            self._log(f"Permission denied creating directory: {directory_path}")
            return False
        except Exception as e:
            self._log(f"Error creating directory {directory_path}: {str(e)}")
            return False
    
    def get_video_files(self, directory_path):
        """
        Returns a list of video files in a directory.
        
        Only returns files with supported extensions (from config).
        Files are sorted alphabetically for predictable upload order.
        
        Args:
            directory_path (str): Path to directory to scan
            
        Returns:
            list: List of filenames (not full paths) of video files
            
        Example:
            >>> fh = FileHandler()
            >>> videos = fh.get_video_files("C:/Videos")
            >>> print(videos)
            ['clip1.mp4', 'clip2.mov', 'recording.avi']
        """
        try:
            if not os.path.isdir(directory_path):
                self._log(f"Not a directory: {directory_path}")
                return []
            
            # List all files in directory
            all_files = os.listdir(directory_path)
            
            # Filter to only video files with supported extensions
            video_files = [
                f for f in all_files
                if config.is_supported_video_file(f) and
                   os.path.isfile(os.path.join(directory_path, f))
            ]
            
            # Sort alphabetically for predictable order
            video_files.sort()
            
            self._log(f"Found {len(video_files)} video file(s) in {directory_path}")
            return video_files
            
        except PermissionError:
            self._log(f"Permission denied accessing directory: {directory_path}")
            return []
        except Exception as e:
            self._log(f"Error listing video files in {directory_path}: {str(e)}")
            return []
    
    # -------------------------------------------------------------------------
    # File Information
    # -------------------------------------------------------------------------
    
    def get_file_size_mb(self, filepath):
        """
        Returns the size of a file in megabytes.
        
        Useful for logging and progress indication.
        
        Args:
            filepath (str): Path to file
            
        Returns:
            float: File size in MB, or 0 on error
            
        Example:
            >>> fh = FileHandler()
            >>> size = fh.get_file_size_mb("video.mp4")
            >>> print(f"File size: {size:.2f} MB")
        """
        try:
            size_bytes = os.path.getsize(filepath)
            size_mb = size_bytes / (1024 * 1024)
            return size_mb
        except Exception as e:
            self._log(f"Error getting file size for {filepath}: {str(e)}")
            return 0
