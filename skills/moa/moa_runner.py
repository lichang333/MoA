import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_ERROR_RE = re.compile(r"^[A-Za-z0-9\-]+ Error:")

def run_worker(func, prompt, key, attempts=2):
    """Call a worker, retrying once on a transient error (timeout, incomplete read)."""
    last = ""
    for _ in range(attempts):
        last = func(prompt, key)
        if not _ERROR_RE.match(last.lstrip()):
            return last
    return last

def load_env():
    paths = [
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.expanduser("~/Desktop/moa_keys.env")
    ]
    for env_path in paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip('"').strip("'")
                            if val and "your_" not in val:
                                os.environ[key] = val
            except Exception as e:
                print(f"Warning: Failed to load env file {env_path}: {e}")

def call_openai(prompt, api_key):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"OpenAI Error: {str(e)}"

def call_anthropic(prompt, api_key):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json"
    }
    data = {
        "model": "claude-3-5-sonnet-20240620",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["content"][0]["text"]
    except Exception as e:
        return f"Anthropic Error: {str(e)}"

def call_glm(prompt, api_key):
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"GLM Error: {str(e)}"

def call_glm52(prompt, api_key, model="glm-5.2"):
    """Strong GLM model used as the second-stage reviewer/critic in --deep (plan B)."""
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"GLM52 Error: {str(e)}"

def call_deepseek(prompt, api_key):
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"DeepSeek Error: {str(e)}"

def call_minimax(prompt, api_key):
    url = "https://api.minimax.io/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "MiniMax-M3",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res["choices"][0]["message"]["content"]
            # MiniMax-M3 leaks its chain-of-thought in a leading <think>...</think>
            # block; strip it so the proposer draft is clean for aggregation.
            content = re.sub(r"^\s*<think>.*?</think>\s*", "", content, flags=re.DOTALL)
            return content.strip()
    except Exception as e:
        return f"MiniMax Error: {str(e)}"

def call_gemini(prompt, api_key):
    # Use the streaming (SSE) endpoint: the buffered generateContent endpoint returns
    # IncompleteRead(0 bytes) on longer/slower answers when an intermediary resets the
    # idle connection. Streaming starts sending sooner, keeping the connection alive.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?alt=sse&key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        chunks = []
        with urllib.request.urlopen(req, timeout=90) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                obj = json.loads(payload)
                try:
                    for p in obj["candidates"][0]["content"]["parts"]:
                        if "text" in p:
                            chunks.append(p["text"])
                except (KeyError, IndexError):
                    continue
        text = "".join(chunks)
        return text if text else "Gemini Error: empty response"
    except Exception as e:
        return f"Gemini Error: {str(e)}"

def aggregate(prompt, worker_responses, aggregator_type, api_key):
    system_prompt = "You are the Aggregator in a Mixture of Agents (MoA) system. Synthesize responses from multiple AI models to produce a single, outstanding, comprehensive final response to the user's prompt. Retain core logical steps, optimize code formatting, and structure it beautifully. Do not mention model names in the final answer unless necessary."
    
    responses_str = ""
    for name, content in worker_responses.items():
        responses_str += f"\n\n--- {name} Response ---\n{content}"

    user_content = f"Original Prompt: {prompt}\n{responses_str}\n\nSynthesized Final Output:"

    if aggregator_type == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        data = {
            "model": "claude-3-5-sonnet-20240620",
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}]
        }
    elif aggregator_type == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        }
    elif aggregator_type == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
        headers = {
            "Content-Type": "application/json"
        }
        data = {
            "contents": [
                {"parts": [{"text": user_content}]}
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            }
        }
    elif aggregator_type == "deepseek":
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        }
    elif aggregator_type == "glm":
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        }
    else:
        return "Error: Unsupported aggregator type."

    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=45) as response:
        res = json.loads(response.read().decode("utf-8"))
        if aggregator_type == "anthropic":
            return res["content"][0]["text"]
        else:
            return res["candidates"][0]["content"]["parts"][0]["text"] if aggregator_type == "gemini" else res["choices"][0]["message"]["content"]

def main():
    args = [a for a in sys.argv[1:]]
    raw_mode = False
    review_mode = False
    if "--raw" in args:
        raw_mode = True
        args.remove("--raw")
    if "--review" in args:
        review_mode = True
        args.remove("--review")
    # --glm52 is a clean alias for talking directly to GLM 5.2 (single turn, no wrapping).
    if "--glm52" in args:
        review_mode = True
        args.remove("--glm52")
    if not args:
        print("Usage: python moa_runner.py [--raw | --review | --glm52] <prompt>")
        sys.exit(1)
    prompt = args[0]

    load_env()

    # --review: single call to the strong GLM 5.2 reviewer (plan B, --deep). Used by the
    # Claude orchestrator to get an adversarial critique of its draft. No proposers run.
    if review_mode:
        zhipu_key = os.environ.get("ZHIPUAI_API_KEY") or os.environ.get("ZHIPU_API_KEY")
        if not zhipu_key:
            print("Error: --review requires ZHIPUAI_API_KEY (GLM 5.2).")
            sys.exit(1)
        review = call_glm52(prompt, zhipu_key)
        print("===MOA_REVIEW_START===")
        print(review)
        print("===MOA_REVIEW_END===")
        return

    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    zhipu_key = os.environ.get("ZHIPUAI_API_KEY") or os.environ.get("ZHIPU_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    minimax_key = os.environ.get("MINIMAX_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    # Select active worker models based on configured keys
    workers = {}
    if openai_key:
        workers["GPT-4o"] = (call_openai, openai_key)
    if anthropic_key:
        workers["Claude-3.5-Sonnet"] = (call_anthropic, anthropic_key)
    if zhipu_key:
        workers["GLM-4"] = (call_glm, zhipu_key)
    if deepseek_key:
        workers["DeepSeek-Chat"] = (call_deepseek, deepseek_key)
    if minimax_key:
        workers["MiniMax-M3"] = (call_minimax, minimax_key)
    if gemini_key:
        workers["Gemini-3.5-Flash"] = (call_gemini, gemini_key)

    if not workers:
        print("Error: No API keys configured. Please add keys to ~/Desktop/moa_keys.env.")
        sys.exit(1)

    print(f"Starting MoA with {len(workers)} worker models: {', '.join(workers.keys())}")
    
    worker_responses = {}
    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        futures = {name: executor.submit(run_worker, func, prompt, key) for name, (func, key) in workers.items()}
        for name, future in futures.items():
            worker_responses[name] = future.result()

    print("\n--- Worker Responses Collected ---")
    for name, content in worker_responses.items():
        print(f"- {name}: {len(content)} characters")

    # --raw: emit worker responses as JSON and stop before any paid aggregation.
    # Used by the Claude Code orchestration mode, where Claude adds its own vote
    # and performs the aggregation itself (no aggregator API call / cost).
    if raw_mode:
        print("\n===MOA_RAW_JSON_START===")
        print(json.dumps(worker_responses, ensure_ascii=False))
        print("===MOA_RAW_JSON_END===")
        return

    # Choose aggregator: Anthropic > OpenAI > Gemini > DeepSeek > GLM
    aggregator_type = None
    aggregator_key = None

    if anthropic_key:
        aggregator_type = "anthropic"
        aggregator_key = anthropic_key
    elif openai_key:
        aggregator_type = "openai"
        aggregator_key = openai_key
    elif gemini_key:
        aggregator_type = "gemini"
        aggregator_key = gemini_key
    elif deepseek_key:
        aggregator_type = "deepseek"
        aggregator_key = deepseek_key
    elif zhipu_key:
        aggregator_type = "glm"
        aggregator_key = zhipu_key

    if not aggregator_key:
        print("Error: No aggregator key available (requires Anthropic, OpenAI, Gemini, DeepSeek, or GLM-4).")
        sys.exit(1)

    print(f"\nAggregating responses using {aggregator_type.upper()}...")
    try:
        final_res = aggregate(prompt, worker_responses, aggregator_type, aggregator_key)
        print("\n--- FINAL SYNTHESIZED RESPONSE ---")
        print(final_res)
    except Exception as e:
        print(f"Error during aggregation: {e}")

if __name__ == "__main__":
    main()
