"""
Ollama Client for Local LLM inference.

Connects to a local Ollama server for query routing decisions.
"""
import httpx
from typing import Optional

from config.settings import settings


class OllamaError(Exception):
    """Error communicating with Ollama."""
    pass


class OllamaClient:
    """
    Client for the Ollama local LLM API.

    Provides async inference for query routing.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None
    ):
        """
        Initialize Ollama client.

        Args:
            host: Ollama server URL (default from settings)
            model: Model name to use (default from settings)
            timeout: Request timeout in seconds (default from settings)
        """
        self.host = host or settings.ollama_host
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout

    async def generate(self, prompt: str, stream: bool = False) -> str:
        """
        Generate a response from the local LLM.

        Args:
            prompt: The prompt to send to the model
            stream: Whether to stream the response (not implemented)

        Returns:
            The model's response text

        Raises:
            OllamaError: If communication fails
        """
        url = f"{self.host}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,  # We want the full response
            "options": {
                "temperature": 0.1,  # Low temperature for consistent routing
                "num_predict": 200,  # Limit output length
            }
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("response", "")

        except httpx.TimeoutException as e:
            raise OllamaError(f"Timeout connecting to Ollama: {e}")
        except httpx.ConnectError as e:
            raise OllamaError(f"Connection error to Ollama: {e}")
        except httpx.HTTPStatusError as e:
            raise OllamaError(f"HTTP error from Ollama: {e}")
        except Exception as e:
            raise OllamaError(f"Error communicating with Ollama: {e}")

    def is_available(self) -> bool:
        """
        Check if Ollama server is available.

        Returns:
            True if Ollama is running and responding
        """
        try:
            response = httpx.get(f"{self.host}", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False
