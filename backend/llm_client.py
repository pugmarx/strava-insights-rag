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
        self.provider = os.getenv("LLM_PROVIDER", "huggingface").lower()
        self.hf_token = os.getenv("HF_TOKEN")
        self.hf_model = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        
        self.hf_client = None
        if self.provider == "huggingface" and self.hf_token:
            try:
                from huggingface_hub import InferenceClient
                self.hf_client = InferenceClient(model=self.hf_model, token=self.hf_token)
            except ImportError:
                print("Warning: huggingface_hub not installed. Run 'pip install huggingface_hub'")

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
            print("HF_TOKEN missing in environment, falling back to Ollama...")
            return self._call_ollama(prompt, system_instruction)

        try:
            if self.hf_client:
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                try:
                    # Try chat completion first
                    response = self.hf_client.chat_completion(
                        messages=messages,
                        max_tokens=600,
                        temperature=0.3
                    )
                    return response.choices[0].message.content
                except Exception:
                    # Fallback to direct text generation
                    full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
                    return self.hf_client.text_generation(
                        full_prompt,
                        max_new_tokens=600,
                        temperature=0.3
                    )
            else:
                # Direct REST API fallback without SDK
                headers = {"Authorization": f"Bearer {self.hf_token}"}
                api_url = f"https://api-inference.huggingface.co/models/{self.hf_model}"
                full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
                payload = {
                    "inputs": full_prompt,
                    "parameters": {"max_new_tokens": 600, "temperature": 0.3, "return_full_text": False}
                }
                res = requests.post(api_url, headers=headers, json=payload, timeout=30)
                res.raise_for_status()
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0].get("generated_text", "")
                return str(data)
        except Exception as e:
            print(f"Hugging Face inference error: {e}. Falling back to Ollama...")
            return self._call_ollama(prompt, system_instruction)

    def _call_groq(self, prompt: str, system_instruction: str = None) -> str:
        """Call Groq Cloud API."""
        if not self.groq_api_key:
            return self._call_ollama(prompt, system_instruction)
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
                "max_tokens": 600
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Groq API error: {e}. Falling back to Ollama...")
            return self._call_ollama(prompt, system_instruction)

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
            return f"Error connecting to AI service (Ollama/Cloud): {e}"
