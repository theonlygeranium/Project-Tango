#!/usr/bin/env python3
"""
WRITER Agent Playbook Client

Invokes WRITER Agent playbooks via webhook and polls for completion.
Designed for Discord bot integration with async/await support.

Usage:
    client = WriterPlaybookClient(webhook_url, api_key)
    result = await client.invoke_playbook(inputs={}, timeout=300)
"""

import aiohttp
import asyncio
import logging
import json
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PlaybookResult:
    """Result from a WRITER playbook execution"""
    thread_id: str
    status: str  # completed, failed, stopped, awaiting_user_response
    deliverables: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    
    @property
    def success(self) -> bool:
        return self.status == "completed"
    
    @property
    def needs_user_input(self) -> bool:
        return self.status == "awaiting_user_response"


class WriterPlaybookClient:
    """
    Async client for invoking WRITER Agent playbooks via webhook.
    
    Handles:
    - Playbook triggering
    - Status polling with exponential backoff
    - Deliverables download
    - Error handling and timeouts
    """
    
    def __init__(
        self,
        webhook_url: str,
        api_key: str,
        poll_interval: int = 10,
        max_poll_attempts: int = 180,  # 30 minutes at 10s interval
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.webhook_url = webhook_url
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts
        self._session = session
        self._own_session = session is None
    
    async def __aenter__(self):
        if self._own_session:
            self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._own_session and self._session:
            await self._session.close()
    
    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Client must be used as context manager or provide session")
        return self._session
    
    async def invoke_playbook(
        self,
        inputs: List[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        progress_callback: Optional[callable] = None,
        continue_thread_id: Optional[str] = None
    ) -> PlaybookResult:
        """
        Invoke a WRITER playbook and wait for completion.
        
        Args:
            inputs: List of input variables for the playbook (default: empty list)
            timeout: Maximum seconds to wait for completion (default: poll_interval * max_poll_attempts)
            progress_callback: Optional async function called with status updates
                              Signature: async def callback(status: str, attempt: int, max_attempts: int)
            continue_thread_id: Optional thread ID to continue an existing conversation
        
        Returns:
            PlaybookResult with status, deliverables, and metadata
        
        Raises:
            asyncio.TimeoutError: If playbook doesn't complete within timeout
            aiohttp.ClientError: If HTTP request fails
        """
        start_time = datetime.now()
        inputs = inputs or []
        
        # Step 1: Trigger the playbook (or continue existing thread)
        if continue_thread_id:
            logger.info(f"Continuing WRITER thread: {continue_thread_id}")
            thread_id = continue_thread_id
            initial_status = "running"
        else:
            logger.info(f"Triggering WRITER playbook: {self.webhook_url}")
            thread_id, initial_status = await self._trigger_playbook(inputs)
            logger.info(f"Playbook started: thread_id={thread_id}, initial_status={initial_status}")
        
        if progress_callback:
            await progress_callback("triggered", 0, self.max_poll_attempts)
        
        # Step 2: Poll for completion
        status = initial_status or "running"
        terminal_statuses = {"completed", "failed", "stopped", "awaiting_user_response"}
        
        for attempt in range(1, self.max_poll_attempts + 1):
            if status in terminal_statuses:
                break
            
            # Check timeout
            if timeout:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= timeout:
                    raise asyncio.TimeoutError(
                        f"Playbook exceeded timeout of {timeout}s (thread_id={thread_id})"
                    )
            
            # Wait before polling
            await asyncio.sleep(self.poll_interval)
            
            # Poll status
            status = await self._poll_status(thread_id)
            logger.info(f"[{attempt}/{self.max_poll_attempts}] Status: {status}")
            
            if progress_callback:
                await progress_callback(status, attempt, self.max_poll_attempts)
        
        # Check if we exhausted attempts
        if status not in terminal_statuses:
            raise asyncio.TimeoutError(
                f"Playbook did not complete after {self.max_poll_attempts} attempts "
                f"(last status: {status}, thread_id={thread_id})"
            )
        
        # Step 3: Download deliverables (if completed)
        deliverables = None
        error_message = None
        
        if status == "completed":
            logger.info(f"Attempting to download deliverables for thread_id={thread_id}")
            try:
                deliverables = await asyncio.wait_for(
                    self._download_deliverables(thread_id),
                    timeout=60  # 60 second timeout for deliverables
                )
                logger.info(f"Deliverables downloaded: {len(deliverables or {})} items")
            except asyncio.TimeoutError:
                logger.warning(f"Deliverables download timed out, trying thread messages fallback")
                # Fallback: Try to get thread messages instead
                try:
                    deliverables = await self._download_thread_messages(thread_id)
                    logger.info(f"Thread messages retrieved as fallback")
                except Exception as e:
                    logger.error(f"Thread messages fallback also failed: {e}")
                    error_message = "Deliverables download timed out"
            except Exception as e:
                logger.error(f"Failed to download deliverables: {e}")
                error_message = f"Deliverables download failed: {str(e)}"
        elif status == "failed":
            error_message = "Playbook execution failed"
        elif status == "stopped":
            error_message = "Playbook was stopped"
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return PlaybookResult(
            thread_id=thread_id,
            status=status,
            deliverables=deliverables,
            error_message=error_message,
            execution_time_seconds=execution_time
        )
    
    async def _trigger_playbook(self, inputs: List[Dict[str, Any]]) -> tuple[str, str]:
        """
        Trigger the playbook webhook.
        
        Returns:
            (thread_id, initial_status)
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {"inputs": inputs}
        
        async with self.session.post(
            self.webhook_url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60)
        ) as response:
            if response.status not in (200, 201):
                error_text = await response.text()
                raise aiohttp.ClientError(
                    f"Playbook trigger failed ({response.status}): {error_text}"
                )
            
            data = await response.json()
            thread_id = data.get("thread_id")
            if not thread_id:
                raise ValueError(f"Response missing thread_id: {data}")
            
            initial_status = data.get("status", "running")
            return thread_id, initial_status
    
    async def _poll_status(self, thread_id: str) -> str:
        """
        Poll the playbook status.
        
        Returns:
            Current status string
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        url = f"{self.webhook_url}/threads/{thread_id}/status"
        
        async with self.session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise aiohttp.ClientError(
                    f"Status poll failed ({response.status}): {error_text}"
                )
            
            data = await response.json()
            status = data.get("status")
            if not status:
                raise ValueError(f"Status response missing status field: {data}")
            
            return status
    
    async def _download_deliverables(
        self,
        thread_id: str,
        max_attempts: int = 30,
        retry_delay: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Download playbook deliverables with retry logic.
        
        Returns:
            Deliverables dict or None if not available
        """
        logger.info(f"Starting deliverables download for thread_id={thread_id}, max_attempts={max_attempts}")
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        url = f"{self.webhook_url}/threads/{thread_id}/deliverables"
        logger.info(f"Deliverables URL: {url}")
        
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Deliverables attempt {attempt}/{max_attempts}")
            async with self.session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                # 202: Not ready yet
                if response.status == 202:
                    retry_after = response.headers.get("Retry-After", str(retry_delay))
                    try:
                        wait_seconds = int(retry_after)
                    except ValueError:
                        wait_seconds = retry_delay
                    
                    logger.debug(
                        f"[{attempt}/{max_attempts}] Deliverables not ready, "
                        f"retrying in {wait_seconds}s"
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                
                # 200: Should be deliverables
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    
                    # Check if it's JSON (status message) or actual deliverables
                    if "application/json" in content_type:
                        data = await response.json()
                        
                        # If it's a message saying "not ready", retry
                        if "message" in data:
                            logger.debug(f"Deliverables returned message: {data['message']}")
                            await asyncio.sleep(retry_delay)
                            continue
                        
                        # Otherwise, treat as deliverables
                        return data
                    
                    # If it's a ZIP or other binary, download and extract
                    elif "application/zip" in content_type or "application/octet-stream" in content_type:
                        logger.info(f"Downloading binary deliverable: {content_type}")
                        binary_data = await response.read()
                        
                        # Try to extract ZIP contents
                        try:
                            import io
                            import zipfile
                            
                            zip_buffer = io.BytesIO(binary_data)
                            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                                file_list = zip_ref.namelist()
                                logger.info(f"ZIP contains {len(file_list)} files: {file_list}")
                                
                                # Extract all text/markdown files
                                extracted_content = []
                                for filename in file_list:
                                    if filename.endswith(('.txt', '.md', '.json', '.log')):
                                        content = zip_ref.read(filename).decode('utf-8')
                                        extracted_content.append(f"=== {filename} ===\n{content}\n")
                                
                                if extracted_content:
                                    return {
                                        "type": "text",
                                        "content": "\n".join(extracted_content),
                                        "source": "zip_extraction",
                                        "files_extracted": len(extracted_content)
                                    }
                        except Exception as e:
                            logger.error(f"Failed to extract ZIP: {e}")
                        
                        # Fallback if extraction fails
                        return {
                            "type": "binary",
                            "content_type": content_type,
                            "size": len(binary_data),
                            "size_readable": f"{len(binary_data) / 1024:.1f} KB",
                            "note": "Binary deliverable downloaded but could not extract contents"
                        }
                    
                    # Text response - return as-is
                    else:
                        text = await response.text()
                        return {"type": "text", "content": text}
                
                # Other status codes
                error_text = await response.text()
                raise aiohttp.ClientError(
                    f"Deliverables download failed ({response.status}): {error_text}"
                )
        
        # Exhausted retries
        logger.warning(f"Deliverables not available after {max_attempts} attempts")
        return None
    
    async def _download_thread_messages(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Fallback: Download thread messages when deliverables aren't available.
        
        Returns:
            Dict with thread messages as deliverables format
        """
        logger.info(f"Fetching thread messages for thread_id={thread_id}")
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Try to get the thread's conversation/messages
        # WRITER API might have endpoints like /threads/{id}/messages or similar
        url = f"{self.webhook_url}/threads/{thread_id}"
        
        try:
            async with self.session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract the last assistant message as the deliverable
                    # The structure might vary, but typically there's a messages array
                    if "messages" in data:
                        messages = data["messages"]
                        # Get the last assistant message
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", "")
                                return {
                                    "type": "text",
                                    "content": content,
                                    "source": "thread_messages"
                                }
                    
                    # If no messages structure, try to extract any text content
                    if "content" in data:
                        return {
                            "type": "text",
                            "content": data["content"],
                            "source": "thread_data"
                        }
                    
                    # Last resort: return the whole response
                    return {
                        "type": "json",
                        "content": json.dumps(data, indent=2),
                        "source": "thread_raw"
                    }
                else:
                    logger.error(f"Thread fetch failed with status {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Failed to fetch thread messages: {e}")
            return None


# Convenience function for one-off invocations
async def invoke_writer_playbook(
    webhook_url: str,
    api_key: str,
    inputs: List[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
    progress_callback: Optional[callable] = None
) -> PlaybookResult:
    """
    Convenience function to invoke a WRITER playbook.
    
    Args:
        webhook_url: Full webhook URL
        api_key: Bearer token for authentication
        inputs: List of input variables (default: empty list)
        timeout: Maximum seconds to wait (default: 30 minutes)
        progress_callback: Optional async callback for progress updates
    
    Returns:
        PlaybookResult
    """
    async with WriterPlaybookClient(webhook_url, api_key) as client:
        return await client.invoke_playbook(inputs, timeout, progress_callback)


if __name__ == "__main__":
    # Example usage
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    async def example():
        # Example: Cursor LiteLLM Session Provisioning playbook
        webhook_url = "https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c"
        api_key = "4b7ddcec2fca099542b6fb888334cfd83683465dcd60e77d2c7678ec47e6affd"
        
        async def on_progress(status: str, attempt: int, max_attempts: int):
            print(f"Progress: {status} ({attempt}/{max_attempts})")
        
        result = await invoke_writer_playbook(
            webhook_url=webhook_url,
            api_key=api_key,
            inputs=[],
            timeout=1800,  # 30 minutes
            progress_callback=on_progress
        )
        
        print(f"\n=== Playbook Result ===")
        print(f"Thread ID: {result.thread_id}")
        print(f"Status: {result.status}")
        print(f"Success: {result.success}")
        print(f"Execution Time: {result.execution_time_seconds:.1f}s")
        
        if result.deliverables:
            print(f"\nDeliverables:")
            print(json.dumps(result.deliverables, indent=2))
        
        if result.error_message:
            print(f"\nError: {result.error_message}")
    
    asyncio.run(example())
