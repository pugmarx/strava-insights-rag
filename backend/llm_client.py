import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class LLMClient:
    """
    Universal LLM Client supporting Hugging Face Serverless Inference API,
    Groq, OpenAI-compatible APIs, and local Ollama fallback.
    """
    def __init__(self):
        def _clean_env(key, default=""):
            val = os.getenv(key, default)
            if val is None:
                return default
            return val.strip().strip("\"'")

        self.provider = _clean_env("LLM_PROVIDER", "huggingface").lower()
        self.hf_token = _clean_env("HF_TOKEN", "")
        self.hf_model = _clean_env("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
        self.ollama_url = _clean_env("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.ollama_model = _clean_env("OLLAMA_MODEL", "mistral")
        self.groq_api_key = _clean_env("GROQ_API_KEY", "")
        self.groq_model = _clean_env("GROQ_MODEL", "llama-3.3-70b-versatile")
        
        try:
            self.max_tokens = int(_clean_env("MAX_TOKENS", "2048"))
        except ValueError:
            self.max_tokens = 2048
        
        self.hf_client = None
        if self.provider == "huggingface" and self.hf_token:
            try:
                from huggingface_hub import InferenceClient
                self.hf_client = InferenceClient(token=self.hf_token)
            except ImportError:
                pass

    def generate(self, prompt: str, system_instruction: str = None) -> str:
        """Generate a response using the configured provider with automatic fallbacks."""
        if self.provider == "huggingface":
            return self._call_huggingface(prompt, system_instruction)
        elif self.provider == "groq":
            return self._call_groq(prompt, system_instruction)
        else:
            return self._call_ollama(prompt, system_instruction)

    def _call_huggingface(self, prompt: str, system_instruction: str = None) -> str:
        """Call Hugging Face Serverless Inference API."""
        if not self.hf_token:
            return "Error: HF_TOKEN is not set in environment or .env file."

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # Candidate models supported on Hugging Face Serverless Inference
        candidate_models = [self.hf_model]
        for fallback in ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.2-3B-Instruct", "meta-llama/Llama-3.3-70B-Instruct"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        errors = []
        for model_id in candidate_models:
            # 1. Try huggingface_hub client chat completions
            if self.hf_client:
                try:
                    if hasattr(self.hf_client, "chat") and hasattr(self.hf_client.chat, "completions"):
                        resp = self.hf_client.chat.completions.create(
                            model=model_id,
                            messages=messages,
                            max_tokens=self.max_tokens,
                            temperature=0.3
                        )
                        if resp.choices and len(resp.choices) > 0:
                            return resp.choices[0].message.content or ""
                except Exception as e:
                    errors.append(f"{model_id} (chat.completions): {e}")

                try:
                    response = self.hf_client.chat_completion(
                        model=model_id,
                        messages=messages,
                        max_tokens=self.max_tokens,
                        temperature=0.3
                    )
                    if response.choices and len(response.choices) > 0:
                        return response.choices[0].message.content or ""
                except Exception as e:
                    errors.append(f"{model_id} (chat_completion): {e}")

            # 2. Try Hugging Face Router endpoint
            headers = {
                "Authorization": f"Bearer {self.hf_token}",
                "Content-Type": "application/json"
            }
            try:
                router_url = "https://router.huggingface.co/hf-inference/v1/chat/completions"
                payload = {
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3
                }
                res = requests.post(router_url, headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"]
                else:
                    errors.append(f"HF Router {model_id} ({res.status_code}): {res.text}")
            except Exception as e:
                errors.append(f"HF Router {model_id} failed: {e}")

        return f"Error connecting to Hugging Face API: {' | '.join(errors)}"

    def _call_groq(self, prompt: str, system_instruction: str = None) -> str:
        """Call Groq Cloud API."""
        if not self.groq_api_key:
            return "Error: GROQ_API_KEY is not set in environment or .env file."
        try:
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.groq_model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": self.max_tokens
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error connecting to Groq API: {e}"

    def _call_ollama(self, prompt: str, system_instruction: str = None) -> str:
        """Call local Ollama instance."""
        try:
            full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
            payload = {
                "model": self.ollama_model,
                "prompt": full_prompt,
                "stream": False
            }
            response = requests.post(self.ollama_url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("response", "No response received")
        except Exception as e:
            return f"Error connecting to Ollama: {e}"
