import os
import json
import urllib.request
import urllib.error
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Read from the environment, never committed. A hardcoded key here was
# caught by GitHub push protection on the first publish attempt; it had
# been sitting in the repository history since "Baseline before brain
# rewrite". Set BEDROCK_KEY in your shell before running this.
BEDROCK_KEY = os.environ.get("BEDROCK_KEY", "")
if not BEDROCK_KEY:
    raise SystemExit("set BEDROCK_KEY in the environment to run this script")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "expert_feedback")
os.makedirs(OUTPUT_DIR, exist_ok=True)

PROMPT = """You are a Principal AI / Reinforcement Learning Architect and Expert Game Bot Engineer.
We are building HastyCR, an autonomous AI bot playing Supercell's Clash Royale live on ladder via an Android emulator (MuMu Player) with the ultimate goal of achieving state-of-the-art competitive play via Reinforcement Learning (RL).

### Current System Architecture:
1. Environment & Actuation:
   - MuMu Player Android emulator (1080x1920 portrait) controlled via ADB (`exec-out screencap` for frames @ ~10 FPS, `input tap <x> <y>` for card deployment).
   - Logical coordinate space: 18x32 top-down tile grid (y < 16 enemy half, y >= 16 ally half), mapped to pixels via `grid_to_mumu()`.
2. Deck: Classic Hog 2.6 Cycle (Hog Rider, Musketeer, Cannon, Fireball, The Log, Ice Golem, Ice Spirit, Skeletons).
3. Perception:
   - ClashRoyaleBuildABot (ONNX runtime) detecting screen state, elixir (0-10), 4 hand cards + 1 queued next card, ally/enemy tower HPs, unit bounding boxes and tile positions.
4. Policy Model:
   - KataCR (StARformer_3L: 3-layer Spatial-Temporal Autoregressive Transformer for offline RL).
   - Checkpoint: Trained offline on simulated games against KataCR's naive scripted Golem bot. Emits action tuple: (card_slot, x, y, delay).
5. Strategy Layer & Policy Shims (`scripts/policy_shims.py`):
   - Rules overriding the model: forces Hog at bridge when affordable and safe, alternates lanes to avoid predictable counter-pushes, clamps Cannon strictly into defensive pocket (x 8-10, y 20-22), retargets spells onto densest enemy unit clusters, swaps low-tier chip cards (Skeletons/Ice Spirit) for real defenders (Musketeer/Cannon/Ice Golem) under pressure (>=2 enemies or any enemy y >= 20), fireballs enemy towers below 0.18 HP.
6. Safety Layer:
   - `battle_guard` and `pre_card_guard` gate every card tap on live battle verification.
   - `popup_guard.py` dismisses Supercell popups strictly via red X button (zero shop/gem interaction).

### Empirical Overnight Run Results (8.5 hours, 36 blocks, 168 matches):
- True Record: 0 wins, 168 losses (ground-truth validated on end-of-match victory/defeat banner positions).
- Offensive progress:
  * Hog frequency maxed out at 3.7 per match (at the physical elixir cycle ceiling for Hog 2.6).
  * Push conversion rate rose to 76% - 83% across 115+ pushes.
  * Average enemy tower damage: ~1.0 tower destroyed/match.
- Defensive collapse:
  * The bot loses every match because it cannot defend counter-pushes. In Clash Royale, Hog 2.6 wins through razor-thin positive elixir trades, kiting, and Cannon-pull micro-interactions.
- Hand-written rule-based policy (`scripts/heuristic_policy.py`) was tested and performed worse than Model+Shims (turtled, starved offense, scored 0.33 crowns/block).

### Critical Bottlenecks & Known Issues:
1. Shifting Tower HP Bar Bug: Ally princess tower HP detection frequently reports 0.00 on full 3346 HP towers because in-game HP bar vertical coordinates shift between matches (y 1160-1177 vs 1177-1194). Fixed pixel ROIs fail. Defensive performance cannot currently be measured accurately.
2. Latency & Race Conditions: ~800ms-1200ms perception-to-tap latency causes hand card state to shift before taps land (~149 rejected decisions/night).
3. Checkpoint Distribution Mismatch: The model was trained offline against a scripted Golem bot. Real ~5500 trophy ladder opponents play diverse archetypes (Bait, Bridge Spam, Fast Cycle, Beatdown).
4. Long-Term RL Goal: Our ultimate destination is full, robust Reinforcement Learning that masters micro-interactions, elixir management, deck adaptation, and strategy.

---

### Request for In-Depth Technical Advice:
Please provide an exhaustive, highly technical, and deeply reasoned advisory document for this project. Do not give a brief high-level summary; provide thorough explanations, formulas/pseudocode, system diagrams, and actionable blueprints covering:

1. Immediate Computer Vision / Perception Fixes:
   - How to permanently solve the shifting tower HP bar problem (dynamic ROI anchoring, landmark alignment, template matching, level badge detection, OCR, or contour analysis).
   - Improving unit detection fidelity and handling overlapping swarms.

2. Latency Reduction & Actuation Architecture:
   - How to reduce ADB latency (e.g. Scrcpy / Minicap / shared memory framebuffer / raw socket ADB protocols vs exec-out screencap).
   - Predictive state estimation / action queuing to eliminate stale hand-card rejections.

3. Tactical Hog 2.6 Micro-Defense Formulation:
   - Algorithmic formulation of Hog 2.6 defensive mechanics: kiting geometry (Ice Golem/Ice Spirit pulling across lanes), 4-3/2-3 Cannon pull placements, staggered placements against splash units, and spell trade calculations.

4. The Roadmap to True Reinforcement Learning:
   - Phase 1: High-fidelity Data Generation & Imitation Learning (harvesting top-ladder replays from RoyaleAPI / YouTube / screen recorders; behavioral cloning with transformer policies).
   - Phase 2: Simulation vs Live Environment (analyzing headless simulators like ClashAI vs self-play on parallel emulator farms).
   - Phase 3: Modern RL Algorithms & Reward Design (PPO, SAC, Decision Transformer, Offline RL with Conservative Q-Learning / IQL, self-play league training like AlphaStar / OpenAI Five).
   - State representation, action space discretization, credit assignment, and shaping rewards (elixir advantage, tower HP deltas, lane pressure) to prevent degenerate policies.

5. Priority Action Matrix & Milestones:
   - A sequenced chronological roadmap (Day 1-7, Month 1, Month 3, Month 6) to take HastyCR from 0-168 to a positive ladder win rate, and ultimately a top-tier RL agent.
"""

MODELS = [
    {"name": "GLM_5", "id": "zai.glm-5", "region": "us-east-1"},
    {"name": "DeepSeek_3_2", "id": "deepseek.v3.2", "region": "us-east-1"},
    {"name": "Kimi_2_5_Thinking", "id": "moonshot.kimi-k2-thinking", "region": "us-east-1"},
    {"name": "Kimi_2_5", "id": "moonshotai.kimi-k2.5", "region": "us-east-1"},
    {"name": "Qwen_3_Next_80B", "id": "qwen.qwen3-next-80b-a3b", "region": "us-east-1"},
    {"name": "Qwen_3_Coder_Next", "id": "qwen.qwen3-coder-next", "region": "us-east-1"},
    {"name": "Mistral_Large_3_675B", "id": "mistral.mistral-large-3-675b-instruct", "region": "us-east-1"},
    {"name": "OpenAI_GPT_OSS_120B", "id": "openai.gpt-oss-120b-1:0", "region": "us-east-1"},
    {"name": "Llama_3_3_70B", "id": "us.meta.llama3-3-70b-instruct-v1:0", "region": "us-east-1"},
]

def query_single_model(model_info):
    name = model_info["name"]
    model_id = model_info["id"]
    region = model_info["region"]
    out_file = os.path.join(OUTPUT_DIR, f"{name}.txt")
    print(f"[*] Dispatching query to {name} ({model_id})...", flush=True)
    
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": PROMPT}]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 4096,
            "temperature": 0.7
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {BEDROCK_KEY}",
            "Content-Type": "application/json"
        }
    )
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("output", {}).get("message", {}).get("content", [])
            response_text = ""
            for block in content:
                if "text" in block:
                    response_text += block["text"]
                elif "reasoningContent" in block:
                    reasoning = block['reasoningContent'].get('reasoningText', {}).get('text', '')
                    response_text += f"\n[THINKING / REASONING]\n{reasoning}\n[/THINKING / REASONING]\n\n"
            
            elapsed = time.time() - start_time
            print(f"[+] COMPLETED: {name} in {elapsed:.2f}s ({len(response_text)} chars)", flush=True)
            
            header = f"# Model Advice: {name}\n# Model ID: {model_id}\n# Response Time: {elapsed:.2f}s\n# Output Characters: {len(response_text)}\n\n"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(header + response_text)
            return True, name, elapsed, len(response_text)
            
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        print(f"[-] FAILED: {name} HTTP Error {e.code}: {err[:120]}", flush=True)
        return False, name, 0, err
    except Exception as e:
        print(f"[-] FAILED: {name} Error: {e}", flush=True)
        return False, name, 0, str(e)

if __name__ == "__main__":
    print(f"Starting parallel multi-model evaluation panel. Workers: {len(MODELS)}", flush=True)
    start_all = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=len(MODELS)) as executor:
        futures = {executor.submit(query_single_model, m): m for m in MODELS}
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            
    total_time = time.time() - start_all
    print(f"\n================ ALL QUERIES FINISHED in {total_time:.2f}s ================", flush=True)
    for success, name, t, detail in sorted(results, key=lambda x: x[1]):
        status = "SUCCESS" if success else "FAILED"
        print(f"{name:25} | {status:7} | {t:6.2f}s | {detail}", flush=True)
