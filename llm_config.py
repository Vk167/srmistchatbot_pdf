"""
LLM configuration and wrapper for Google Gemini
"""
import time
import logging
import google.generativeai as genai


class GeminiLLM:
    """
    Wrapper for Google Gemini API with streaming and retry support.
    """

    def __init__(
            self,
            api_key: str,
            model_name: str = "models/gemini-2.5-flash",
            max_output_tokens: int = 8192,
            temperature: float = 0.7,
            top_p: float = 0.95,
            max_retries: int = 3
    ):
        """
        Initialize Gemini LLM.

        Args:
            api_key: Google API key
            model_name: Gemini model identifier
            max_output_tokens: Maximum response length
            temperature: Sampling temperature (0-1)
            top_p: Nucleus sampling parameter
            max_retries: Number of retry attempts on failure
        """
        genai.configure(api_key=api_key)

        # Configure generation parameters
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
        )

        self.model = genai.GenerativeModel(
            model_name,
            generation_config=generation_config
        )
        self.max_retries = max_retries

        logging.info(f"Initialized Gemini LLM: {model_name}")

    def __call__(self, prompt: str) -> str:
        """
        Non-streaming mode for compatibility.

        Args:
            prompt: Input prompt

        Returns:
            Generated text response
        """
        if not prompt or not prompt.strip():
            return "Please provide a valid question."

        # Truncate very long prompts
        if len(prompt) > 30000:
            prompt = prompt[:30000] + "...[truncated]"

        for attempt in range(self.max_retries):
            try:
                response = self.model.generate_content(prompt)

                if not response or not getattr(response, "text", "").strip():
                    raise ValueError("Empty response from Gemini")

                return response.text.strip()

            except Exception as e:
                if attempt == self.max_retries - 1:
                    logging.error(
                        f"Gemini API failed after {self.max_retries} attempts: {str(e)}"
                    )
                    return "I'm having trouble processing your request right now. Please try again later."

                # Exponential backoff
                time.sleep(2 ** attempt)

        return "Service temporarily unavailable."

    def stream(self, prompt: str):
        """
        Streaming mode - yields text chunks as they arrive.

        Args:
            prompt: Input prompt

        Yields:
            Text chunks from the model
        """
        if not prompt or not prompt.strip():
            yield "Please provide a valid question."
            return

        # Truncate very long prompts
        if len(prompt) > 30000:
            prompt = prompt[:30000] + "...[truncated]"

        for attempt in range(self.max_retries):
            try:
                response = self.model.generate_content(
                    prompt,
                    stream=True
                )

                # Yield chunks as they arrive
                for chunk in response:
                    if chunk.text:
                        yield chunk.text

                return  # Success, exit retry loop

            except Exception as e:
                if attempt == self.max_retries - 1:
                    logging.error(
                        f"Gemini streaming failed after {self.max_retries} attempts: {str(e)}"
                    )
                    yield "I'm having trouble processing your request right now. Please try again later."
                    return

                # Exponential backoff
                time.sleep(2 ** attempt)

    def invoke(self, prompt: str) -> str:
        """
        LangChain compatibility method.

        Args:
            prompt: Input prompt

        Returns:
            Generated text response
        """
        return self.__call__(prompt)


def setup_gemini_llm(
        api_key: str,
        config: dict = None
) -> GeminiLLM:
    """
    Factory function to create and configure Gemini LLM.

    Args:
        api_key: Google API key
        config: Optional configuration dict with keys:
            - model_name: str
            - max_output_tokens: int
            - temperature: float
            - top_p: float
            - max_retries: int

    Returns:
        Configured GeminiLLM instance

    Raises:
        ValueError: If API key is missing
        RuntimeError: If initialization fails
    """
    if not api_key:
        raise ValueError("Gemini API key is required")

    try:
        # Default configuration
        default_config = {
            "model_name": "models/gemini-2.5-flash",
            "max_output_tokens": 8192,
            "temperature": 0.7,
            "top_p": 0.95,
            "max_retries": 3
        }

        # Merge with provided config
        if config:
            default_config.update(config)

        return GeminiLLM(api_key, **default_config)

    except Exception as e:
        logging.error(f"Gemini setup failed: {str(e)}")
        raise RuntimeError(f"Could not configure Gemini API: {str(e)}")