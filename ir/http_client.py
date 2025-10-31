"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Enhanced HTTP Client with Bot Detection Avoidance
"""

import time
import random
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional, List
from http.cookiejar import CookieJar


class RateLimiter:
    """Rate limiter to avoid triggering bot detection"""
    
    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        """
        Initialize rate limiter
        
        Args:
            min_delay: Minimum delay between requests in seconds
            max_delay: Maximum delay between requests in seconds
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time = 0
        self.domain_last_request = {}
    
    def wait(self, domain: Optional[str] = None):
        """Wait before making next request"""
        current_time = time.time()
        
        # Check domain-specific rate limit
        if domain:
            last_domain_request = self.domain_last_request.get(domain, 0)
            time_since_last = current_time - last_domain_request
            
            if time_since_last < self.min_delay:
                delay = self.min_delay - time_since_last
                delay += random.uniform(0, self.max_delay - self.min_delay)
                time.sleep(delay)
            
            self.domain_last_request[domain] = time.time()
        else:
            # Global rate limit
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_delay:
                delay = self.min_delay - time_since_last
                delay += random.uniform(0, self.max_delay - self.min_delay)
                time.sleep(delay)
        
        self.last_request_time = time.time()


class EnhancedHTTPClient:
    """
    Enhanced HTTP client with bot detection avoidance features:
    - Realistic browser headers
    - Cookie management
    - Rate limiting
    - Retry logic with exponential backoff
    - Session management
    """
    
    # Realistic user agents from common browsers
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    
    def __init__(
        self,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        max_retries: int = 3,
        timeout: int = 30
    ):
        """
        Initialize enhanced HTTP client
        
        Args:
            min_delay: Minimum delay between requests
            max_delay: Maximum delay between requests
            max_retries: Maximum number of retry attempts
            timeout: Request timeout in seconds
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.rate_limiter = RateLimiter(min_delay, max_delay)
        self.max_retries = max_retries
        self.timeout = timeout
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        
        # Session state
        self.session_headers = {}
    
    def get_headers(self, url: str, custom_headers: Optional[Dict] = None) -> Dict:
        """
        Get realistic browser headers
        
        Args:
            url: Target URL
            custom_headers: Optional custom headers to merge
            
        Returns:
            Dictionary of headers
        """
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        
        headers = {
            'User-Agent': random.choice(self.USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        # Add referer if we have session history for this domain
        if domain in self.session_headers:
            headers['Referer'] = self.session_headers[domain]
        
        # Merge custom headers
        if custom_headers:
            headers.update(custom_headers)
        
        return headers
    
    def fetch(
        self,
        url: str,
        custom_headers: Optional[Dict] = None,
        method: str = 'GET',
        data: Optional[bytes] = None,
        respect_rate_limit: bool = True
    ) -> str:
        """
        Fetch a web page with bot detection avoidance
        
        Args:
            url: URL to fetch
            custom_headers: Optional custom headers
            method: HTTP method
            data: Optional POST data
            respect_rate_limit: Whether to respect rate limiting
            
        Returns:
            Page content as string
            
        Raises:
            ValueError: If fetching fails after all retries
        """
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        
        for attempt in range(self.max_retries):
            try:
                # Rate limiting
                if respect_rate_limit:
                    self.rate_limiter.wait(domain)
                
                # Prepare request
                headers = self.get_headers(url, custom_headers)
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                
                # Make request
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1}/{self.max_retries})")
                response = self.opener.open(req, timeout=self.timeout)
                
                # Read and decode content
                content = response.read()
                
                # Handle different encodings
                try:
                    decoded_content = content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        decoded_content = content.decode('latin-1')
                    except:
                        decoded_content = content.decode('utf-8', errors='ignore')
                
                # Update session state
                self.session_headers[domain] = url
                
                return decoded_content
                
            except urllib.error.HTTPError as e:
                self.logger.warning(f"HTTP Error {e.code} for {url}")
                
                if e.code == 403:
                    # Bot detection - wait longer and retry
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 5 + random.uniform(1, 5)
                        self.logger.info(f"Got 403, waiting {wait_time:.1f}s before retry")
                        time.sleep(wait_time)
                        continue
                
                if e.code == 429:
                    # Rate limited - exponential backoff
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 10 + random.uniform(5, 15)
                        self.logger.info(f"Rate limited, waiting {wait_time:.1f}s before retry")
                        time.sleep(wait_time)
                        continue
                
                if e.code >= 500:
                    # Server error - retry with backoff
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 2 + random.uniform(1, 3)
                        self.logger.info(f"Server error {e.code}, waiting {wait_time:.1f}s before retry")
                        time.sleep(wait_time)
                        continue
                
                # Client error (4xx) - don't retry except 403, 429
                if attempt == self.max_retries - 1:
                    raise ValueError(f"HTTP Error {e.code}: {e.reason}")
                    
            except urllib.error.URLError as e:
                self.logger.warning(f"URL Error for {url}: {e.reason}")
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 2 + random.uniform(1, 3)
                    time.sleep(wait_time)
                    continue
                raise ValueError(f"Failed to fetch: {e.reason}")
                
            except Exception as e:
                self.logger.warning(f"Error fetching {url}: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 2 + random.uniform(1, 3)
                    time.sleep(wait_time)
                    continue
                raise ValueError(f"Failed to fetch: {str(e)}")
        
        raise ValueError(f"Failed to fetch {url} after {self.max_retries} attempts")
    
    def fetch_json(self, url: str, custom_headers: Optional[Dict] = None) -> dict:
        """
        Fetch and parse JSON response
        
        Args:
            url: URL to fetch
            custom_headers: Optional custom headers
            
        Returns:
            Parsed JSON data
        """
        import json
        
        headers = custom_headers or {}
        headers['Accept'] = 'application/json'
        
        content = self.fetch(url, custom_headers=headers)
        return json.loads(content)
    
    def check_robots_txt(self, base_url: str, path: str) -> bool:
        """
        Check if path is allowed by robots.txt
        
        Args:
            base_url: Base URL of the site
            path: Path to check
            
        Returns:
            True if allowed, False if disallowed
        """
        try:
            parsed = urllib.parse.urlparse(base_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            
            # Fetch robots.txt without rate limiting (it's usually allowed)
            robots_content = self.fetch(robots_url, respect_rate_limit=False)
            
            # Simple robots.txt parser
            user_agent_section = False
            for line in robots_content.split('\n'):
                line = line.strip()
                
                if line.startswith('User-agent:'):
                    ua = line.split(':', 1)[1].strip()
                    user_agent_section = (ua == '*' or 'bot' in ua.lower())
                
                elif user_agent_section and line.startswith('Disallow:'):
                    disallowed = line.split(':', 1)[1].strip()
                    if disallowed and path.startswith(disallowed):
                        return False
            
            return True
            
        except:
            # If we can't fetch robots.txt, assume allowed
            return True
    
    def clear_session(self):
        """Clear session state and cookies"""
        self.cookie_jar.clear()
        self.session_headers.clear()
