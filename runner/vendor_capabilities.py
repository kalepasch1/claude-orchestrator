#!/usr/bin/env python3
"""
vendor_capabilities.py — Unified capability registry for all AI vendors.

Maps each vendor's UNIQUE capabilities so the task router can match task
requirements to vendor strengths. This replaces the old scalar cap/cost
model with a rich capability vector per vendor.

Capabilities tracked:
- text_completion: basic text generation (all vendors)
- code_generation: writing/editing code (all vendors, varying quality)
- vision: image understanding/analysis
- image_generation: creating images from text
- video_generation: creating video from text/images
- web_search: real-time web search grounded in results
- browser_automation: controlling a browser (Claude-in-Chrome via Cowork)
- document_generation: docx/pptx/xlsx creation (Cowork skills)
- function_calling: structured tool use
- long_context: 200k+ token windows
- ultra_long_context: 1M+ token windows
- fast_inference: sub-second latency for simple tasks
- code_execution: sandboxed code running
- real_time_data: access to live/current data feeds
- audio_generation: generating audio/speech
- batch_api: 50%+ cost reduction for non-urgent work

Each vendor entry includes:
- capabilities: set of capability strings
- models: dict of model_name -> {context_window, strengths, cost_per_mtok_in, cost_per_mtok_out}
- api_style: "anthropic" | "openai_compat" | "google" | "custom"
- key_env: env var name for API key
- base_url: API endpoint
- unique_strengths: list of strings describing what this vendor does better than anyone
- limitations: list of strings describing known weaknesses
"""

import os, sys, json, threading, time, re as _re

_lock = threading.Lock()

# ── Vendor Registry ──────────────────────────────────────────────────

VENDORS = {
    "claude": {
        "provider": "anthropic",
        "api_style": "anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com/v1/messages",
        "capabilities": {
            "text_completion", "code_generation", "vision", "function_calling",
            "long_context", "code_execution", "browser_automation",
            "document_generation", "batch_api",
        },
        "models": {
            "claude-sonnet-5": {
                "context_window": 200_000,
                "cost_per_mtok_in": 3.0,
                "cost_per_mtok_out": 15.0,
                "strengths": ["code", "reasoning", "instruction_following"],
                "tier": "mid",
            },
            "claude-opus-4-8": {
                "context_window": 200_000,
                "cost_per_mtok_in": 5.0,
                "cost_per_mtok_out": 25.0,
                "strengths": ["deep_reasoning", "complex_code", "analysis"],
                "tier": "heavy",
            },
            "claude-haiku-4-5": {
                "context_window": 200_000,
                "cost_per_mtok_in": 0.80,
                "cost_per_mtok_out": 4.0,
                "strengths": ["speed", "simple_tasks", "classification"],
                "tier": "fast",
            },
        },
        "unique_strengths": [
            "Best-in-class code generation and reasoning",
            "Browser automation via Claude-in-Chrome (Cowork session)",
            "Document generation skills (docx/pptx/xlsx via Cowork)",
            "Computer use / desktop control",
            "Batch API at 50% cost reduction",
        ],
        "limitations": [
            "No native image generation",
            "No native video generation",
            "No real-time web data (without tools)",
        ],
        "cowork_skills": ["browser_automation", "document_generation", "computer_use"],
    },

    "openai": {
        "provider": "openai",
        "api_style": "openai_compat",
        "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "capabilities": {
            "text_completion", "code_generation", "vision", "function_calling",
            "long_context", "image_generation", "audio_generation",
            "web_search", "code_execution",
        },
        "models": {
            "gpt-5.5": {
                "context_window": 200_000,
                "cost_per_mtok_in": 5.0,
                "cost_per_mtok_out": 30.0,
                "strengths": ["reasoning", "multimodal", "code"],
                "tier": "heavy",
            },
            "gpt-5.4-mini": {
                "context_window": 128_000,
                "cost_per_mtok_in": 0.75,
                "cost_per_mtok_out": 4.50,
                "strengths": ["speed", "cost", "general"],
                "tier": "mid",
            },
            "gpt-5.4-nano": {
                "context_window": 128_000,
                "cost_per_mtok_in": 0.20,
                "cost_per_mtok_out": 1.25,
                "strengths": ["ultra_fast", "cost", "simple_tasks"],
                "tier": "fast",
            },
            "gpt-5.6-sol": {
                "context_window": 200_000,
                "cost_per_mtok_in": 5.0,
                "cost_per_mtok_out": 30.0,
                "strengths": ["frontier_reasoning", "multimodal"],
                "tier": "frontier",
            },
            "o4-mini": {
                "context_window": 200_000,
                "cost_per_mtok_in": 1.1,
                "cost_per_mtok_out": 4.4,
                "strengths": ["reasoning", "math", "cost_efficient"],
                "tier": "mid",
            },
        },
        "unique_strengths": [
            "Native image generation (DALL-E)",
            "Native audio/speech generation and transcription",
            "Built-in web search (ChatGPT search)",
            "Code Interpreter sandbox",
            "Broadest third-party ecosystem",
        ],
        "limitations": [
            "Sora video generation being discontinued Sept 2026",
            "Higher cost than DeepSeek/Gemini for comparable quality",
        ],
        "cowork_skills": [],
    },

    "deepseek": {
        "provider": "deepseek",
        "api_style": "openai_compat",
        "key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "capabilities": {
            "text_completion", "code_generation", "function_calling",
            "long_context",
        },
        "models": {
            "deepseek-v4-flash": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 0.14,
                "cost_per_mtok_out": 0.28,
                "strengths": ["code", "reasoning", "cost_efficiency"],
                "tier": "mid",
            },
            "deepseek-v4-pro": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 0.435,
                "cost_per_mtok_out": 0.87,
                "strengths": ["deep_reasoning", "math", "complex_code"],
                "tier": "heavy",
            },
        },
        "unique_strengths": [
            "Extremely low cost (10-50x cheaper than Claude/GPT)",
            "Strong code generation competitive with top models",
            "Deep reasoning via deepseek-reasoner at fraction of cost",
        ],
        "limitations": [
            "No vision capability",
            "No image/video generation",
            "No web search",
            "Chinese data residency concerns for some use cases",
        ],
        "cowork_skills": [],
    },

    "gemini": {
        "provider": "google",
        "api_style": "google",
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "capabilities": {
            "text_completion", "code_generation", "vision", "function_calling",
            "long_context", "ultra_long_context", "web_search",
            "image_generation", "video_generation", "audio_generation",
            "code_execution",
        },
        "models": {
            "gemini-3.1-pro": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 2.0,
                "cost_per_mtok_out": 12.0,
                "strengths": ["reasoning", "multimodal", "ultra_long_context"],
                "tier": "heavy",
            },
            "gemini-3.5-flash": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 1.50,
                "cost_per_mtok_out": 9.0,
                "strengths": ["speed", "multimodal", "long_context"],
                "tier": "mid",
            },
            "gemini-3-flash": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 0.50,
                "cost_per_mtok_out": 3.0,
                "strengths": ["speed", "cost", "long_context"],
                "tier": "fast",
            },
            "gemini-2.5-pro": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 1.25,
                "cost_per_mtok_out": 10.0,
                "strengths": ["ultra_long_context", "reasoning"],
                "tier": "heavy",
            },
        },
        "unique_strengths": [
            "1M token context window (largest available)",
            "Native video generation via Veo 3 (Vertex AI)",
            "Native image generation via Imagen",
            "Built-in Google Search grounding",
            "Native code execution sandbox",
            "Generous free tier",
        ],
        "limitations": [
            "Transient 503 errors requiring retry cascades",
            "Veo 3 requires Vertex AI access (separate from Gemini API)",
        ],
        "cowork_skills": [],
    },

    "groq": {
        "provider": "groq",
        "api_style": "openai_compat",
        "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "capabilities": {
            "text_completion", "code_generation", "function_calling",
            "fast_inference", "vision",
        },
        "models": {
            "llama-3.3-70b-versatile": {
                "context_window": 128_000,
                "cost_per_mtok_in": 0.59,
                "cost_per_mtok_out": 0.79,
                "strengths": ["speed", "latency", "general"],
                "tier": "mid",
            },
            "llama-3.1-8b-instant": {
                "context_window": 128_000,
                "cost_per_mtok_in": 0.05,
                "cost_per_mtok_out": 0.08,
                "strengths": ["ultra_fast", "cost", "simple_tasks"],
                "tier": "fast",
            },
        },
        "unique_strengths": [
            "10x faster inference than GPU-based providers (custom LPU silicon)",
            "500+ tok/s on 8B, 250+ tok/s on 70B models",
            "Generous free tier (30 RPM, no credit card)",
            "Ideal for latency-sensitive pipelines (triage, classification, routing)",
        ],
        "limitations": [
            "Open-source models only (no proprietary frontier models)",
            "No image/video generation",
            "No web search",
            "Rate limits on free tier",
        ],
        "cowork_skills": [],
    },

    "xai": {
        "provider": "xai",
        "api_style": "openai_compat",
        "key_env": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1/chat/completions",
        "capabilities": {
            "text_completion", "code_generation", "vision", "function_calling",
            "long_context", "ultra_long_context", "image_generation",
            "video_generation", "web_search", "real_time_data", "batch_api",
        },
        "models": {
            "grok-4.5": {
                "context_window": 500_000,
                "cost_per_mtok_in": 2.0,
                "cost_per_mtok_out": 6.0,
                "strengths": ["frontier_reasoning", "multimodal"],
                "tier": "frontier",
            },
            "grok-4.3": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 1.25,
                "cost_per_mtok_out": 2.50,
                "strengths": ["reasoning", "real_time_data", "multimodal"],
                "tier": "heavy",
            },
            "grok-4.20": {
                "context_window": 1_000_000,
                "cost_per_mtok_in": 1.25,
                "cost_per_mtok_out": 2.50,
                "strengths": ["reasoning", "non_reasoning", "multi_agent"],
                "tier": "heavy",
            },
            "grok-build-0.1": {
                "context_window": 256_000,
                "cost_per_mtok_in": 1.00,
                "cost_per_mtok_out": 2.00,
                "strengths": ["code", "coding_tasks"],
                "tier": "mid",
            },
        },
        "unique_strengths": [
            "Real-time X/Twitter data access for current events",
            "Native image generation via FLUX ($0.02/image)",
            "Image-to-video conversion ($0.05/sec)",
            "DeepSearch multi-hop web research agent",
            "Batch API at 50% cost reduction on all token costs",
            "2M token context on some models",
        ],
        "limitations": [
            "Newer API, less battle-tested in production",
            "X/Twitter data access is unique but niche",
        ],
        "cowork_skills": [],
    },

    "bfl": {
        "provider": "bfl",
        "api_style": "custom",
        "key_env": "BFL_API_KEY",
        "base_url": "https://api.bfl.ml/v1",
        "capabilities": {
            "image_generation", "image_editing",
        },
        "models": {
            "flux-2-pro": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "cost_per_image": 0.03,
                "strengths": ["photorealism", "prompt_adherence", "image_quality"],
                "tier": "heavy",
            },
            "flux-2-dev": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "cost_per_image": 0.01,
                "strengths": ["speed", "cost", "open_weights"],
                "tier": "fast",
            },
        },
        "unique_strengths": [
            "FLUX.2 Pro — current photorealism leader ($0.03/image)",
            "Best prompt adherence for image generation",
            "Pay-per-image, no subscription required",
            "Megapixel-based pricing scales with resolution",
        ],
        "limitations": [
            "Image generation only — no text/code/video",
            "No text completion capabilities",
        ],
        "cowork_skills": [],
    },

    "ideogram": {
        "provider": "ideogram",
        "api_style": "custom",
        "key_env": "IDEOGRAM_API_KEY",
        "base_url": "https://api.ideogram.ai/v1",
        "capabilities": {
            "image_generation", "text_in_image",
        },
        "models": {
            "ideogram-3.0": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "cost_per_image": 0.04,
                "strengths": ["text_rendering", "typography", "logos"],
                "tier": "heavy",
            },
        },
        "unique_strengths": [
            "~92% text accuracy in images (vs ~30-40% for others)",
            "Best-in-class for logos, banners, and typography-heavy work",
            "Purpose-built for text-in-image generation",
        ],
        "limitations": [
            "Image generation only",
            "Higher cost than FLUX for non-text images",
        ],
        "cowork_skills": [],
    },

    "elevenlabs": {
        "provider": "elevenlabs",
        "api_style": "custom",
        "key_env": "ELEVENLABS_API_KEY",
        "base_url": "https://api.elevenlabs.io/v1",
        "capabilities": {
            "audio_generation", "voice_cloning", "text_to_speech",
        },
        "models": {
            "eleven-multilingual-v2": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "strengths": ["voice_quality", "multilingual", "cloning"],
                "tier": "heavy",
            },
            "eleven-flash": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "strengths": ["speed", "cost", "low_latency"],
                "tier": "fast",
            },
        },
        "unique_strengths": [
            "Industry-leading text-to-speech quality",
            "Professional voice cloning from samples",
            "29+ languages supported",
            "Real-time streaming TTS for voice agents",
        ],
        "limitations": [
            "Audio/voice only — no text/code/image",
            "API pricing separate from consumer plans",
        ],
        "cowork_skills": [],
    },

    "kling": {
        "provider": "kling",
        "api_style": "custom",
        "key_env": "KLING_API_KEY",
        "base_url": "https://api.klingai.com/v1",
        "capabilities": {
            "video_generation", "image_to_video",
        },
        "models": {
            "kling-3.0": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "cost_per_second": 0.075,
                "strengths": ["cinematic_realism", "motion_quality", "cost"],
                "tier": "mid",
            },
        },
        "unique_strengths": [
            "Best value video generation ($0.075/sec — 65% cheaper than Sora was)",
            "Cinematic realism and motion quality",
            "Motion control support",
            "Failed generations not charged",
        ],
        "limitations": [
            "Video generation only",
            "API requires prepaid resource packages",
        ],
        "cowork_skills": [],
    },

    "meshy": {
        "provider": "meshy",
        "api_style": "custom",
        "key_env": "MESHY_API_KEY",
        "base_url": "https://api.meshy.ai/v2",
        "capabilities": {
            "3d_generation", "text_to_3d", "image_to_3d",
        },
        "models": {
            "meshy-4": {
                "context_window": 0,
                "cost_per_mtok_in": 0,
                "cost_per_mtok_out": 0,
                "cost_per_generation": 0.20,
                "strengths": ["3d_printing", "textured_models", "speed"],
                "tier": "mid",
            },
        },
        "unique_strengths": [
            "Text-to-3D and image-to-3D model generation",
            "Best for 3D printing workflows",
            "Fully textured output models",
            "API access from $10/mo Pro plan",
        ],
        "limitations": [
            "3D generation only",
            "Credit-based pricing",
        ],
        "cowork_skills": [],
    },

    "local": {
        "provider": "ollama",
        "api_style": "openai_compat",
        "key_env": "",  # no key needed
        "base_url": "http://localhost:11434/v1/chat/completions",
        "capabilities": {
            "text_completion", "code_generation", "vision",
            "fast_inference",
        },
        "models": {},  # dynamically discovered via ollama_catalog.py
        "unique_strengths": [
            "Zero cost per token",
            "Full data privacy (no data leaves machine)",
            "No rate limits",
            "Works offline",
        ],
        "limitations": [
            "Quality depends on hardware and model size",
            "RAM-constrained (44GB resident memory incident documented)",
            "No image/video generation",
            "No web search",
        ],
        "cowork_skills": [],
    },
}

# ── Capability → Vendor index ────────────────────────────────────────

_capability_index = {}  # capability_name -> [vendor_names]
_vendor_index_built = False


def _build_index():
    global _capability_index, _vendor_index_built
    with _lock:
        _capability_index = {}
        try:
            for vname, vinfo in VENDORS.items():
                for cap in vinfo.get("capabilities", set()):
                    _capability_index.setdefault(cap, []).append(vname)
        except Exception:
            _capability_index = {}
        _vendor_index_built = True


def vendors_with_capability(capability):
    """Return list of vendor names that have a given capability."""
    try:
        if not _vendor_index_built:
            _build_index()
        return list(_capability_index.get(capability, []))
    except Exception:
        return []


def vendor_has_capability(vendor, capability):
    """Check if a specific vendor has a capability."""
    try:
        v = VENDORS.get(vendor)
        if not v:
            return False
        return capability in v.get("capabilities", set())
    except Exception:
        return False


def all_capabilities():
    """Return set of all known capabilities across all vendors."""
    try:
        if not _vendor_index_built:
            _build_index()
        return set(_capability_index.keys())
    except Exception:
        return set()


def vendor_info(vendor):
    """Return full vendor dict or empty dict if unknown."""
    try:
        return dict(VENDORS.get(vendor, {}))
    except Exception:
        return {}


def unique_capabilities(vendor):
    """Return capabilities this vendor has that NO other vendor has."""
    try:
        if not _vendor_index_built:
            _build_index()
        v = VENDORS.get(vendor)
        if not v:
            return set()
        unique = set()
        for cap in v.get("capabilities", set()):
            providers = _capability_index.get(cap, [])
            if len(providers) == 1 and providers[0] == vendor:
                unique.add(cap)
        return unique
    except Exception:
        return set()


# ── Task capability detection ────────────────────────────────────────

# Keywords/patterns that signal a task needs a specific capability
_CAPABILITY_SIGNALS = {
    "image_generation": [
        r"(?i)\b(generate|create|make|draw|design)\b.*\b(image|picture|photo|illustration|graphic|logo|icon|banner)\b",
        r"(?i)\b(image|picture|photo)\b.*\b(generat|creat|mak)\b",
        r"(?i)\bdall-?e\b", r"(?i)\bflux\b", r"(?i)\bimagen\b",
    ],
    "video_generation": [
        r"(?i)\b(generate|create|make|produce)\b.*\b(video|clip|animation|movie)\b",
        r"(?i)\b(video|clip|animation)\b.*\b(generat|creat|mak|produc)\b",
        r"(?i)\bveo\b", r"(?i)\bsora\b", r"(?i)\brunway\b",
    ],
    "browser_automation": [
        r"(?i)\b(browse|scrape|crawl|navigate|click|interact)\b.*\b(web\w*|page|site|url|browser)\b",
        r"(?i)\b(web\w*|page|site|url|browser)\b.*\b(browse|scrape|crawl|navigate|click|interact|verify|check|test)\b",
        r"(?i)\bchrome\b.*\b(automat|control|driv)\b",
        r"(?i)\bvisual\s+(verification|check|test|inspect)\b",
        r"(?i)\bweb\s+interaction\b",
        r"(?i)\bselenium\b", r"(?i)\bplaywright\b",
        r"(?i)\bverify\b.*\b(deploy|web\w*|page|site)\b",
    ],
    "document_generation": [
        r"(?i)\b(create|generate|make|build|produce|write)\b.*\b(docx|pptx|xlsx|word\s+doc|presentation|spreadsheet|slide\s+deck|powerpoint|excel)\b",
        r"(?i)\.(docx|pptx|xlsx|dotx|potx|xltx)\b",
    ],
    "vision": [
        r"(?i)\b(analyz|describ|read|extract|ocr|understand|interpret)\b.*\b(image|screenshot|photo|picture|diagram|chart|pdf)\b",
        r"(?i)\b(image|screenshot|photo|picture)\b.*\b(analys|recogni|detect|classif)\b",
    ],
    "web_search": [
        r"(?i)\b(search|look\s+up|find|research)\b.*\b(web|internet|online|current|latest|recent|news)\b",
        r"(?i)\breal.?time\b.*\b(data|info|news)\b",
        r"(?i)\bcurrent\s+(events?|news|price|status)\b",
    ],
    "ultra_long_context": [
        r"(?i)\b(entire|full|whole|complete)\s+(codebase|repo|repository|book|document)\b",
        r"(?i)\b(analyz|review|read)\b.*\b(large|huge|massive|entire)\b",
        r"(?i)\b(100k|200k|500k|1m|million)\s*tokens?\b",
    ],
    "fast_inference": [
        r"(?i)\b(fast|quick|instant|real.?time|low.?latency)\b.*\b(response|answer|classif|triage|route|result|inference)\b",
        r"(?i)\b(response|answer|classif|triage|route|result|inference)\b.*\b(fast|quick|instant|real.?time|low.?latency)\b",
        r"(?i)\btriage\b", r"(?i)\bclassif\b",
        r"(?i)\bneed\w*\s+(result|answer|response)s?\s+(fast|quick)\b",
    ],
    "code_execution": [
        r"(?i)\b(run|execute|test|eval)\b.*\b(code|script|program|snippet)\b",
        r"(?i)\bsandbox\b",
    ],
    "real_time_data": [
        r"(?i)\b(twitter|x\.com|tweet|trending|social\s+media)\b",
        r"(?i)\breal.?time\s+(feed|data|stream)\b",
    ],
    "audio_generation": [
        r"(?i)\b(generate|create|make|synthesize)\b.*\b(audio|speech|voice|sound|music)\b",
        r"(?i)\btext.?to.?speech\b", r"(?i)\btts\b",
    ],
    "batch_api": [
        r"(?i)\bbatch\b.*\b(process|run|execut)\b",
        r"(?i)\bnon.?urgent\b",
        r"(?i)\bbulk\s+(process|generat|creat)\b",
    ],
    "3d_generation": [
        r"(?i)\b(generate|create|make|build|model)\b.*\b(3d|three.?d|mesh|3D)\b",
        r"(?i)\b3d\b.*\b(model|asset|object|scene|print)\b",
        r"(?i)\b(text|image).?to.?3d\b",
        r"(?i)\b(mesh|obj|glb|gltf|fbx|stl)\b",
    ],
    "text_in_image": [
        r"(?i)\b(text|typography|logo|banner|poster|sign)\b.*\b(image|graphic|design)\b",
        r"(?i)\b(image|graphic|design)\b.*\b(text|typography|logo|lettering)\b",
        r"(?i)\blogo\s+(design|generat|creat)\b",
    ],
    "voice_cloning": [
        r"(?i)\b(clone|copy|replicate|mimic)\b.*\b(voice|speech|accent)\b",
        r"(?i)\bvoice\s+clon\b",
        r"(?i)\bcustom\s+voice\b",
    ],
    "text_to_speech": [
        r"(?i)\btext.?to.?speech\b",
        r"(?i)\btts\b",
        r"(?i)\b(narrat|voiceover|read\s+aloud|speak)\b.*\b(text|script|document)\b",
    ],
    "image_to_video": [
        r"(?i)\b(image|photo|picture|still)\b.*\b(to|into)\b.*\b(video|animation|motion)\b",
        r"(?i)\banimat\w*\b.*\b(image|photo|picture)\b",
    ],
    "image_editing": [
        r"(?i)\b(edit|modify|alter|retouch|inpaint|outpaint)\b.*\b(image|photo|picture)\b",
        r"(?i)\b(image|photo|picture)\b.*\b(edit|modif|alter|retouch)\b",
        r"(?i)\binpaint\b", r"(?i)\boutpaint\b",
    ],
}


def detect_required_capabilities(task):
    """
    Analyze a task dict and return set of capabilities it requires.

    Looks at task fields: slug, title, description, prompt, needs, kind.
    Always includes 'text_completion' and 'code_generation' as baseline.
    Fail-soft: returns baseline set on any error.
    """
    required = {"text_completion", "code_generation"}

    try:
        if not isinstance(task, dict):
            return required

        # Gather all text fields to scan
        text_parts = []
        for field in ("slug", "title", "description", "prompt", "needs", "kind", "objective"):
            val = task.get(field, "")
            if isinstance(val, str) and val:
                text_parts.append(val)

        combined = " ".join(text_parts)
        if not combined.strip():
            return required

        for cap, patterns in _CAPABILITY_SIGNALS.items():
            for pattern in patterns:
                try:
                    if _re.search(pattern, combined):
                        required.add(cap)
                        break
                except Exception:
                    continue

        # Explicit capability tags in task metadata
        explicit = task.get("required_capabilities", [])
        if isinstance(explicit, list):
            required.update(explicit)
        elif isinstance(explicit, str):
            required.update(c.strip() for c in explicit.split(",") if c.strip())

        return required
    except Exception:
        return required


def best_vendors_for_task(task, exclude=None):
    """
    Given a task dict, return ranked list of (vendor, score, reason) tuples.

    Score considers: capability coverage, cost efficiency, unique strengths.
    Higher score = better fit. Fail-soft: returns [] on error.
    """
    try:
        if not _vendor_index_built:
            _build_index()

        exclude = set(exclude or [])
        required = detect_required_capabilities(task)

        results = []
        for vname, vinfo in VENDORS.items():
            if vname in exclude:
                continue

            # Check API key availability (skip vendors we can't reach)
            key_env = vinfo.get("key_env", "")
            if key_env and not os.environ.get(key_env):
                continue

            vcaps = vinfo.get("capabilities", set())
            covered = required & vcaps
            missing = required - vcaps

            if not covered:
                continue

            # Base score: coverage ratio
            coverage = len(covered) / max(len(required), 1)

            # Bonus for unique capabilities that match
            unique_bonus = 0
            unique_caps = unique_capabilities(vname)
            matched_unique = required & unique_caps
            if matched_unique:
                unique_bonus = 0.3 * len(matched_unique)

            # Cost efficiency bonus (cheaper = higher bonus)
            models = vinfo.get("models", {})
            if models:
                min_cost = min(m.get("cost_per_mtok_in", 999) for m in models.values())
                cost_bonus = max(0, 0.2 * (1 - min_cost / 15.0))  # normalize against Opus pricing
            else:
                cost_bonus = 0.15  # local/free

            # Penalty for missing required capabilities
            missing_penalty = 0.5 * len(missing) / max(len(required), 1)

            score = coverage + unique_bonus + cost_bonus - missing_penalty

            reason_parts = []
            if coverage == 1.0:
                reason_parts.append("full capability coverage")
            else:
                reason_parts.append(f"{len(covered)}/{len(required)} capabilities")
                if missing:
                    reason_parts.append(f"missing: {', '.join(sorted(missing))}")
            if matched_unique:
                reason_parts.append(f"unique: {', '.join(sorted(matched_unique))}")

            results.append((vname, round(score, 3), "; ".join(reason_parts)))

        results.sort(key=lambda x: -x[1])
        return results
    except Exception:
        return []


def best_vendor_for_capability(capability, prefer_cost=True):
    """
    Return the single best vendor for a specific capability.
    If prefer_cost=True, picks cheapest. Otherwise picks highest quality.
    Fail-soft: returns None on error.
    """
    try:
        candidates = vendors_with_capability(capability)
        if not candidates:
            return None

        # Filter to available (have API key configured)
        available = []
        for v in candidates:
            key_env = VENDORS[v].get("key_env", "")
            if not key_env or os.environ.get(key_env):
                available.append(v)

        if not available:
            return None
        if len(available) == 1:
            return available[0]

        if prefer_cost:
            def _min_cost(v):
                models = VENDORS[v].get("models", {})
                if not models:
                    return 0  # free/local
                return min(m.get("cost_per_mtok_in", 999) for m in models.values())
            available.sort(key=_min_cost)
        else:
            # Prefer by unique strength count for quality
            available.sort(key=lambda v: -len(VENDORS[v].get("unique_strengths", [])))

        return available[0]
    except Exception:
        return None


def requires_cowork_session(task):
    """
    Return True if the task requires capabilities only available via Cowork session.
    Returns (bool, list_of_cowork_capabilities_needed). Fail-soft: returns (False, []) on error.
    """
    try:
        required = detect_required_capabilities(task)
        cowork_only = {"browser_automation", "document_generation"}
        needed = required & cowork_only
        return (bool(needed), sorted(needed))
    except Exception:
        return (False, [])


def suggest_model(vendor, task):
    """
    Given a vendor and task, suggest the best model from that vendor.
    Returns (model_name, reason) or (None, "").
    """
    try:
        v = VENDORS.get(vendor)
        if not v or not v.get("models"):
            return (None, "")

        required = detect_required_capabilities(task)

        # Determine tier needed
        tier_needed = "fast"
        heavy_signals = {"ultra_long_context", "video_generation", "image_generation"}
        mid_signals = {"vision", "web_search", "code_execution", "function_calling"}

        if required & heavy_signals:
            tier_needed = "heavy"
        elif required & mid_signals:
            tier_needed = "mid"

        # Match by tier
        models = v["models"]
        tier_matches = {k: m for k, m in models.items() if m.get("tier") == tier_needed}

        if tier_matches:
            # Pick cheapest within tier
            best = min(tier_matches.items(), key=lambda x: x[1].get("cost_per_mtok_in", 999))
            return (best[0], f"tier={tier_needed}")

        # Fallback: cheapest model
        best = min(models.items(), key=lambda x: x[1].get("cost_per_mtok_in", 999))
        return (best[0], f"fallback (no {tier_needed} tier)")
    except Exception:
        return (None, "")


def available_vendors():
    """Return list of vendor names that have their API key configured (or are local). Fail-soft: [] on error."""
    try:
        result = []
        for vname, vinfo in VENDORS.items():
            key_env = vinfo.get("key_env", "")
            if not key_env or os.environ.get(key_env):
                result.append(vname)
        return result
    except Exception:
        return []


def capability_matrix():
    """
    Return dict of {vendor: {capability: bool}} for all vendors and capabilities.
    Useful for dashboards and diagnostics. Fail-soft: returns {} on error.
    """
    try:
        all_caps = sorted(all_capabilities())
        matrix = {}
        for vname, vinfo in VENDORS.items():
            vcaps = vinfo.get("capabilities", set())
            matrix[vname] = {cap: cap in vcaps for cap in all_caps}
        return matrix
    except Exception:
        return {}


def stats():
    """Return summary stats for operator dashboards. Fail-soft: returns {} on error."""
    try:
        avail = available_vendors()
        all_caps = all_capabilities()
        return {
            "total_vendors": len(VENDORS),
            "available_vendors": len(avail),
            "available": avail,
            "total_capabilities": len(all_caps),
            "capabilities": sorted(all_caps),
            "coverage_by_capability": {
                cap: len(vendors_with_capability(cap))
                for cap in sorted(all_caps)
            },
        }
    except Exception:
        return {}


# ── Module-level singleton wrapper ───────────────────────────────────
#
# Registry state above is process-global (VENDORS, _capability_index) and
# guarded by _lock for index construction. The functions above already act
# as the module-level API; this class exists to match the codebase's
# singleton-with-delegating-functions convention for callers that prefer
# an object handle (e.g. tests, dependency injection).

class _VendorCapabilityRegistry:
    """Thread-safe singleton wrapper around the module-level registry functions."""

    def vendors_with_capability(self, capability):
        return vendors_with_capability(capability)

    def vendor_has_capability(self, vendor, capability):
        return vendor_has_capability(vendor, capability)

    def all_capabilities(self):
        return all_capabilities()

    def vendor_info(self, vendor):
        return vendor_info(vendor)

    def unique_capabilities(self, vendor):
        return unique_capabilities(vendor)

    def detect_required_capabilities(self, task):
        return detect_required_capabilities(task)

    def best_vendors_for_task(self, task, exclude=None):
        return best_vendors_for_task(task, exclude=exclude)

    def best_vendor_for_capability(self, capability, prefer_cost=True):
        return best_vendor_for_capability(capability, prefer_cost=prefer_cost)

    def requires_cowork_session(self, task):
        return requires_cowork_session(task)

    def suggest_model(self, vendor, task):
        return suggest_model(vendor, task)

    def available_vendors(self):
        return available_vendors()

    def capability_matrix(self):
        return capability_matrix()

    def stats(self):
        return stats()


_registry = None
_registry_lock = threading.Lock()


def _get_registry():
    """Return the module-level singleton registry instance, creating it if needed."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = _VendorCapabilityRegistry()
    return _registry
