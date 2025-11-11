# =============================================================================
# upload_manager.py - YouTube Uploader v2.0 Upload Management Module
# =============================================================================
# Purpose: Core upload logic, quota management, and playlist operations.
#
# Key Features:
# - Video upload to YouTube with progress tracking
# - 24-hour quota cooldown enforcement
# - Automatic playlist addition after upload
# - Safe file handling (uses FileHandler)
# - Duplicate detection (uses StateManager)
# - Crash recovery support
#
# Data Flow:
# 1. Check if file already uploaded (via MD5 hash)
# 2. Mark file as 'uploading' in state
# 3. Upload to YouTube API
# 4. Add to playlist (if selected)
# 5. Safe move to Uploaded folder
# 6. Record in upload history
# 7. Mark as 'completed' in state
# =============================================================================

import os
import time
from datetime import datetime, timedelta
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import config


class UploadError(Exception):
    """
    Custom exception for upload failures.
    
    This allows calling code to distinguish between upload errors
    and other types of errors (auth, file I/O, etc.)
    """
    pass


class QuotaExceededError(Exception):
    """
    Custom exception for quota exceeded errors.
    
    This triggers the 24-hour cooldown period.
    """
    pass


class UploadManager:
    """
    Manages video uploads to YouTube with quota awareness.
    
    This class handles:
    - Video upload API calls
    - Quota exceeded detection and cooldown
    - Playlist insertion
    - File handling (via FileHandler)
    - State tracking (via StateManager)
    
    Attributes:
        youtube: Authenticated YouTube API client
        file_handler: FileHandler instance for safe file operations
        state_manager: StateManager instance for persistence
        privacy_status: Default privacy setting for uploads
    """
    
    def __init__(self, youtube_client, file_handler, state_manager, logger=None):
        """
        Initialize the UploadManager.
        
        Args:
            youtube_client: Authenticated YouTube API client (from AuthManager)
            file_handler: FileHandler instance
            state_manager: StateManager instance
            logger (callable, optional): Function to call for logging
        """
        self.youtube = youtube_client
        self.file_handler = file_handler
        self.state_manager = state_manager
        self.logger = logger
        
        # Default settings (can be changed via setters)
        self.privacy_status = config.DEFAULT_PRIVACY_SETTING
        self.selected_playlist_id = None
        self.selected_category = config.DEFAULT_VIDEO_CATEGORY

        # Session statistics
        self.session_upload_count = 0
    
    def _log(self, message):
        """
        Internal logging helper.
        
        Args:
            message (str): Message to log
        """
        if self.logger:
            self.logger(message)
    
    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------
    
    def set_privacy(self, privacy_status):
        """
        Sets the privacy status for future uploads.
        
        Args:
            privacy_status (str): One of: 'public', 'unlisted', 'private'
            
        Raises:
            ValueError: If privacy_status is invalid
        """
        if privacy_status not in config.PRIVACY_SETTINGS:
            raise ValueError(f"Invalid privacy status: {privacy_status}")
        
        self.privacy_status = privacy_status
        self._log(f"Privacy setting changed to: {privacy_status}")
    
    def set_playlist(self, playlist_id):
        """
        Sets the playlist for future uploads.

        Args:
            playlist_id (str or None): Playlist ID, or None for no playlist
        """
        self.selected_playlist_id = playlist_id

        if playlist_id:
            self._log(f"Playlist set to ID: {playlist_id}")
        else:
            self._log("Playlist set to: No Playlist")

    def set_category(self, category_name):
        """
        Sets the video category for future uploads.

        Args:
            category_name (str): Category name (e.g., "Gaming", "Education")

        Raises:
            ValueError: If category_name is not valid
        """
        if category_name not in config.VIDEO_CATEGORIES:
            raise ValueError(f"Invalid video category: {category_name}")

        self.selected_category = category_name
        self._log(f"Video category set to: {category_name}")
    
    # -------------------------------------------------------------------------
    # Quota Cooldown Management
    # -------------------------------------------------------------------------
    
    def is_in_cooldown(self):
        """
        Checks if we're currently in the 24-hour quota cooldown period.
        
        Returns:
            bool: True if in cooldown, False otherwise
            
        Example:
            >>> um = UploadManager(...)
            >>> if um.is_in_cooldown():
            ...     print("Can't upload yet, waiting for cooldown")
        """
        last_quota_hit = self.state_manager.get_last_quota_hit()
        
        if not last_quota_hit:
            return False
        
        try:
            # Parse the ISO timestamp
            last_hit_dt = datetime.fromisoformat(last_quota_hit)
            
            # Calculate when cooldown ends
            cooldown_end = last_hit_dt + timedelta(
                hours=config.QUOTA_COOLDOWN_HOURS,
                minutes=config.QUOTA_COOLDOWN_BUFFER_MINUTES
            )
            
            # Check if we're still before the cooldown end
            return datetime.now() < cooldown_end
            
        except Exception as e:
            self._log(f"Error checking cooldown: {str(e)}")
            return False
    
    def get_cooldown_end_time(self):
        """
        Returns when the current cooldown period ends.
        
        Returns:
            datetime: When cooldown ends, or None if not in cooldown
            
        Example:
            >>> um = UploadManager(...)
            >>> if um.is_in_cooldown():
            ...     end = um.get_cooldown_end_time()
            ...     print(f"Cooldown ends at {end.strftime('%H:%M:%S')}")
        """
        last_quota_hit = self.state_manager.get_last_quota_hit()
        
        if not last_quota_hit:
            return None
        
        try:
            last_hit_dt = datetime.fromisoformat(last_quota_hit)
            cooldown_end = last_hit_dt + timedelta(
                hours=config.QUOTA_COOLDOWN_HOURS,
                minutes=config.QUOTA_COOLDOWN_BUFFER_MINUTES
            )
            return cooldown_end
        except Exception:
            return None
    
    def record_quota_exceeded(self):
        """
        Records that quota was just exceeded.
        
        This starts the 24-hour cooldown period. No uploads should be
        attempted until the cooldown expires.
        """
        self.state_manager.record_quota_hit()
        self._log(config.INFO_QUOTA_EXCEEDED)
    
    # -------------------------------------------------------------------------
    # Video Upload (Core Functionality)
    # -------------------------------------------------------------------------
    
    def upload_video(self, filepath, progress_callback=None):
        """
        Uploads a single video file to YouTube.

        This is the core upload function that:
        1. Validates file exists
        2. Validates file size (<256GB)
        3. Computes MD5 hash for duplicate detection
        4. Checks for duplicates
        5. Marks as 'uploading' in state
        6. Prepares upload metadata
        7. Creates media upload object (chunked for large files)
        8. Uploads to YouTube API with progress tracking
        9. Adds to playlist (if selected)
        10. Moves to Uploaded folder
        11. Records in history
        12. Marks as 'completed'
        13. Updates session statistics

        Args:
            filepath (str): Full path to video file to upload
            progress_callback (callable, optional): Function(percent) for progress updates

        Returns:
            tuple: (success: bool, message: str, video_id: str or None)

        Raises:
            QuotaExceededError: If upload quota is exceeded

        Example:
            >>> um = UploadManager(...)
            >>> success, msg, video_id = um.upload_video("C:/Videos/clip.mp4")
            >>> if success:
            ...     print(f"Uploaded! Video ID: {video_id}")
        """
        try:
            filename = os.path.basename(filepath)

            # Step 1: Validate file exists
            if not os.path.isfile(filepath):
                return False, f"File not found: {filename}", None

            # Step 2: Validate file size (YouTube has 256GB limit)
            file_size = os.path.getsize(filepath)
            if file_size > config.MAX_FILE_SIZE_BYTES:
                size_formatted = config.format_file_size(file_size)
                max_size_formatted = config.format_file_size(config.MAX_FILE_SIZE_BYTES)
                error_msg = f"File too large: {filename} ({size_formatted}) exceeds YouTube's {max_size_formatted} limit"
                self._log(error_msg)
                return False, error_msg, None

            self._log(f"File size: {config.format_file_size(file_size)}")

            # Step 3: Compute MD5 hash for duplicate detection
            self._log(f"Computing hash for {filename}...")
            file_hash = self.file_handler.compute_file_hash(filepath)
            
            if file_hash is None:
                return False, f"Failed to compute hash for {filename}", None

            # Step 4: Check if already uploaded
            if self.state_manager.is_file_uploaded(file_hash):
                msg = config.INFO_ALREADY_UPLOADED.format(filename=filename)
                self._log(msg)
                return False, msg, None

            # Step 5: Mark as uploading (for crash recovery)
            self.state_manager.set_upload_state(filepath, 'uploading')

            # Step 6: Prepare upload metadata
            # Title is the filename without extension
            video_title = os.path.splitext(filename)[0]

            # Get category ID from category name
            category_id = config.VIDEO_CATEGORIES.get(self.selected_category, '22')

            body = {
                'snippet': {
                    'title': video_title,
                    'description': '',
                    'tags': [],
                    'categoryId': category_id
                },
                'status': {
                    'privacyStatus': self.privacy_status
                }
            }
            
            # Step 7: Create media upload object
            # Use chunked uploads for files larger than 100MB for better reliability
            # Smaller files upload in one chunk for simplicity
            chunk_size = config.UPLOAD_CHUNK_SIZE if file_size > 100 * 1024 * 1024 else -1
            media = MediaFileUpload(
                filepath,
                chunksize=chunk_size,
                resumable=True
            )

            # Step 8: Execute upload
            self._log(f"Uploading {filename} to YouTube...")

            try:
                request = self.youtube.videos().insert(
                    part=','.join(body.keys()),
                    body=body,
                    media_body=media
                )

                # Handle chunked vs non-chunked uploads
                if chunk_size == -1:
                    # Non-chunked: single execution
                    response = request.execute()
                    video_id = response['id']
                else:
                    # Chunked upload with progress tracking
                    response = None
                    while response is None:
                        status, response = request.next_chunk()
                        if status:
                            # Calculate progress percentage
                            progress = int(status.progress() * 100)
                            self._log(f"Upload progress: {progress}%")
                            if progress_callback:
                                progress_callback(progress)

                    video_id = response['id']

            except HttpError as e:
                # Check for quota exceeded errors
                error_content = str(e.content) if hasattr(e, 'content') else str(e)
                
                if 'quotaExceeded' in error_content or 'uploadLimitExceeded' in error_content:
                    # Record quota hit and stop uploading
                    self.record_quota_exceeded()
                    raise QuotaExceededError("YouTube upload quota exceeded")
                
                # Some other HTTP error
                raise
            
            finally:
                # Always close the file handle
                if hasattr(media, '_fd') and media._fd:
                    media._fd.close()
                    # Give system time to release file handle
                    # Using configured initial delay instead of hard-coded 1 second
                    time.sleep(config.INITIAL_FILE_OPERATION_DELAY)

            # Step 9: Add to playlist (if selected)
            if self.selected_playlist_id:
                try:
                    self._add_video_to_playlist(video_id, self.selected_playlist_id)
                except UploadError as e:
                    # Playlist is deleted or inaccessible
                    # Video was uploaded successfully but couldn't be added to playlist
                    error_msg = f"Video uploaded successfully but could not be added to playlist: {str(e)}"
                    self._log(error_msg)
                    # Mark as failed so user is notified
                    self.state_manager.set_upload_state(filepath, 'failed')
                    return False, error_msg, video_id

            # Step 10: Move file to Uploaded folder (safe move with verification)
            watch_folder = os.path.dirname(filepath)
            uploaded_folder = config.get_uploaded_folder_path(watch_folder)

            # Ensure Uploaded folder exists
            if not self.file_handler.ensure_directory_exists(uploaded_folder):
                self._log(f"Warning: Could not create Uploaded folder: {uploaded_folder}")

            # Safe move (copy + verify + delete)
            # Pass cached file_hash to avoid recomputing (optimization)
            destination = os.path.join(uploaded_folder, filename)
            move_success, move_msg = self.file_handler.safe_move(filepath, destination, file_hash)
            
            if not move_success:
                self._log(f"Warning: {move_msg}")
                self._log("File was uploaded but could not be moved. Original file remains.")

            # Step 11: Record in upload history
            self.state_manager.add_upload_to_history(file_hash, filename, video_id)

            # Step 12: Mark as completed
            self.state_manager.set_upload_state(filepath, 'completed')

            # Step 13: Update session statistics
            self.session_upload_count += 1
            
            success_msg = config.SUCCESS_UPLOAD.format(
                filename=filename,
                count=self.session_upload_count
            )
            self._log(success_msg)
            
            return True, success_msg, video_id
            
        except QuotaExceededError:
            # Re-raise quota errors so they can be handled by caller
            # Don't use retry mechanism for quota errors (need 24-hour cooldown instead)
            self.state_manager.set_upload_state(filepath, 'failed')
            raise

        except Exception as e:
            # Handle upload failure with retry mechanism
            retry_count = self.state_manager.get_retry_count(filepath)
            retry_count += 1

            if retry_count < config.MAX_UPLOAD_RETRY_ATTEMPTS:
                # Calculate next retry time using exponential backoff
                delay = min(
                    config.INITIAL_RETRY_DELAY_SECONDS * (2 ** (retry_count - 1)),
                    config.MAX_RETRY_DELAY_SECONDS
                )
                next_retry = datetime.now() + timedelta(seconds=delay)

                # Mark as failed with retry information
                self.state_manager.set_upload_state(
                    filepath,
                    'failed',
                    retry_count=retry_count,
                    next_retry_time=next_retry.isoformat()
                )

                error_msg = (f"Upload failed for {filename}: {str(e)}. "
                           f"Will retry (attempt {retry_count + 1}/{config.MAX_UPLOAD_RETRY_ATTEMPTS}) "
                           f"in {delay // 60} minute(s).")
                self._log(error_msg)
            else:
                # Max retries exceeded - mark as permanently failed
                self.state_manager.set_upload_state(
                    filepath,
                    'failed',
                    retry_count=retry_count
                )

                error_msg = (f"Upload failed for {filename} after {config.MAX_UPLOAD_RETRY_ATTEMPTS} attempts: {str(e)}. "
                           f"Manual intervention required.")
                self._log(error_msg)

            return False, error_msg, None
    
    # -------------------------------------------------------------------------
    # Playlist Operations
    # -------------------------------------------------------------------------
    
    def _add_video_to_playlist(self, video_id, playlist_id):
        """
        Adds a video to a playlist with validation.

        This is called automatically after successful upload if a playlist
        is selected. It's a separate API call from the upload.

        Validates that the playlist exists before attempting to add the video.
        If the playlist has been deleted, raises an error to notify the user.

        Args:
            video_id (str): YouTube video ID (from upload response)
            playlist_id (str): Playlist ID to add video to

        Returns:
            bool: True if successful, False otherwise

        Raises:
            UploadError: If playlist is deleted or inaccessible
        """
        try:
            # Step 1: Validate playlist exists before attempting to add video
            try:
                playlist_check = self.youtube.playlists().list(
                    part="snippet",
                    id=playlist_id
                ).execute()

                # If playlist doesn't exist, the items list will be empty
                if not playlist_check.get('items'):
                    error_msg = (f"ERROR: Cannot add video to playlist - "
                               f"playlist {playlist_id} no longer exists or is inaccessible. "
                               f"Please select a different playlist or re-authenticate.")
                    self._log(error_msg)
                    raise UploadError(error_msg)

            except HttpError as e:
                error_content = str(e.content) if hasattr(e, 'content') else str(e)
                if 'not found' in error_content.lower() or '404' in str(e):
                    error_msg = (f"ERROR: Cannot add video to playlist - "
                               f"playlist {playlist_id} no longer exists. "
                               f"Please select a different playlist.")
                    self._log(error_msg)
                    raise UploadError(error_msg)
                else:
                    # Re-raise other HTTP errors
                    raise

            # Step 2: Add video to playlist
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }

            request = self.youtube.playlistItems().insert(
                part="snippet",
                body=body
            )

            response = request.execute()

            success_msg = config.SUCCESS_PLAYLIST_ADD.format(
                video_id=video_id,
                playlist_id=playlist_id
            )
            self._log(success_msg)

            return True

        except UploadError:
            # Re-raise UploadError so caller can handle it
            raise
        except HttpError as e:
            error_content = str(e.content) if hasattr(e, 'content') else str(e)

            # Check for deleted/inaccessible playlist
            if 'not found' in error_content.lower() or 'playlistNotFound' in error_content:
                error_msg = (f"ERROR: Cannot add video to playlist - "
                           f"playlist {playlist_id} no longer exists or is inaccessible. "
                           f"Please select a different playlist.")
                self._log(error_msg)
                raise UploadError(error_msg)

            self._log(f"Error adding video {video_id} to playlist: {str(e)}")
            return False
        except Exception as e:
            self._log(f"Unexpected error adding to playlist: {str(e)}")
            return False

    def get_playlist_item_count(self, playlist_id):
        """
        Gets the number of videos in a playlist (lightweight operation).

        Args:
            playlist_id (str): ID of the playlist

        Returns:
            int: Number of videos in the playlist, or 0 if error

        Example:
            >>> um = UploadManager(...)
            >>> count = um.get_playlist_item_count("PLxxx")
            >>> print(f"Playlist has {count} videos")
        """
        try:
            # Use playlists.list to get the item count
            # This is cheaper than fetching all items
            request = self.youtube.playlists().list(
                part="contentDetails",
                id=playlist_id
            )
            response = request.execute()

            if response.get('items'):
                return response['items'][0]['contentDetails']['itemCount']
            else:
                return 0

        except Exception as e:
            self._log(f"Error getting playlist item count: {str(e)}")
            return 0

    def estimate_sort_quota_cost(self, num_videos):
        """
        Estimates the quota cost for sorting a playlist.

        Args:
            num_videos (int): Number of videos in the playlist

        Returns:
            int: Estimated quota cost in units

        Example:
            >>> um = UploadManager(...)
            >>> cost = um.estimate_sort_quota_cost(100)
            >>> print(f"Sorting will cost approximately {cost} quota units")
        """
        # Fetching pages: 1 unit per page of 50 videos
        fetch_pages = (num_videos + 49) // 50  # Ceiling division
        fetch_cost = fetch_pages * config.QUOTA_COST_PLAYLIST_LIST

        # Updating positions: 50 units per video
        update_cost = num_videos * config.QUOTA_COST_PLAYLIST_UPDATE

        return fetch_cost + update_cost

    def sort_playlist_alphabetically(self, playlist_id, progress_callback=None):
        """
        Sorts all videos in a playlist alphabetically by title.

        This fetches all videos from the playlist, sorts them by title,
        and updates their positions. For date-based filenames, this
        effectively sorts chronologically.

        Args:
            playlist_id (str): ID of playlist to sort
            progress_callback (callable, optional): Function(current, total, message)

        Returns:
            tuple: (success: bool, message: str, items_sorted: int)

        Example:
            >>> um = UploadManager(...)
            >>> success, msg, count = um.sort_playlist_alphabetically("PLxxx")
            >>> if success:
            ...     print(f"Sorted {count} videos")

        Note:
            YouTube API has quota costs:
            - Each playlistItems.list() costs 1 unit per page of 50
            - Each playlistItems.update() costs 50 units
            - For 100 videos: ~2 + (100 * 50) = 5,002 units
            - For 814 videos: ~17 + (814 * 50) = 40,717 units
            - Daily quota limit is typically 10,000 units
        """
        try:
            # Step 0: Check if there's a saved state for resume
            saved_state = self.state_manager.get_playlist_sort_state(playlist_id)

            if saved_state:
                # Resume from saved state
                self._log(f"Found saved sort state - resuming from position {saved_state['last_position'] + 1}")
                sorted_items = saved_state['sorted_items']
                start_position = saved_state['last_position'] + 1  # Continue from next position
            else:
                # No saved state - start fresh
                self._log(f"Fetching playlist items for sorting...")

                # Step 1: Fetch all videos in the playlist with pagination
                playlist_items = []
                next_page_token = None
                page_count = 0

                while True:
                    request = self.youtube.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=playlist_id,
                        maxResults=50,  # YouTube API max per page
                        pageToken=next_page_token
                    )

                    response = request.execute()
                    page_count += 1

                    items = response.get('items', [])
                    playlist_items.extend(items)

                    # Update progress
                    if progress_callback:
                        progress_callback(
                            len(playlist_items),
                            len(playlist_items),
                            f"Fetching playlist items (page {page_count})..."
                        )

                    # Check if there are more pages
                    next_page_token = response.get('nextPageToken')
                    if not next_page_token:
                        break

                if not playlist_items:
                    msg = "Playlist is empty, nothing to sort"
                    self._log(msg)
                    return False, msg, 0

                self._log(f"Found {len(playlist_items)} video(s) in playlist")

                # Estimate and log quota cost
                estimated_cost = self.estimate_sort_quota_cost(len(playlist_items))
                self._log(f"Estimated quota cost: {estimated_cost:,} units "
                         f"(Daily limit: {config.DEFAULT_DAILY_QUOTA_LIMIT:,} units)")

                if estimated_cost > config.DEFAULT_DAILY_QUOTA_LIMIT:
                    self._log(f"WARNING: Estimated cost ({estimated_cost:,}) exceeds daily quota limit "
                             f"({config.DEFAULT_DAILY_QUOTA_LIMIT:,}). This operation will likely fail partway through.")

                # Step 2: Sort by video title (alphabetically)
                # Store original data with new positions
                sorted_items = []
                for item in playlist_items:
                    video_title = item['snippet'].get('title', '')
                    sorted_items.append({
                        'id': item['id'],  # playlistItem ID (not video ID)
                        'video_id': item['contentDetails']['videoId'],
                        'title': video_title,
                        'snippet': item['snippet']
                    })

                # Sort alphabetically by title (case-insensitive)
                sorted_items.sort(key=lambda x: x['title'].lower())

                self._log("Sorted playlist items alphabetically")
                start_position = 0  # Start from beginning

            # Step 3: Update positions in the playlist
            # We need to update each item's position via the API
            # Start from start_position (0 for new sorts, or resume position for continued sorts)
            updated_count = start_position  # Count already-updated items
            failed_count = 0
            quota_exceeded = False
            last_successful_position = start_position - 1  # Track for resume

            for new_position in range(start_position, len(sorted_items)):
                item = sorted_items[new_position]
                # Update progress
                if progress_callback:
                    progress_callback(
                        new_position + 1,
                        len(sorted_items),
                        f"Updating position: {item['title'][:50]}..."
                    )

                try:
                    # Update the playlist item's position
                    # Note: snippet needs playlistId and resourceId
                    update_body = {
                        'id': item['id'],
                        'snippet': {
                            'playlistId': playlist_id,
                            'resourceId': {
                                'kind': 'youtube#video',
                                'videoId': item['video_id']
                            },
                            'position': new_position
                        }
                    }

                    request = self.youtube.playlistItems().update(
                        part='snippet',
                        body=update_body
                    )

                    response = request.execute()
                    updated_count += 1
                    last_successful_position = new_position

                except HttpError as e:
                    error_content = str(e.content) if hasattr(e, 'content') else str(e)

                    # Check for quota exceeded errors
                    if 'quotaExceeded' in error_content or 'uploadLimitExceeded' in error_content:
                        self._log(f"Quota exceeded while updating position for '{item['title']}'")

                        # Record quota hit for cooldown
                        self.record_quota_exceeded()

                        # Save state for resume capability
                        self.state_manager.save_playlist_sort_state(
                            playlist_id,
                            sorted_items,
                            last_successful_position
                        )

                        # Stop trying to update more items
                        quota_exceeded = True
                        failed_count = len(sorted_items) - updated_count
                        break
                    else:
                        # Some other error - log and continue
                        self._log(f"Error updating position for '{item['title']}': {str(e)}")
                        failed_count += 1
                        continue

            # Step 4: Report results
            if quota_exceeded:
                error_msg = (f"Quota exceeded after sorting {updated_count} of {len(sorted_items)} video(s). "
                            f"{failed_count} video(s) were not sorted. "
                            f"Wait 24 hours for quota to reset, then run sort again to continue.")
                self._log(error_msg)
                return False, error_msg, updated_count
            elif failed_count > 0:
                partial_msg = (f"Partially sorted playlist: {updated_count} succeeded, {failed_count} failed. "
                              f"Check logs for error details.")
                self._log(partial_msg)
                return False, partial_msg, updated_count
            else:
                # Sort completed successfully - clear saved state
                self.state_manager.clear_playlist_sort_state()

                success_msg = f"Successfully sorted {updated_count} video(s) in playlist alphabetically"
                self._log(success_msg)
                return True, success_msg, updated_count

        except HttpError as e:
            error_msg = f"YouTube API error during playlist sort: {str(e)}"
            self._log(error_msg)
            return False, error_msg, 0
        except Exception as e:
            error_msg = f"Unexpected error sorting playlist: {str(e)}"
            self._log(error_msg)
            return False, error_msg, 0
    
    # -------------------------------------------------------------------------
    # Batch Upload Operations
    # -------------------------------------------------------------------------
    
    def upload_files_from_folder(self, folder_path, progress_callback=None, should_stop_callback=None):
        """
        Uploads all video files from a folder sequentially.
        
        This processes files one at a time (not parallel) for stability.
        If quota is exceeded mid-batch, remaining files are skipped.
        
        Args:
            folder_path (str): Path to folder containing video files
            progress_callback (callable, optional): Function(current, total, percent)
            should_stop_callback (callable, optional): Function() -> bool to check if should stop
            
        Returns:
            dict: Statistics about the upload batch
                  {success_count, fail_count, skip_count, total_files}
        """
        results = {
            'success_count': 0,
            'fail_count': 0,
            'skip_count': 0,
            'total_files': 0,
            'quota_exceeded': False
        }
        
        try:
            # Get all video files in folder
            video_files = self.file_handler.get_video_files(folder_path)
            results['total_files'] = len(video_files)
            
            if not video_files:
                self._log(config.INFO_NO_VIDEOS_FOUND)
                return results
            
            self._log(f"Found {len(video_files)} video(s) to upload")
            
            # Process each file
            for i, filename in enumerate(video_files):
                # Check if we should stop (user clicked stop button, etc.)
                if should_stop_callback and should_stop_callback():
                    self._log("Upload batch stopped by user")
                    break
                
                # Update progress
                if progress_callback:
                    percent = (i / len(video_files)) * 100
                    progress_callback(i, len(video_files), percent)
                
                # Upload this file
                filepath = os.path.join(folder_path, filename)
                
                try:
                    success, message, video_id = self.upload_video(filepath)
                    
                    if success:
                        results['success_count'] += 1
                    else:
                        # File was skipped (already uploaded or other non-fatal error)
                        results['skip_count'] += 1
                        
                except QuotaExceededError:
                    # Quota exceeded - stop processing remaining files
                    results['quota_exceeded'] = True
                    self._log("Quota exceeded, stopping batch upload")
                    break
            
            # Final progress update
            if progress_callback:
                progress_callback(len(video_files), len(video_files), 100)
            
            # Log summary
            self._log(f"Batch upload complete: {results['success_count']} succeeded, "
                     f"{results['skip_count']} skipped, {results['fail_count']} failed")
            
            return results
            
        except Exception as e:
            self._log(f"Error in batch upload: {str(e)}")
            return results
    
    # -------------------------------------------------------------------------
    # Session Statistics
    # -------------------------------------------------------------------------
    
    def get_session_stats(self):
        """
        Returns statistics for the current session.
        
        Returns:
            dict: Session statistics
        """
        return {
            'uploads_this_session': self.session_upload_count,
            'total_uploads_all_time': self.state_manager.get_upload_count(),
            'privacy_setting': self.privacy_status,
            'playlist_selected': bool(self.selected_playlist_id),
            'in_cooldown': self.is_in_cooldown()
        }
