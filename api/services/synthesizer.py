"""
Synthesizer service for LifeOS.

Handles Claude API calls for RAG synthesis.
"""
import logging
from typing import Optional
import anthropic

from config.settings import settings
from api.services.model_selector import get_claude_model_name

logger = logging.getLogger(__name__)

# Default model tier
DEFAULT_MODEL_TIER = "sonnet"


class Synthesizer:
    """Service for synthesizing answers using Claude."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize synthesizer.

        Args:
            api_key: Anthropic API key (defaults to settings)
        """
        self.api_key = api_key or settings.anthropic_api_key
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        """Lazy-load the Anthropic client."""
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def synthesize(
        self,
        prompt: str,
        max_tokens: int = 1024,
        model: str = None,
        model_tier: str = None
    ) -> str:
        """
        Generate a synthesized response using Claude.

        Args:
            prompt: The full prompt including context and question
            max_tokens: Maximum response length
            model: Full Claude model name (overrides model_tier)
            model_tier: Model tier ("haiku", "sonnet", "opus")

        Returns:
            Generated response text

        Raises:
            Exception: If API call fails
        """
        # Resolve model name: explicit model > model_tier > default
        if model is None:
            tier = model_tier or DEFAULT_MODEL_TIER
            model = get_claude_model_name(tier)

        logger.debug(f"Using model: {model}")

        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.content[0].text
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Synthesizer error: {e}")
            raise

    async def stream_response(
        self,
        prompt: str,
        max_tokens: int = 1024,
        model: str = None,
        model_tier: str = None
    ):
        """
        Stream a response from Claude.

        Args:
            prompt: The full prompt including context and question
            max_tokens: Maximum response length
            model: Full Claude model name (overrides model_tier)
            model_tier: Model tier ("haiku", "sonnet", "opus")

        Yields:
            Text chunks as they arrive
        """
        # Resolve model name: explicit model > model_tier > default
        if model is None:
            tier = model_tier or DEFAULT_MODEL_TIER
            model = get_claude_model_name(tier)

        logger.debug(f"Streaming with model: {model}")

        try:
            with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except anthropic.APIError as e:
            logger.error(f"Claude API streaming error: {e}")
            raise
        except Exception as e:
            logger.error(f"Synthesizer streaming error: {e}")
            raise

    async def get_response(
        self,
        prompt: str,
        max_tokens: int = 2048,
        model: str = None,
        model_tier: str = None
    ) -> str:
        """
        Get a complete response from Claude (async wrapper).

        Args:
            prompt: The full prompt
            max_tokens: Maximum response length
            model: Full Claude model name (overrides model_tier)
            model_tier: Model tier ("haiku", "sonnet", "opus")

        Returns:
            Generated response text
        """
        return self.synthesize(prompt, max_tokens, model, model_tier)


# System prompt for RAG synthesis
SYSTEM_CONTEXT = """You are LifeOS, a personal knowledge assistant for Nathan.
You have access to his Obsidian vault containing notes, meeting transcripts, and personal documents.

Your responses should be:
- Concise and direct (Paul Graham style - no fluff)
- Grounded in the provided context
- Citing sources when making claims

When answering:
1. Use only information from the provided context
2. If the context doesn't contain enough information, say so
3. Reference source files naturally (e.g., "According to the Budget Review notes...")
4. Extract and highlight action items if relevant
5. Be specific with dates, names, and numbers when available

Format:
- Keep answers focused and brief
- Use bullet points for lists
- Include relevant quotes when helpful
- End with sources list if multiple files referenced"""


def construct_prompt(
    question: str,
    chunks: list[dict],
    conversation_history: list = None
) -> str:
    """
    Construct the full prompt for Claude.

    Args:
        question: User's question
        chunks: Retrieved context chunks with metadata
        conversation_history: Optional list of previous messages for context

    Returns:
        Formatted prompt string
    """
    # Build context section
    if chunks:
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            file_name = chunk.get("file_name", "Unknown")
            content = chunk.get("content", "")
            context_parts.append(f"[Source {i}: {file_name}]\n{content}")

        context = "\n\n---\n\n".join(context_parts)
    else:
        context = "(No relevant context found in the vault)"

    # Build conversation history section
    history_section = ""
    if conversation_history:
        from api.services.conversation_store import format_conversation_history
        formatted_history = format_conversation_history(conversation_history)
        if formatted_history:
            history_section = f"""## Conversation History

{formatted_history}

---

"""

    # Construct full prompt
    prompt = f"""{SYSTEM_CONTEXT}

## Context from Vault

{context}

{history_section}## Question

{question}

## Instructions

Answer the question based on the context above. Cite your sources by referencing the file names. If the context doesn't contain enough information to fully answer, acknowledge what's missing. If this is a follow-up question, consider the conversation history for context."""

    return prompt


# Singleton instance
_synthesizer: Synthesizer | None = None


def get_synthesizer() -> Synthesizer:
    """Get or create synthesizer singleton."""
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = Synthesizer()
    return _synthesizer
