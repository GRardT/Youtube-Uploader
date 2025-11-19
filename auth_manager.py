# =============================================================================
# auth_manager.py - YouTube Uploader v2.0 Authentication Module
# =============================================================================
# Purpose: Manages OAuth authentication and YouTube API client initialization.
#
# Key Features:
# - OAuth 2.0 token management
# - Automatic token refresh
# - Secure token storage with file permissions
# - Re-authentication flow when tokens expire
# - Internet connectivity checks
# - Playlist fetching
#
# Security:
# - Token files protected with Windows ACLs (owner-only access)
# - Sensitive data never logged
# - Corrupted tokens backed up with timestamp
# =============================================================================

import os
import pickle
import time
import requests
from datetime import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import config

# Windows-specific imports for file permissions
try:
    import win32security
    import ntsecuritycon as con
    WINDOWS_SECURITY_AVAILABLE = True
except ImportError:
    WINDOWS_SECURITY_AVAILABLE = False


# ============================================================================
# Utility Functions (Module-Level)
# ============================================================================

def test_youtube_api_connection(youtube_client):
    """
    Tests YouTube API client connection by making a lightweight test call.

    This utility function is used by both AuthManager (during initialization)
    and UploadManager (before batch uploads) to verify the connection is working
    without duplicating code.

    Args:
        youtube_client: Authenticated YouTube API client

    Returns:
        bool: True if connection test succeeded, False otherwise

    Example:
        >>> if test_youtube_api_connection(youtube):
        ...     print("Connection is healthy")
    """
    if not youtube_client:
        return False

    try:
        # Make a lightweight API call to test connection
        # channels().list() is fast and requires no quota units
        request = youtube_client.channels().list(
            part="id",
            mine=True,
            maxResults=1
        )
        response = request.execute()

        # Check if we got a valid response
        return bool(response.get('items'))

    except Exception:
        # Any exception means connection test failed
        return False


class AuthenticationError(Exception):
    """
    Custom exception for authentication failures.
    
    This allows calling code to distinguish between authentication errors
    and other types of errors (network, API, etc.)
    """
    pass


class AuthManager:
    """
    Manages YouTube API authentication and client initialization.
    
    This class handles:
    - Initial OAuth authorization (browser-based)
    - Token storage and refresh
    - YouTube client creation
    - Playlist fetching
    - Internet connectivity checks
    
    Attributes:
        youtube: Authenticated YouTube API client (googleapiclient Resource)
        playlists (dict): User's playlists {title: id, "No Playlist": None}
    """
    
    def __init__(self, logger=None):
        """
        Initialize the AuthManager.
        
        Args:
            logger (callable, optional): Function to call for logging messages.
                                        If None, no logging is performed.
        """
        self.logger = logger
        self.youtube = None
        self.playlists = {"No Playlist": None}  # Default: no playlist selected
        
    def _log(self, message):
        """
        Internal logging helper.
        
        Args:
            message (str): Message to log
        """
        if self.logger:
            self.logger(message)
    
    # -------------------------------------------------------------------------
    # Internet Connectivity Check (Required Before Auth)
    # -------------------------------------------------------------------------
    
    def wait_for_internet(self, max_wait=None, interval=None):
        """
        Waits for stable internet connection before proceeding.
        
        This is critical because:
        - OAuth requires internet to reach Google's auth servers
        - Token refresh requires internet
        - VPN connections may take time to establish
        
        The function tries multiple URLs to avoid false negatives from
        one service being down or blocked.
        
        Args:
            max_wait (int, optional): Maximum seconds to wait. Uses config default if None.
            interval (int, optional): Seconds between checks. Uses config default if None.
            
        Returns:
            bool: True if internet is available, False if timeout
            
        Example:
            >>> auth = AuthManager()
            >>> if auth.wait_for_internet():
            ...     print("Internet ready!")
            ... else:
            ...     print("No internet after 5 minutes")
        """
        max_wait = max_wait or config.MAX_INTERNET_WAIT_SECONDS
        interval = interval or config.INTERNET_CHECK_INTERVAL_SECONDS
        
        self._log("Waiting for VPN/Internet connectivity...")
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            # Try each URL in our connectivity check list
            for url in config.CONNECTIVITY_CHECK_URLS:
                try:
                    response = requests.get(
                        url,
                        timeout=config.CONNECTIVITY_CHECK_TIMEOUT
                    )
                    
                    # If we get a successful response, we have internet
                    if response.status_code == 200:
                        self._log(f"Internet connectivity detected via {url}")
                        return True
                        
                except requests.RequestException:
                    # This URL failed, try the next one
                    continue
            
            # None of the URLs worked, wait and try again
            self._log(f"Internet not available yet, retrying in {interval}s...")
            time.sleep(interval)
        
        # Timeout reached without successful connection
        self._log(f"Internet not available after {max_wait}s")
        return False
    
    # -------------------------------------------------------------------------
    # Token File Security (Windows Only)
    # -------------------------------------------------------------------------
    
    def _secure_token_file(self, filepath):
        """
        Sets Windows file permissions to owner-only access.
        
        This prevents other users on the same system from reading the
        OAuth token file, which could be used to access your YouTube account.
        
        On non-Windows systems or if win32security is not available,
        this function does nothing (logs a warning).
        
        Args:
            filepath (str): Path to token file to secure
            
        Security Note:
            This is defense-in-depth. The token.pickle file should already
            be in .gitignore, but this adds protection against local attacks.
        """
        if not WINDOWS_SECURITY_AVAILABLE:
            self._log("Warning: Windows security modules not available, "
                     "cannot set restrictive permissions on token file")
            return
        
        try:
            # Get current user's SID (Security Identifier)
            user, domain, type = win32security.LookupAccountName("", os.getlogin())
            
            # Create a new security descriptor
            sd = win32security.SECURITY_DESCRIPTOR()
            
            # Create a DACL (Discretionary Access Control List)
            dacl = win32security.ACL()
            
            # Add ACE (Access Control Entry) for current user: FULL_CONTROL
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION,
                con.FILE_ALL_ACCESS,
                user
            )
            
            # Set the DACL on the security descriptor
            sd.SetSecurityDescriptorDacl(1, dacl, 0)
            
            # Apply the security descriptor to the file
            win32security.SetFileSecurity(
                filepath,
                win32security.DACL_SECURITY_INFORMATION,
                sd
            )
            
            self._log(f"Set restrictive permissions on {filepath}")
            
        except Exception as e:
            self._log(f"Warning: Could not set restrictive permissions on token file: {e}")
    
    # -------------------------------------------------------------------------
    # OAuth Token Management
    # -------------------------------------------------------------------------
    
    def _load_credentials(self):
        """
        Loads OAuth credentials from token.pickle file.
        
        Returns:
            Credentials: Google OAuth credentials, or None if file doesn't exist
            
        Raises:
            AuthenticationError: If token file is corrupted
        """
        if not os.path.exists(config.TOKEN_FILE):
            self._log("No existing token file found")
            return None
        
        try:
            with open(config.TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
            
            self._log("Loaded credentials from token.pickle")
            return creds
            
        except Exception as e:
            # Token file is corrupted - back it up and start fresh
            backup_name = f"token_corrupt_{int(time.time())}.pickle"
            self._log(f"Token file corrupted, backing up to {backup_name}")
            
            try:
                os.rename(config.TOKEN_FILE, backup_name)
            except Exception as rename_error:
                self._log(f"Could not backup corrupted token: {rename_error}")
            
            raise AuthenticationError(f"Token file corrupted: {str(e)}")
    
    def _save_credentials(self, creds):
        """
        Saves OAuth credentials to token.pickle file with secure permissions.
        
        Args:
            creds (Credentials): Google OAuth credentials to save
        """
        try:
            with open(config.TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
            
            # Set restrictive file permissions (Windows only)
            self._secure_token_file(config.TOKEN_FILE)
            
            self._log("Saved credentials to token.pickle")
            
        except Exception as e:
            self._log(f"Error saving credentials: {str(e)}")
            raise AuthenticationError(f"Failed to save credentials: {str(e)}")
    
    def _refresh_credentials(self, creds):
        """
        Refreshes expired OAuth credentials.
        
        OAuth tokens expire after ~1 hour, but they come with a refresh token
        that can be used to get a new access token without re-authenticating.
        
        Args:
            creds (Credentials): Expired credentials with refresh token
            
        Returns:
            Credentials: Refreshed credentials
            
        Raises:
            AuthenticationError: If refresh fails
        """
        try:
            self._log("Refreshing expired credentials...")
            creds.refresh(Request())
            self._log("Credentials refreshed successfully")
            return creds
            
        except Exception as e:
            self._log(f"Failed to refresh credentials: {str(e)}")
            raise AuthenticationError("Token refresh failed, re-authentication required")
    
    def _run_oauth_flow(self):
        """
        Runs the OAuth 2.0 authorization flow (opens browser).
        
        This is the interactive flow where the user:
        1. Browser opens to Google's authorization page
        2. User logs in with their Google account
        3. User grants permissions to the app
        4. Browser redirects with authorization code
        5. App exchanges code for access/refresh tokens
        
        Returns:
            Credentials: New OAuth credentials
            
        Raises:
            AuthenticationError: If authorization fails
        """
        try:
            self._log("Starting OAuth authorization flow...")
            
            # Create flow from client secrets file
            flow = InstalledAppFlow.from_client_secrets_file(
                config.CLIENT_SECRETS_FILE,
                config.YOUTUBE_API_SCOPES
            )
            
            # Run local server to receive OAuth callback
            # port=0 means use any available port
            creds = flow.run_local_server(port=0)
            
            self._log("OAuth authorization successful")
            return creds
            
        except Exception as e:
            self._log(f"OAuth authorization failed: {str(e)}")
            raise AuthenticationError(f"Authorization failed: {str(e)}")
    
    # -------------------------------------------------------------------------
    # YouTube Client Initialization
    # -------------------------------------------------------------------------

    def _test_client_connection(self):
        """
        Tests the YouTube API client connection to warm up the connection.

        This uses the shared utility function to verify the connection is working
        before starting uploads. If the connection is bad, it fails fast instead
        of failing on the first upload.

        Returns:
            bool: True if connection test succeeded, False otherwise
        """
        self._log("Testing YouTube API connection...")

        if test_youtube_api_connection(self.youtube):
            self._log("YouTube API connection test successful")
            return True
        else:
            self._log("YouTube API connection test failed")
            return False

    def initialize_youtube_client(self, force_reauth=False):
        """
        Initializes the YouTube API client with authentication.

        This handles the full authentication flow:
        1. Check for internet connectivity
        2. Load existing credentials (if any)
        3. Refresh if expired
        4. Re-authenticate if necessary
        5. Build YouTube API client
        6. Test client connection (warm-up)
        7. Fetch user's playlists

        Args:
            force_reauth (bool): If True, forces re-authentication even if
                                token exists. Useful for troubleshooting.

        Raises:
            AuthenticationError: If authentication fails

        Example:
            >>> auth = AuthManager()
            >>> auth.initialize_youtube_client()
            >>> # Now auth.youtube is ready to use
        """
        # Step 1: Ensure internet is available
        if not self.wait_for_internet():
            raise AuthenticationError("No internet connection available")

        # Step 2: Get valid credentials
        creds = None

        if not force_reauth:
            # Try to load existing credentials
            try:
                creds = self._load_credentials()
            except AuthenticationError:
                # Token was corrupted, need to re-authenticate
                creds = None

        # Step 3: Check if credentials are valid
        if creds:
            if creds.expired and creds.refresh_token:
                # Token expired but we can refresh it
                try:
                    creds = self._refresh_credentials(creds)
                except AuthenticationError:
                    # Refresh failed, need to re-authenticate
                    creds = None
            elif not creds.valid:
                # Token is invalid for some other reason
                creds = None

        # Step 4: If still no valid credentials, run OAuth flow
        if not creds:
            creds = self._run_oauth_flow()

        # Step 5: Save credentials for future use
        self._save_credentials(creds)

        # Step 6: Build YouTube API client
        try:
            self.youtube = build(
                config.YOUTUBE_API_SERVICE_NAME,
                config.YOUTUBE_API_VERSION,
                credentials=creds
            )
            self._log(config.SUCCESS_AUTH)

        except Exception as e:
            raise AuthenticationError(f"Failed to build YouTube client: {str(e)}")

        # Step 7: Test client connection (warm-up)
        if not self._test_client_connection():
            raise AuthenticationError("Failed to establish connection to YouTube API")

        # Step 8: Fetch user's playlists
        self.fetch_playlists()
    
    def refresh_youtube_client(self):
        """
        Refreshes the YouTube API client without requiring re-authentication.

        This is used periodically to prevent stale connections (e.g., after VPN IP changes).
        It reuses existing credentials and just rebuilds the client and re-fetches playlists.

        This is lighter-weight than full re-authentication because:
        - We reuse the existing valid credentials (no OAuth flow)
        - We just rebuild the API client object
        - We re-fetch playlists in case anything changed

        Returns:
            bool: True if refresh succeeded, False if refresh failed

        Raises:
            AuthenticationError: If client build fails
        """
        try:
            # Load existing credentials (should be valid from initialization)
            creds = self._load_credentials()

            if not creds:
                self._log("Warning: No credentials available for refresh")
                return False

            # Rebuild the YouTube API client with same credentials
            try:
                self.youtube = build(
                    config.YOUTUBE_API_SERVICE_NAME,
                    config.YOUTUBE_API_VERSION,
                    credentials=creds
                )
            except Exception as e:
                raise AuthenticationError(f"Failed to rebuild YouTube client: {str(e)}")

            # Test the new client connection
            if not self._test_client_connection():
                raise AuthenticationError("New client connection test failed")

            # Re-fetch playlists in case they changed
            self.fetch_playlists()

            self._log("YouTube API client refresh completed successfully")
            return True

        except AuthenticationError as e:
            self._log(f"Failed to refresh YouTube client: {str(e)}")
            return False
        except Exception as e:
            self._log(f"Unexpected error refreshing YouTube client: {str(e)}")
            return False

    # -------------------------------------------------------------------------
    # Playlist Operations
    # -------------------------------------------------------------------------
    
    def fetch_playlists(self):
        """
        Fetches the user's YouTube playlists with pagination support.

        This populates self.playlists with {title: id} mappings.
        The "No Playlist" option is always included.

        Implements pagination to fetch all playlists, regardless of count.
        Loops through pages using nextPageToken until all playlists are retrieved.

        Raises:
            HttpError: If API request fails
        """
        if not self.youtube:
            self._log("Cannot fetch playlists: YouTube client not initialized")
            return

        try:
            # Start with "No Playlist" option
            new_playlists = {"No Playlist": None}

            # Pagination loop to fetch all playlists
            next_page_token = None
            page_count = 0

            while True:
                # Request user's playlists
                # mine=True ensures we only get the current user's playlists
                request = self.youtube.playlists().list(
                    part="snippet",
                    mine=True,
                    maxResults=config.MAX_PLAYLISTS_TO_FETCH,
                    pageToken=next_page_token
                )

                response = request.execute()
                page_count += 1

                # Add each playlist from the response
                for item in response.get("items", []):
                    playlist_title = item["snippet"]["title"]
                    playlist_id = item["id"]
                    new_playlists[playlist_title] = playlist_id

                # Check if there are more pages
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

                self._log(f"Fetching playlists page {page_count + 1}...")

            self.playlists = new_playlists

            playlist_count = len(self.playlists) - 1  # Don't count "No Playlist"
            self._log(f"Fetched {playlist_count} playlist(s) from YouTube ({page_count} page(s))")

        except HttpError as e:
            self._log(f"HTTP error fetching playlists: {str(e)}")
            # Keep default playlists (just "No Playlist")
        except Exception as e:
            self._log(f"Unexpected error fetching playlists: {str(e)}")
            # Keep default playlists (just "No Playlist")
    
    def get_playlist_titles(self):
        """
        Returns a list of playlist titles for GUI dropdown.
        
        Returns:
            list: Playlist titles including "No Playlist"
            
        Example:
            >>> auth = AuthManager()
            >>> auth.initialize_youtube_client()
            >>> titles = auth.get_playlist_titles()
            >>> print(titles)
            ['No Playlist', 'Gaming Clips', 'Tutorials', 'Vlogs']
        """
        return list(self.playlists.keys())
    
    def get_playlist_id(self, title):
        """
        Gets the playlist ID for a given title.
        
        Args:
            title (str): Playlist title
            
        Returns:
            str: Playlist ID, or None if title is "No Playlist" or not found
            
        Example:
            >>> auth = AuthManager()
            >>> playlist_id = auth.get_playlist_id("Gaming Clips")
        """
        return self.playlists.get(title)
    
    # -------------------------------------------------------------------------
    # Client Health Check
    # -------------------------------------------------------------------------
    
    def is_client_ready(self):
        """
        Checks if the YouTube client is initialized and ready to use.
        
        Returns:
            bool: True if client is ready, False otherwise
        """
        return self.youtube is not None
    
    def get_client(self):
        """
        Returns the YouTube API client.
        
        Returns:
            Resource: YouTube API client, or None if not initialized
            
        Raises:
            AuthenticationError: If client is not initialized
        """
        if not self.youtube:
            raise AuthenticationError("YouTube client not initialized")
        return self.youtube
